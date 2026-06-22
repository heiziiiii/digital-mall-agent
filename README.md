# 数码商城智能客服

![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Agent-009688?logo=fastapi&logoColor=white)
![PydanticAI](https://img.shields.io/badge/PydanticAI-Multi--Agent-0F766E)
![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.x-6DB33F?logo=springboot&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-Memory-DC382D?logo=redis&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-RAG-DC244C)

面向数码商城场景的智能客服系统，覆盖售前商品推荐、订单查询、物流追踪、售后申请、技术答疑、人工服务转接和历史会话管理。系统由 React 前端、Spring Cloud Gateway、Python 多 Agent 服务和 Spring AI MCP 工具服务组成。

## 功能亮点

- **多 Agent 协作**：编排 Agent 将用户问题拆分为商品、订单售后、技术支持、记忆总结等专家任务，并按依赖关系执行。
- **流式客服体验**：前端通过 SSE 展示 Agent 思考、工具调用和最终回复过程。
- **人工确认机制**：创建订单、创建售后申请、创建人工服务单等写操作会先返回确认卡片，用户确认后才执行。
- **分层记忆**：本地缓存、Redis、MySQL、Qdrant 分别承载运行态、近期上下文、消息流水和长期语义记忆。
- **Hybrid RAG**：商品详情和售后知识库同时支持关键词召回、向量召回和融合排序。
- **客户自助页面**：支持查看我的订单、订单详情、撤销待付款订单、查看我的售后和历史会话。

## 演示

客服主界面：

![客服主界面](image/README/1782146858431.png)

复杂问题编排解决：

![复杂问题编排解决](image/README/1782155379299.png)

关键写操作用户确认：

![关键写操作用户确认](image/README/1782155459515.png)

## 技术架构

```mermaid
graph LR
    UI[React 前端] --> GW[API Gateway :8002]
    GW --> AGENT[Python Agent :8001]
    GW --> CUSTOMER[MCP Customer REST]
    AGENT --> MCP[MCP SSE Server :8080]
    MCP --> MYSQL[(MySQL :3307)]
    MCP --> QDRANT[(Qdrant :6333/:6334)]
    AGENT --> REDIS[(Redis :6379)]
    GW --> REDIS
```

请求主链路：

```text
React 前端
  -> API Gateway
       -> /api/auth/**      登录、登出、当前用户、历史会话
       -> /api/agent/**     聊天、流式回复、暂停恢复、确认动作
       -> /api/customer/**  订单和售后自助页面
  -> Python Agent
       -> MCP SSE 工具调用
  -> MCP Server
       -> MySQL / Redis / Qdrant
```

## 模块说明

| 模块         | 目录                                              | 说明                                                                    |
| ------------ | ------------------------------------------------- | ----------------------------------------------------------------------- |
| 前端应用     | [`frontend/`](frontend/)                           | React + TypeScript + Vite 客服界面，只访问 API Gateway。                |
| Python Agent | [`Agent/src/agent/`](Agent/src/agent/)             | 基于 FastAPI 与 PydanticAI 的多 Agent 编排、流式响应、记忆和用户确认。  |
| API Gateway  | [`Agent/src/api-gateway/`](Agent/src/api-gateway/) | Spring Cloud Gateway，负责登录鉴权、JWT、路由转发、身份透传、历史会话。 |
| MCP Server   | [`MCP/`](MCP/)                                     | Spring AI MCP 工具服务，封装商品、订单、售后、知识库和人工服务能力。    |

## 环境要求

- Node.js 18+
- JDK 17+
- Maven 3.9+
- Python 3.10+
- Docker / Docker Compose
- 可选：DashScope 兼容 OpenAI 接口 Key，用于 LLM 与 embedding

## 快速启动

建议按下面顺序启动。MCP 的 Docker Compose 会同时拉起 MCP 应用、MySQL、Redis 和 Qdrant。

### 1. 启动 MCP 与基础服务

```bash
cd MCP
docker compose up -d
curl -X POST http://localhost:8080/admin/reindex
```

`/admin/reindex` 会从种子数据重建商品和知识库向量索引。没有真实 `DASHSCOPE_API_KEY` 时，服务仍可启动，检索能力会降级。

### 2. 启动 Python Agent

```bash
cd ../Agent/src/agent
conda activate ai
pip install -r requirements.txt
```

创建 `.env`，至少配置模型 Key 和 MCP 地址：

```env
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus
OPENAI_ORCHESTRATOR_MODEL=qwen3.5-plus
OPENAI_EXPERT_MODEL=qwen-turbo
OPENAI_MEMORY_MODEL=qwen-turbo

MCP_SERVER_URL=http://localhost:8080/sse
REDIS_URL=redis://localhost:6379/0
MYSQL_DSN=mysql+aiomysql://root:root@localhost:3307/digital_cs?charset=utf8mb4
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=agent_memory
```

启动服务：

```bash
python main.py --serve
```

### 3. 启动 API Gateway

```bash
cd ../api-gateway
```

如果使用上面的 MCP Compose，建议显式指定 MCP 地址：

```powershell
$env:JWT_SECRET = "replace-with-at-least-32-bytes-secret"
$env:MYSQL_USERNAME = "root"
$env:MYSQL_PASSWORD = "root"
$env:AGENT_SERVICE_URI = "http://127.0.0.1:8001"
$env:MCP_SERVICE_URI = "http://127.0.0.1:8080"
mvn spring-boot:run
```

本地开发可不设置 `JWT_SECRET`，系统会使用开发默认值；生产或共享环境请务必显式配置，并设置 `REQUIRE_ENV_JWT_SECRET=true`。

### 4. 启动前端

```bash
cd ../../../frontend
npm install
npm run dev
```

访问：`http://localhost:5173`

## 默认端口

| 服务                 | 地址                      |
| -------------------- | ------------------------- |
| 前端                 | `http://localhost:5173` |
| API Gateway          | `http://localhost:8002` |
| Python Agent         | `http://127.0.0.1:8001` |
| MCP Server           | `http://localhost:8080` |
| MySQL                | `localhost:3307`        |
| Redis                | `localhost:6379`        |
| Qdrant REST / Web UI | `http://localhost:6333` |
| Qdrant gRPC          | `localhost:6334`        |

## 常用接口

| 网关路径                         | 后端路径                | 说明                         |
| -------------------------------- | ----------------------- | ---------------------------- |
| `POST /api/auth/login`         | Gateway                 | 手机号和密码登录，返回 JWT。 |
| `POST /api/auth/logout`        | Gateway                 | 登出并拉黑当前 token。       |
| `GET /api/auth/me`             | Gateway                 | 当前登录用户。               |
| `GET /api/auth/history`        | Gateway                 | 历史客服会话列表。           |
| `POST /api/agent/run`          | Agent `POST /run`     | 单次非流式问答。             |
| `POST /api/agent/stream`       | Agent `POST /stream`  | SSE 流式问答。               |
| `POST /api/agent/confirm`      | Agent `POST /confirm` | 确认或拒绝待执行动作。       |
| `GET /api/customer/orders`     | MCP REST                | 当前用户订单列表。           |
| `GET /api/customer/aftersales` | MCP REST                | 当前用户售后列表。           |

## MCP 工具能力

| 工具                       | 说明                                 |
| -------------------------- | ------------------------------------ |
| `searchProducts`         | 按需求检索和推荐商品。               |
| `getProductDetail`       | 查询指定商品价格、库存、规格和详情。 |
| `queryOrder`             | 查询订单详情。                       |
| `listCustomerOrders`     | 列出当前客户订单。                   |
| `trackLogistics`         | 查询订单物流轨迹。                   |
| `createOrder`            | 创建待付款订单，需要用户确认。       |
| `queryAfterSale`         | 查询售后单详情。                     |
| `listOrderAfterSales`    | 查询某个订单关联的售后记录。         |
| `listCustomerAfterSales` | 列出当前客户售后申请。               |
| `createAfterSale`        | 创建售后申请，需要用户确认。         |
| `createHumanService`     | 创建人工服务单，需要用户确认。       |
| `searchKnowledge`        | 检索售后政策、故障排查和使用知识。   |

## 测试

```bash
# 前端
cd frontend
npm test
npm run build

# Python Agent
cd ../Agent/src/agent
pytest

# API Gateway
cd ../api-gateway
mvn test

# MCP Server
cd ../../../MCP
mvn test
```

## 验证与排障

健康检查：

```bash
curl http://localhost:8002/actuator/health
curl http://localhost:8002/api/agent/health
curl http://localhost:8080/actuator/health
```

常见问题：

- **Agent 连不上 MCP**：确认 `MCP_SERVER_URL=http://localhost:8080/sse`，并检查 `docker compose ps`。
- **Gateway 的客户自助接口 404 或连接失败**：确认 `MCP_SERVICE_URI=http://127.0.0.1:8080`。
- **向量检索结果为空**：先执行 `POST /admin/reindex`；没有 `DASHSCOPE_API_KEY` 时会降级为关键词检索。
- **MySQL 连接失败**：Compose 宿主机端口是 `3307`，容器内端口是 `3306`。
- **前端跨域或接口失败**：开发环境前端只请求 `/api/*`，Vite 会代理到 `http://127.0.0.1:8002`。

## 项目结构

```text
.
├── frontend/                 # React + TypeScript 前端
├── Agent/
│   └── src/
│       ├── agent/            # Python 多 Agent 服务
│       └── api-gateway/      # Spring Cloud Gateway
├── MCP/                      # Spring AI MCP 工具服务与基础服务 Compose
├── image/README/             # README 演示截图
└── screenshots/              # 补充演示截图
```

## 文档入口

- [前端文档](frontend/README.md)
- [后端总览](Agent/README.md)
- [Python Agent 文档](Agent/src/agent/README.md)
- [API Gateway 文档](Agent/src/api-gateway/README.md)
- [MCP Server 文档](MCP/README.md)
