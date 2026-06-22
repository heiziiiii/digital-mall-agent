# 智能客服后端

本目录包含智能客服后端的两个核心工程：

- [`src/agent/`](src/agent/)：Python 多 Agent 服务，负责理解用户问题、规划专家任务、调用 MCP 工具、生成回复和保存记忆。
- [`src/api-gateway/`](src/api-gateway/)：Java API Gateway，负责登录鉴权、路由转发、身份透传和前端接口入口。

MCP 工具服务位于仓库根目录的 [`../MCP/`](../MCP/)，前端位于 [`../frontend/`](../frontend/)。

## 后端分层

```text
前端请求
  -> API Gateway :8002
       -> /api/auth/**       登录、登出、当前用户、历史会话
       -> /api/agent/**      转发到 Python Agent
       -> /api/customer/**   转发到 MCP REST 接口
  -> Python Agent :8001
       -> MCP SSE :8080/sse
  -> MCP Server :8080
       -> MySQL / Redis / Qdrant
```

## 模块职责

| 模块 | 主要职责 | 文档 |
| --- | --- | --- |
| Python Agent | 多 Agent 编排、流式响应、暂停恢复、人工确认、记忆管理 | [src/agent/README.md](src/agent/README.md) |
| API Gateway | JWT 鉴权、路由转发、身份透传、历史会话接口、订单售后 REST 聚合 | [src/api-gateway/README.md](src/api-gateway/README.md) |

## 启动顺序

先启动根目录的 MCP 服务，再启动 Agent 和 Gateway。

```bash
# 1. MCP 服务
cd ../MCP
docker compose up -d
curl -X POST http://localhost:8080/admin/reindex

# 2. Python Agent
cd ../Agent/src/agent
conda activate ai
pip install -r requirements.txt
python main.py --serve

# 3. API Gateway
cd ../api-gateway
mvn spring-boot:run
```

Gateway 本地开发可直接启动；生产或共享环境启动前请显式配置：

```powershell
$env:JWT_SECRET = "replace-with-at-least-32-bytes-secret"
$env:REQUIRE_ENV_JWT_SECRET = "true"
$env:MYSQL_USERNAME = "root"
$env:MYSQL_PASSWORD = "root"
$env:AGENT_SERVICE_URI = "http://127.0.0.1:8001"
$env:MCP_SERVICE_URI = "http://127.0.0.1:8080"
```

## 验证

```bash
curl http://localhost:8002/actuator/health
curl http://localhost:8002/api/agent/health
```

## 测试

```bash
# Python Agent
cd src/agent
pytest

# API Gateway
cd ../api-gateway
mvn test
```

## 目录结构

```text
Agent/
├── README.md
└── src/
    ├── agent/         # Python Agent 工程
    └── api-gateway/   # Java API Gateway 工程
```
