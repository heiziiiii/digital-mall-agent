# MCP 工具说明（tools 包）

> 本包下每个 `*Tools` 类的 `@Tool` 方法即一个对外暴露的 MCP 工具。
> `@Tool` / `@ToolParam` 的中文 `description` 是大模型唯一可见的语义契约，**视同对外 API，修改即变更接口**。
> 工具类只做参数转换并调用 `service`，不写业务逻辑。新建工具类**必须**在
> [McpServerApplication.java](../src/main/java/com/digitalcs/mcp/McpServerApplication.java) 的 `customerServiceTools` Bean 的 `.toolObjects(...)` 中注册，否则不会被暴露。
>
> **检索说明**：商品详情与售后知识统一走 Qdrant 混合检索（[VectorSearchService](../src/main/java/com/digitalcs/mcp/vector/VectorSearchService.java)）——sparse(jieba 分词关键词，服务端 IDF) + dense(DashScope 语义) 双路 + RRF 融合。
> 未配置真实 DashScope key（或 key 以 `sk-dummy` 开头）时 dense 通道关闭，检索退化为纯 sparse 关键词检索；Qdrant 不可用时检索类工具返回空，其余 MySQL 查询不受影响。
>
> **鉴权说明（自助模式）**：凡涉及个人数据（订单、物流、售后、客户资料）的工具，**必须传入当前操作用户ID `userId`（即登录客户本人）**，由 [AuthService](../src/main/java/com/digitalcs/mcp/auth/AuthService.java) 做「数据归属」校验：
> - 按订单号/售后单号查询的工具，仅当该资源归属 `userId` 时返回，否则返回 `{authorized:false, message}`；资源不存在则返回 `{found:false, message}`。
> - 「查我的订单/售后/资料」类工具直接以 `userId` 为客户主键，只返回本人数据，无法查他人。
> - `AuthService` 只校验数据归属、不验证身份真伪——`userId` 的真实性应由上游会话/网关保证（本服务假定传入的 `userId` 即已认证的当前客户）。

共 **5 个工具类 / 11 个工具**：商品 2 · 订单 3 · 售后 4 · 知识 1 · 用户 1。

---

## 一、商品（[ProductTools](../src/main/java/com/digitalcs/mcp/tools/ProductTools.java)）

数据跨库：MySQL `product` 为**纯库存表**（仅 stock/状态/展示名）；价格/发布时间/详情（名称/分类/品牌/描述/规格）在 Qdrant，按 `productNo` 关联。

### `searchProducts` — 混合检索/筛选商品

按自然语言/关键词搜索数码商品（手机/电脑/相机/配件等），并支持按类目、品牌、价格区间过滤与排序，返回匹配商品列表（含名称/参数规格等详情与价格、库存）。
流程：Qdrant 混合检索（sparse 关键词 + dense 语义 + RRF 融合，**类目/品牌作为 payload 过滤下推 Qdrant**）召回详情与价格 → 按 productNo 回 MySQL 补库存 → **内存按价格区间过滤 → 排序 → 截断至 limit**。
`query` 为空时退化为「纯过滤浏览」（无向量打分，仅按类目/品牌/价格筛选）。

| 入参         | 类型    | 必填 | 说明                                                                                                                                  |
| ------------ | ------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `query`    | String  | 否   | 搜索关键词或自然语言描述，如 `静音空调`、`5000mAh 长续航手机`；为空则按类目/品牌/价格筛选浏览                                     |
| `category` | String  | 否   | 类目过滤，需与商品类目一致，如 `手机`、`笔记本电脑`                                                                               |
| `brand`    | String  | 否   | 品牌过滤，如 `华为`、`苹果`、`小米`                                                                                             |
| `minPrice` | Double  | 否   | 最低价格（元，含此价）                                                                                                                |
| `maxPrice` | Double  | 否   | 最高价格（元，含此价）                                                                                                                |
| `sortBy`   | Enum    | 否   | 排序方式：`relevance` 相关度 / `price_asc` 价格升序 / `price_desc` 价格降序 / `stock_desc` 库存降序 / `newest` 发布时间最近 |
| `limit`    | Integer | 否   | 返回数量上限，默认 10                                                                                                                 |

> **默认排序**：不传 `sortBy` 时——有 `query` 按 `relevance`，无 `query`（纯浏览/无任何参数）按 `newest` 发布时间最近优先。
> **排序枚举说明**：仅按已有数据设计。`product` 表无销量/评分字段，故未提供 `sales_desc`/`rating_desc`，以 `stock_desc`（货源充足优先）替代；价格/发布时间取自 Qdrant payload。

**返回**：`List<Map>`，每项含详情字段（productNo/name/subtitle/category/brand/description/specs/`publishedAt`）+ `price`/`marketPrice`（来自 Qdrant）+ `stock`/`inStock`（来自 MySQL）。检索不可用时返回空列表。指定价格区间但某商品无价格数据时，该商品被排除。

### `getProductDetail` — 基于商品编号查商品完整信息（含库存与价格）

根据商品编号查询单个商品的完整信息：名称、参数规格、描述、发布时间、价格与库存（Qdrant 详情/价格 + MySQL 库存合并）。**查库存、查价格均用此工具**（原 `checkStock` 已并入）。

| 入参          | 类型   | 必填 | 说明                 |
| ------------- | ------ | ---- | -------------------- |
| `productNo` | String | 是   | 商品编号(product_no) |

**返回**：`Map` — 命中 `{found:true, ...合并字段}`（productNo/name/.../price/marketPrice/publishedAt/stock/inStock）；未命中 `{found:false, message}`。

---

## 二、订单与物流（[OrderTools](../src/main/java/com/digitalcs/mcp/tools/OrderTools.java)）

数据源：MySQL `orders`（明细 `items`、物流 `logistics` 折叠为 JSON 列）。

### `queryOrder` — 查订单详情

**用途**：客户提供订单号、要核对这一单情况时使用（如『我这单买了什么』『到哪一步了』），一次返回明细+物流+售后概况，是处理订单类问题的第一步。客户说不出订单号时先用 `listCustomerOrders` 找。**仅返回归属当前用户的订单。**

| 入参        | 类型   | 必填 | 说明                                  |
| ----------- | ------ | ---- | ------------------------------------- |
| `userId`  | Long   | 是   | 当前操作用户ID(登录客户本人)，用于鉴权 |
| `orderNo` | String | 是   | 订单号(order_no)                      |

**返回**：`{found:true, order}`；未找到 `{found:false, message}`；订单不属于该用户 `{authorized:false, message}`。

### `listCustomerOrders` — 查我的全部订单

**用途**：客户说不出订单号、想看名下订单或最近买过什么时使用（如『帮我看下我有哪些订单』），据此定位订单号后再用 `queryOrder`。按时间倒序。**自助模式：只返回 `userId` 本人的订单。**

| 入参       | 类型 | 必填 | 说明                                         |
| ---------- | ---- | ---- | -------------------------------------------- |
| `userId` | Long | 是   | 当前操作用户ID(登录客户本人)，只返回其本人订单 |

**返回**：`{authorized:true, orders:List<Orders>}`；缺少身份 `{authorized:false, message}`。

### `trackLogistics` — 查物流轨迹

**用途**：客户只关心『发货没』『快递到哪了』『何时能到』时使用。订单未发货时无轨迹。只需了解订单整体用 `queryOrder` 即可。**仅返回归属当前用户的订单物流。**

| 入参        | 类型   | 必填 | 说明                                  |
| ----------- | ------ | ---- | ------------------------------------- |
| `userId`  | Long   | 是   | 当前操作用户ID(登录客户本人)，用于鉴权 |
| `orderNo` | String | 是   | 订单号(order_no)                      |

**返回**：`{found:true, logistics}`；未找到/无发货记录 `{found:false, message}`；订单不属于该用户 `{authorized:false, message}`。

---

## 三、售后（[AfterSaleTools](../src/main/java/com/digitalcs/mcp/tools/AfterSaleTools.java)）

数据源：MySQL `after_sale`（独立售后记录库，关联订单号与客户）。

### `queryAfterSale` — 查售后单详情

**用途**：客户提供售后单号、追问某次售后的进度或结果时使用（如『我的退款审核了吗』）。说不出单号时先用 `listOrderAfterSales` / `listCustomerAfterSales` 找。**仅返回归属当前用户的售后单。**

| 入参            | 类型   | 必填 | 说明                                  |
| --------------- | ------ | ---- | ------------------------------------- |
| `userId`      | Long   | 是   | 当前操作用户ID(登录客户本人)，用于鉴权 |
| `afterSaleNo` | String | 是   | 售后单号(after_sale_no)               |

**返回**：`{found:true, afterSale}`；未找到 `{found:false, message}`；不属于该用户 `{authorized:false, message}`。

### `listOrderAfterSales` — 查订单的售后单

**用途**：确认某笔订单是否已发起过售后（避免重复申请）、或列出该单所有售后记录时使用。查单条进度用 `queryAfterSale`。**仅当订单归属当前用户时返回。**

| 入参        | 类型   | 必填 | 说明                                  |
| ----------- | ------ | ---- | ------------------------------------- |
| `userId`  | Long   | 是   | 当前操作用户ID(登录客户本人)，用于鉴权 |
| `orderNo` | String | 是   | 订单号(order_no)                      |

**返回**：`{authorized:true, afterSales:List<AfterSale>}`；订单未找到 `{found:false, message}`；订单不属于该用户 `{authorized:false, message}`。

### `listCustomerAfterSales` — 查我的售后单

**用途**：客户笼统问『我的售后/退款都怎么样了』、想总览全部售后申请时使用。**自助模式：只返回 `userId` 本人的售后单。**

| 入参       | 类型 | 必填 | 说明                                           |
| ---------- | ---- | ---- | ---------------------------------------------- |
| `userId` | Long | 是   | 当前操作用户ID(登录客户本人)，只返回其本人售后单 |

**返回**：`{authorized:true, afterSales:List<AfterSale>}`；缺少身份 `{authorized:false, message}`。

### `createAfterSale` — 创建售后单

**用途**：客户明确要对某订单发起售后申请（退货退款/换货/仅退款/维修）时使用（如『这个我要退货』『屏幕坏了想保修』）。**写入操作**：仅代提交、进入待审核，不代表审核通过、不会立即退款退货，须先确认订单号/类型/原因。只是咨询政策流程用 `searchKnowledge`。**仅当订单归属当前用户时才允许发起**，校验订单存在并回填客户。

| 入参             | 类型       | 必填 | 说明                                    |
| ---------------- | ---------- | ---- | --------------------------------------- |
| `userId`       | Long       | 是   | 当前操作用户ID(登录客户本人)，用于鉴权   |
| `orderNo`      | String     | 是   | 订单号(order_no)                        |
| `type`         | Integer    | 是   | 售后类型：1退货退款 2换货 3仅退款 4维修 |
| `reason`       | String     | 是   | 售后原因                                |

**返回**：`{authorized:true, created:true, afterSale}`；订单不存在 `{found:false, message}`；订单不属于该用户 `{authorized:false, message}`。

### `createHumanService` — 创建人工服务单

**用途**：当客户明确要求人工客服、投诉升级、情绪明显不满，或问题经客服/工具处理后仍难以解决时使用。**写入操作**：仅创建待处理的人工服务单，不代表已接入人工或承诺响应时效；须先确认原因，可关联订单号或售后单号。

| 入参 | 类型 | 必填 | 说明 |
| ---- | ---- | ---- | ---- |
| `userId` | Long | 是 | 当前操作用户ID(登录客户本人)，用于鉴权 |
| `reason` | String | 是 | 转人工原因/用户诉求摘要 |
| `orderNo` | String | 否 | 关联订单号，没有则留空 |
| `afterSaleNo` | String | 否 | 关联售后单号，没有则留空 |

**返回**：`{authorized:true, created:true, humanService}`；关联订单/售后不存在 `{found:false, message}`；不属于该用户 `{authorized:false, message}`。

---

## 四、售后知识库（[KnowledgeTools](../src/main/java/com/digitalcs/mcp/tools/KnowledgeTools.java)）— 纯 Qdrant

数据源：Qdrant（`type=knowledge`），权威源为 `resources/seed/knowledge.json`，经 `POST /admin/reindex` 灌入。

### `searchKnowledge` — 知识库混合检索

**用途**：回答与具体订单/商品数据无关的通用问题——使用方法、故障排查、保养技巧、售后政策与流程（如『充电发热怎么办』『退货需满足什么条件』）。只提供通用知识，不查任何客户的订单/库存/售后状态（查具体数据用对应工具，真要申请售后用 `createAfterSale`）。
实现：Qdrant 混合检索（sparse 关键词 + dense 语义 + RRF 融合），结果直接取 payload，不回 MySQL。

| 入参      | 类型    | 必填 | 说明                                                          |
| --------- | ------- | ---- | ------------------------------------------------------------- |
| `query` | String  | 是   | 客户问题或检索关键词，如 `充电发热怎么办`、`如何申请退货` |
| `topK`  | Integer | 否   | 返回数量上限，默认 5                                          |

**返回**：`{query, results:[{kbType, title, content, keywords}]}`。检索不可用时 `results` 为空。
