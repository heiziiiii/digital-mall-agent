# API Gateway

智能客服系统的统一后端入口，基于 Spring Boot 3 和 Spring Cloud Gateway 构建。它不负责 Agent 推理，也不直接实现 MCP 工具，而是把前端请求安全地路由到对应服务。

## 职责边界

- 登录、登出、当前用户信息。
- JWT 鉴权和 token 黑名单。
- 将用户身份透传给下游服务。
- 将 `/api/agent/**` 转发到 Python Agent。
- 将 `/api/customer/**` 转发到 MCP REST 接口。
- 读取和删除当前用户的历史客服会话。
- 提供 CORS、限流、访问日志等网关能力。

## 请求流向

```mermaid
graph LR
    FE[React 前端] --> GW[API Gateway :8002]
    GW --> AUTH[Auth Controller]
    GW --> AGENT[/api/agent/**]
    GW --> CUSTOMER[/api/customer/**]

    AGENT --> PY[Python Agent :8001]
    CUSTOMER --> MCP[MCP Server :8080]

    AUTH --> MYSQL[(MySQL)]
    AUTH --> REDIS[(Redis)]
    PY --> MYSQL
```

## 路由

### Agent 路由

`/api/agent/**` 经 `StripPrefix=2` 转发到 Python Agent。

| 网关路径 | 后端路径 | 说明 |
| --- | --- | --- |
| `/api/agent/run` | `POST /run` | 单次问答 |
| `/api/agent/stream` | `POST /stream` | SSE 流式问答 |
| `/api/agent/pause` | `POST /pause` | 暂停会话 |
| `/api/agent/resume` | `POST /resume` | 恢复会话 |
| `/api/agent/confirm` | `POST /confirm` | 确认或拒绝待执行动作 |
| `/api/agent/sessions/{id}` | `GET /sessions/{id}` | 查询会话状态 |
| `/api/agent/health` | `GET /health` | Agent 健康检查 |

### 客户自助路由

`/api/customer/**` 转发到 MCP 服务的 REST 接口，主要供前端订单和售后页面使用。

| 网关路径 | 说明 |
| --- | --- |
| `GET /api/customer/orders` | 当前用户订单列表 |
| `GET /api/customer/orders/{orderNo}` | 订单详情 |
| `POST /api/customer/orders` | 创建待付款订单 |
| `POST /api/customer/orders/{orderNo}/cancel` | 撤销待付款订单 |
| `GET /api/customer/aftersales` | 当前用户售后列表 |
| `GET /api/customer/aftersales/{afterSaleNo}` | 售后详情 |
| `POST /api/customer/aftersales/{afterSaleNo}/cancel` | 撤销售后申请 |

### 认证与历史会话

| 接口 | 说明 |
| --- | --- |
| `POST /api/auth/login` | 手机号和密码登录，返回 JWT。 |
| `POST /api/auth/logout` | 登出并拉黑当前 token。 |
| `GET /api/auth/me` | 当前登录用户。 |
| `GET /api/auth/history` | 当前用户历史客服会话列表。 |
| `GET /api/auth/history/{sessionId}` | 指定会话消息详情。 |
| `DELETE /api/auth/history/{sessionId}` | 删除当前用户的历史会话。 |

## 配置

常用环境变量：

| 变量 | 说明 | 建议值 |
| --- | --- | --- |
| `JWT_SECRET` | JWT 签名密钥，至少 32 字节；本地开发未设置时使用默认开发密钥 | 生产必填 |
| `REQUIRE_ENV_JWT_SECRET` | 是否强制要求 `JWT_SECRET` 来自环境变量 | 生产建议 `true` |
| `MYSQL_USERNAME` | MySQL 用户名 | `root` |
| `MYSQL_PASSWORD` | MySQL 密码 | `root` |
| `AGENT_SERVICE_URI` | Python Agent 地址 | `http://127.0.0.1:8001` |
| `MCP_SERVICE_URI` | MCP REST 地址 | `http://127.0.0.1:8080` |
| `REDIS_HOST` | Redis 地址 | `localhost` |
| `REDIS_PORT` | Redis 端口 | `6379` |
| `FRONTEND_ORIGIN` | 前端跨域来源 | `http://localhost:5173` |

> 注意：`application.yml` 中 `MCP_SERVICE_URI` 的默认值可能是本地开发端口。联调根目录 compose 启动的 MCP 时，请显式设置为 `http://127.0.0.1:8080`。

## 运行

先确保 MCP 和 Python Agent 已启动，然后运行 Gateway。本地开发可直接启动；生产或共享环境请显式配置：

```powershell
$env:JWT_SECRET = "replace-with-at-least-32-bytes-secret"
$env:REQUIRE_ENV_JWT_SECRET = "true"
$env:MYSQL_USERNAME = "root"
$env:MYSQL_PASSWORD = "root"
$env:AGENT_SERVICE_URI = "http://127.0.0.1:8001"
$env:MCP_SERVICE_URI = "http://127.0.0.1:8080"
```

```bash
mvn spring-boot:run
```

验证：

```bash
curl http://localhost:8002/actuator/health
curl http://localhost:8002/api/agent/health
```

## 目录结构

```text
src/main/java/com/digitalmall/gateway/
├── config/       # 安全、JWT、限流、启动校验
├── controller/   # 登录、登出、当前用户、历史会话
├── domain/       # 数据库实体
├── filter/       # 身份透传、访问日志
├── repository/   # 数据访问
├── security/     # Bearer token 解析与认证
├── service/      # 登录、JWT、历史会话服务
└── support/      # 通用支持类
```

## 测试

```bash
mvn test
```
