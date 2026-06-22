# API Gateway

智能数码商城客服系统的统一入口。网关基于 **Spring Boot 3 + Spring Cloud Gateway**，负责鉴权、路由转发、跨域、限流和访问日志。

## 技术栈

- Java 17
- Spring Boot 3.3.4
- Spring Cloud Gateway 2023.0.3
- Maven

## 主要模块

| 模块 | 说明 |
| --- | --- |
| `config/` | 安全、JWT、限流配置 |
| `controller/AuthController.java` | 登录、登出、当前用户接口 |
| `controller/HistoryController.java` | 当前用户历史客服会话列表与详情 |
| `service/` | 账号校验、JWT 签发/解析、登出黑名单、登录日志 |
| `security/` | Bearer token 认证与黑名单校验 |
| `filter/` | 身份透传、访问日志 |
| `repository/`、`domain/` | `customer` 表访问、登录日志（`login_log`）、Agent 记忆会话查询（`agent_memory_sessions` / `agent_memory_messages`） |
| `resources/application.yml` | 端口、路由、CORS、数据源、JWT 配置 |

## 路由

`/api/agent/**` 会经 `StripPrefix=2` 转发到 Python Agent 服务，后端地址由 `AGENT_SERVICE_URI` 配置，默认 `http://127.0.0.1:8001`。

| 网关路径 | 后端接口 | 说明 |
| --- | --- | --- |
| `/api/agent/run` | `POST /run` | 单次问答 |
| `/api/agent/stream` | `POST /stream` | SSE 流式生成 |
| `/api/agent/pause` | `POST /pause` | 暂停会话 |
| `/api/agent/resume` | `POST /resume` | 恢复会话 |
| `/api/agent/confirm` | `POST /confirm` | 高风险写操作人工审核确认（HITL） |
| `/api/agent/sessions/{id}` | `GET /sessions/{id}` | 查询会话状态 |
| `/api/agent/memory/{customerId}` | `DELETE /memory/{customerId}` | 按用户 id 清理长期记忆 |
| `/api/agent/health` | `GET /health` | 后端健康检查 |

`/api/customer/**` 直连 MCP 服务端 REST（路径保持不剥离前缀），后端地址由 `MCP_SERVICE_URI` 配置，默认 `http://127.0.0.1:8081`。供前端「我的订单 / 我的售后」页面拉取结构化数据，身份只信任网关注入的 `X-Customer-Id`（自助模式：只能查本人）。

| 网关路径 | 后端接口 | 说明 |
| --- | --- | --- |
| `/api/customer/orders` | `GET /api/customer/orders` | 当前用户订单列表（按创建时间倒序） |
| `/api/customer/orders/{orderNo}` | `GET /api/customer/orders/{orderNo}` | 订单详情（明细、物流、收货信息） |
| `/api/customer/aftersales` | `GET /api/customer/aftersales` | 当前用户售后列表（按创建时间倒序） |
| `/api/customer/aftersales/{afterSaleNo}` | `GET /api/customer/aftersales/{afterSaleNo}` | 售后单详情 |

## 鉴权

- `/api/auth/login` 与 `/actuator/health` 放行，其余接口默认需要登录。
- 登录校验 MySQL `customer` 表，成功后签发 HS256 JWT。
- 受保护接口需携带 `Authorization: Bearer <token>`。
- 登出会把 JWT 的 `jti` 写入 Redis 黑名单，直到 token 过期。
- 通过认证后，网关向下游透传 `X-Customer-Id`、`X-Customer-No`、`X-Member-Level`。
- 每次登录（成功/失败）均落 MySQL `login_log` 表，记录账号、客户、IP、User-Agent、结果与 token `jti`；落库失败不影响登录主流程。

鉴权接口：

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/auth/login` | `POST` | 手机号 + 密码登录 |
| `/api/auth/logout` | `POST` | 登出并拉黑当前 token |
| `/api/auth/me` | `GET` | 返回当前登录用户 |

历史会话接口（需登录，只能查本人）：

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/auth/history` | `GET` | 当前用户的历史客服会话列表（按更新时间倒序，最多 100 条） |
| `/api/auth/history/{sessionId}` | `GET` | 指定会话的完整对话消息（按轮次/序号排序） |
| `/api/auth/history/{sessionId}` | `DELETE` | 删除当前用户的指定历史会话（会话状态 + 消息流水），先校验归属，越权或不存在返回 404 |

> 历史会话数据来自 Python Agent 落库的记忆表 `agent_memory_sessions` / `agent_memory_messages`，列表/详情网关只读，删除会清理这两张表。

## 配置

常用环境变量：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `AGENT_SERVICE_URI` | Python Agent 地址 | `http://127.0.0.1:8001` |
| `MCP_SERVICE_URI` | MCP 服务端地址（订单/售后 REST） | `http://127.0.0.1:8081` |
| `MYSQL_R2DBC_URL` | MySQL R2DBC 地址 | 见 `application.yml` |
| `MYSQL_USERNAME` / `MYSQL_PASSWORD` | MySQL 账号密码 | 无默认值，需显式提供 |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | Redis 连接信息 | `localhost` / `6379` / 空 |
| `JWT_SECRET` | JWT 签名密钥，至少 32 字节，启动时强校验来自环境变量 | 无默认值，必须提供 |
| `FRONTEND_ORIGIN` / `FRONTEND_ORIGIN_ALT` | 允许跨域访问的前端来源 | `http://localhost:5173` / `http://127.0.0.1:5173` |
| `REQUIRE_ENV_JWT_SECRET` | 是否强制校验 JWT_SECRET 来自环境变量 | `true` |

服务器连接信息见 [`../../docs/server.md`](../../docs/server.md)。

## 运行

先启动 Python Agent：

```bash
cd ../agent
conda activate ai
python main.py --serve
```

再启动网关：

```bash
$env:JWT_SECRET = "replace-with-at-least-32-bytes-secret"
$env:MYSQL_USERNAME = "你的数据库用户"
$env:MYSQL_PASSWORD = "你的数据库密码"
mvn spring-boot:run
```

验证：

```bash
curl http://localhost:8002/actuator/health
curl http://localhost:8002/api/agent/health
```

## 测试

```bash
mvn test
```
