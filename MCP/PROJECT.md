# 数码智能客服系统 — MCP 服务器 · 项目文档

> 基于 **Spring AI Alibaba**（Spring Boot 3 + DashScope）构建的 **MCP（Model Context Protocol）服务器**。
> 它把数码产品客服的后端能力——商品、订单物流、售后、知识库、客户资料——封装为一组 **MCP 工具**，
> 通过 WebMVC **SSE 传输**暴露给大模型 Agent 调用。**本服务本身不参与对话，只作为「工具提供方」存在**。
>
> **检索架构**：所有检索（商品详情、售后知识）统一由 **Qdrant 混合检索**完成——sparse(jieba 分词关键词，服务端 IDF) + dense(DashScope 语义) 双路 + 服务端 RRF 融合，
> 直连原生 `QdrantClient` 走 Query API（Spring AI VectorStore 不支持混合检索）；MySQL 仅作交易数据的权威存储

---

## 一、存储划分（核心约定）

| 存储             | 职责                                           | 内容                                                                                                         |
| ---------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| **MySQL**  | 交易数据权威库（4 张表）                       | 用户信息 `customer`、商品库存 `product`(纯库存，价格在 Qdrant)、订单 `orders`、售后记录 `after_sale` |
| **Qdrant** | 语义检索库（1 collection，`type` 区分 2 类） | 商品详细信息(`type=product`)、售后技术问题解决方案知识库(`type=knowledge`)                               |

- **商品按 `productNo` 跨库关联**：MySQL `product` 为纯库存表（仅 stock/状态/展示名）；价格、发布时间、名称/分类/品牌/描述/规格等详情在 Qdrant。
  搜索 → Qdrant 召回详情与价格 → 回 MySQL 批量补库存 → 合并返回。
- **售后知识库纯 Qdrant 承载**：检索结果直接取 Qdrant payload（title/content），不回 MySQL。
- **Qdrant 数据权威源 = classpath 种子 JSON**（`seed/products.json`、`seed/knowledge.json`），
  由 `POST /admin/reindex` 灌入；首次部署或数据修复时调用。

---

## 二、项目功能（MCP 工具）

### 1. 商品（Product）

| 工具                 | 功能                                                                                                                                     | 返回                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `searchProducts`   | **混合检索/筛选**商品（Qdrant sparse+dense+RRF 召回 + 类目/品牌过滤 + 价格区间过滤/排序 + MySQL 库存合并；无参默认按发布时间最近） | `List<Map>`（详情字段 + price/marketPrice/publishedAt + stock/inStock） |
| `getProductDetail` | 按商品编号查完整信息（Qdrant 详情/价格 + MySQL 库存合并，含查库存/查价格）                                                               | `Map`（found + 合并字段）                                               |

### 2. 订单与物流（Order）

| 工具                   | 功能                         |
| ---------------------- | ---------------------------- |
| `queryOrder`         | 查当前用户订单详情（含明细、物流），需传 `userId` 鉴权 |
| `listCustomerOrders` | 查当前用户本人全部订单（时间倒序），需传 `userId` |
| `trackLogistics`     | 查当前用户订单物流发货状态与轨迹，需传 `userId` 鉴权 |

### 3. 售后（AfterSale）

| 工具                       | 功能                                              |
| -------------------------- | ------------------------------------------------- |
| `queryAfterSale`         | 按售后单号查当前用户售后单详情，需传 `userId` 鉴权 |
| `listOrderAfterSales`    | 查当前用户某订单的全部售后单，需传 `userId` 鉴权 |
| `listCustomerAfterSales` | 查当前用户本人的全部售后单，需传 `userId` |
| `createAfterSale`        | 为当前用户订单创建售后单（退货退款/换货/仅退款/维修），需传 `userId` 鉴权，初始待审 |
| `createHumanService`     | 为当前用户创建人工服务单，可关联订单或售后单，需传 `userId` 鉴权，初始待处理 |

### 4. 售后知识库（Knowledge）— 纯 Qdrant 混合检索

| 工具                | 功能                                                   | 返回                                                   |
| ------------------- | ------------------------------------------------------ | ------------------------------------------------------ |
| `searchKnowledge` | 售后技术问题解决方案知识库混合检索（sparse+dense+RRF） | `{query, results:[{kbType,title,content,keywords}]}` |

### 5. 用户信息（Customer）

| 工具                | 功能                                             |
| ------------------- | ------------------------------------------------ |
| `getCustomerById` | 查询当前用户本人资料，需传 `userId`；不能查他人 |

> **降级保障**：未配置真实 DashScope key（或 key 以 `sk-dummy` 开头）时 dense 通道关闭，检索退化为纯 sparse 关键词检索（`searchProducts`/`searchKnowledge` 仍可用）；
> Qdrant 不可用时检索返回空。两种情况其余 MySQL 查询均不受影响，服务始终可正常启动。

---

## 三、项目结构

### 技术栈

- **Java 17 / Spring Boot 3.4.5**
- **Spring AI MCP Server**（`spring-ai-starter-mcp-server-webmvc`，SSE 传输）
- **Spring AI Alibaba**（`spring-ai-alibaba-starter-dashscope`）— dense 文本嵌入
- **Qdrant 混合检索**：`spring-ai-starter-vector-store-qdrant` 提供 `QdrantClient`/`EmbeddingModel` 自动配置；检索直连原生 `io.qdrant:client` 走 Query API（sparse+dense + RRF）— 唯一检索后端
- **jieba-analysis**（`com.huaban:jieba-analysis`）— sparse 向量中文分词
- **MyBatis-Plus 3.5.9 + MySQL 8.0**
- **Lombok**（构造注入、`@Data`）

### 目录结构

```
src/main/java/com/digitalcs/mcp
├── McpServerApplication.java     # 入口：注册 ToolCallbackProvider、@MapperScan
├── tools/                        # @Tool 方法 → MCP 工具（面向 LLM 的契约层）
│   ├── ProductTools.java
│   ├── OrderTools.java
│   ├── AfterSaleTools.java
│   ├── KnowledgeTools.java
│   └── CustomerTools.java
├── service/                      # 业务逻辑、跨库组装、降级策略
│   ├── ProductService.java       # Qdrant 详情 + MySQL 库存合并
│   ├── OrderService.java
│   ├── AfterSaleService.java
│   ├── KnowledgeService.java     # 纯 Qdrant
│   └── CustomerService.java
├── vector/                       # Qdrant 混合检索，全项目唯一检索入口
│   ├── VectorSearchService.java  # 直连原生 QdrantClient：sparse+dense 检索/写入/建集合
│   └── SparseVectorizer.java     # jieba 分词 → TF sparse 向量
├── mapper/                       # MyBatis-Plus BaseMapper（纯条件构造器，无自定义 SQL）
│   ├── ProductMapper.java
│   ├── OrdersMapper.java
│   ├── AfterSaleMapper.java
│   └── CustomerMapper.java
├── entity/                       # MySQL 表实体
│   ├── Product.java              # 纯库存字段（价格在 Qdrant）
│   ├── Orders.java               # 内含 Item / Logistics / Trace（JSON 列）
│   ├── AfterSale.java
│   └── Customer.java
└── web/IndexAdminController.java # /admin/reindex 从种子 JSON 灌 Qdrant

src/main/resources/
├── application.yml               # 数据源、DashScope、Qdrant、MCP server、MyBatis-Plus 配置
├── db/{schema,seed}.sql          # MySQL 建表 + 冒烟数据
└── seed/{products,knowledge}.json  # Qdrant 商品详情 / 售后知识种子（Qdrant 权威源）
```

### 四层架构

```
tools/    @Tool 方法    面向 LLM 的契约层，中文 description 即 API 语义
   ↓
service/  业务逻辑      跨库组装(商品 Qdrant 详情 + MySQL 库存)、事务、降级
   ↓
mapper/ + vector/       MySQL(BaseMapper 条件构造器) 与 Qdrant(VectorSearchService) 两路数据访问
   ↓
entity/   领域模型      MySQL 表实体；Qdrant 数据以 Document payload 形态流转
```

---

## 四、实现方式

### Qdrant 混合检索（核心）

核心在 [VectorSearchService.java](src/main/java/com/digitalcs/mcp/vector/VectorSearchService.java)，直连注入的原生 `QdrantClient` + `EmbeddingModel` + [SparseVectorizer](src/main/java/com/digitalcs/mcp/vector/SparseVectorizer.java)：

- `search(type, query, topK[, equalsFilters])` → 按 `type` 定位集合后走 Query API：sparse 关键词 + dense 语义两路 prefetch（各带附加 payload 等值过滤如 category/brand、limit=topK*4），顶层 `Fusion.RRF` 融合，返回 `List<Document>`（payload→metadata）。`query` 为空时退化为纯过滤浏览（无向量、仅按过滤条件 scroll）。
- `fetchByBizId(type, bizId)` → 对应集合内纯 payload 过滤（`bizId==..`）的 limit=1 查询，用于按 productNo 取单条商品详情。
- `index(type, List<Record>)` → 写入 `type` 对应集合的原生 `upsert`：每条写 sparse(恒有) + dense(嵌入可用时)，point id 由 `type:bizId` 派生稳定 UUID，payload 携带业务字段。
- `ensureCollections()` → 商品/知识两个集合不存在则建（dense 1024/COSINE + sparse IDF 命名向量），由 `/admin/reindex` 调用。
- 商品与知识**分库存储**，各自独立 collection（`digital_cs_products` / `digital_cs_knowledge`），集合即数据分区，`type` 在代码内映射到对应集合。
- **sparse 向量**：[SparseVectorizer](src/main/java/com/digitalcs/mcp/vector/SparseVectorizer.java) jieba 切词 → token 稳定哈希为下标、TF 为值；IDF 由 Qdrant 服务端（sparse modifier=IDF）计算。
- **降级**：`embeddingEnabled()` 判定 key 有效性（空 / `sk-dummy` 开头 = 未配置）；未配置时 dense 关闭，检索退化为纯 sparse 关键词；Qdrant 抛异常时返回空、写入跳过。

### 4. 商品跨库合并

[ProductService.java](src/main/java/com/digitalcs/mcp/service/ProductService.java)：
`search` 先 Qdrant 召回详情/价格 Document（类目/品牌过滤下推 Qdrant）→ 提取 productNo → 一次 `IN` 查询回 MySQL 取库存 → 内存按价格区间过滤、排序、截断后合并为 `List<Map>`。无 query 时按发布时间(`publishedAt`)最近优先。价格存于 Qdrant payload（字符串），合并时解析为 `BigDecimal`。

## 六、扩展指引

| 想做的事            | 怎么做                                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------ |
| 新增一个客服能力    | 在对应 `*Tools` 类加 `@Tool` 方法，写清中文 `description`                                              |
| 新增一类工具        | 新建 `*Tools` 类，并在 `customerServiceTools` Bean 的 `.toolObjects(...)` 中追加                       |
| 改工具对外语义      | 修改 `@Tool` / `@ToolParam` 的 `description`（等同改 API）                                             |
| 新增可检索数据      | 写入 `seed/*.json`，调 `/admin/reindex` 灌 Qdrant；如需新类别在 `VectorSearchService` 加 `type` 常量 |
| 加 MySQL 业务表查询 | Mapper 继承 `BaseMapper` 用条件构造器                                                                      |
