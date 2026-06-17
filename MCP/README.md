# 数码智能客服系统 — MCP 服务器

基于 **Spring AI Alibaba**（Spring Boot 3 + DashScope）构建的 MCP（Model Context Protocol）服务器，
把数码产品客服后端能力（商品、订单物流、售后、知识库、客户资料）封装为 MCP 工具，供大模型 Agent 调用。
**所有检索统一由 Qdrant 向量语义完成**，MySQL 仅作交易数据的权威存储。

## 存储划分
- **MySQL（4 个权威库）**：用户信息 `customer`、商品库存 `product`、订单 `orders`、售后记录 `after_sale`。
- **Qdrant（2 个独立语义集合，分库存储）**：商品详细信息 `digital_cs_products`、售后技术问题解决方案知识库 `digital_cs_knowledge`。
  数据权威源为 classpath 种子 JSON（`seed/products.json`、`seed/knowledge.json`），由 `POST /admin/reindex` 灌入。
- 商品按 `productNo` 关联：搜索走 Qdrant 召回详情，再回 MySQL 取实时价格库存。

## 技术栈
- Java 17 / Spring Boot 3.4
- Spring AI Alibaba（`spring-ai-alibaba-starter-dashscope`）— 文本嵌入
- Spring AI MCP Server（`spring-ai-starter-mcp-server-webmvc`，SSE 传输）
- Spring AI Qdrant VectorStore（`spring-ai-starter-vector-store-qdrant`）
- MyBatis-Plus + MySQL 8.0

## 目录结构
```
src/main/java/com/digitalcs/mcp
├── McpServerApplication.java   # 入口，注册 ToolCallbackProvider
├── entity/                     # Customer/Product/Orders/AfterSale
├── mapper/                     # MyBatis-Plus BaseMapper（无自定义 SQL）
├── service/                    # 业务服务（检索委托 VectorSearchService）
├── vector/VectorSearchService.java  # Qdrant 语义检索/写入，全项目唯一检索入口
├── tools/                      # MCP 工具：Product/Order/AfterSale/Knowledge/Customer
└── web/IndexAdminController.java    # /admin/reindex 从种子 JSON 灌 Qdrant
src/main/resources/
├── db/schema.sql                       # MySQL 建表
└── seed/                               # 种子数据(docker 初始化 / POST /admin/reset 重置共用)
    ├── mysql.sql                       #   MySQL 冒烟数据(客户/库存/订单/售后)
    └── {products,knowledge}.json       #   Qdrant 商品详情 / 售后知识种子
```

## 快速开始

### 1. 初始化数据库
```sql
CREATE DATABASE digital_cs DEFAULT CHARSET utf8mb4;
USE digital_cs;
SOURCE src/main/resources/db/schema.sql;
SOURCE src/main/resources/seed/mysql.sql;   -- 可选：示例数据(含 TRUNCATE，会清空重置)
```
> 在 `application.yml` 中修改数据库 `username`/`password`。

### 2. 启用向量检索（检索能力依赖此项）
检索全部走 Qdrant + DashScope 嵌入。需启动 Qdrant 并配置真实 key，否则商品/知识检索返回空：
```bash
# Windows PowerShell
$env:DASHSCOPE_API_KEY = "sk-你的key"
```
> 未配置 key 时服务仍可正常启动，仅商品/知识语义检索降级为返回空；订单/售后/客户/库存查询不受影响。

### 3. 启动
```bash
mvn spring-boot:run
```
默认监听 `:8080`，MCP SSE 端点为 `/sse`。

### 4. 灌入 Qdrant（商品详情 + 售后知识）
```bash
curl -X POST http://localhost:8080/admin/reindex
# 返回 {"qdrantProducts":N,"qdrantKnowledge":M}
```

### 5. 验证 MCP 工具
```bash
npx @modelcontextprotocol/inspector   # Transport=SSE, URL=http://localhost:8080/sse
# 或：python mcp_test_client.py
```

## MCP 工具列表
| 工具 | 说明 |
|---|---|
| `searchProducts` / `getProductDetail` | 商品语义搜索 / 详情(含库存与价格) |
| `queryOrder` / `listCustomerOrders` / `trackLogistics` | 订单查询 / 当前用户本人订单 / 物流轨迹，需传 `userId` 鉴权 |
| `queryAfterSale` / `listOrderAfterSales` / `listCustomerAfterSales` / `createAfterSale` / `createHumanService` | 售后查询 / 创建售后单 / 创建人工服务单，需传 `userId` 鉴权 |
| `searchKnowledge` | 售后技术问题解决方案知识库语义检索（纯 Qdrant） |

## 检索说明
`VectorSearchService` 直连原生 `QdrantClient` 封装混合检索，商品详情与售后知识**分库存储**，
各自独立 collection（`digital_cs_products` / `digital_cs_knowledge`），由 `type` 映射到对应集合；payload 直接携带业务字段，知识检索结果无需回 MySQL。
两个集合均以 1024 维（DashScope text-embedding-v3）+ COSINE 距离的 dense 向量及 IDF sparse 向量创建。Qdrant / 嵌入不可用时检索降级为返回空，不影响服务启动。
