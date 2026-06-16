# 智能数码商城客服系统

面向数码商城的多 Agent 客服系统，覆盖**产品推荐 / 订单查询 / 售后服务 / 常见问题解答**。
采用 **Python Agent 服务 + Java API 网关** 的分层架构。

## 仓库结构

```text
src/
├── agent/         # Python Agent 工程（PydanticAI 编排，自包含可独立运行）
└── api-gateway/   # Java API 网关工程（Spring Cloud Gateway，统一入口）
```

- [`src/agent/`](src/agent/)：核心客服 Agent，基于 **PydanticAI** 编排、**MCP（SSE）** 接入工具，
  对外提供 FastAPI 接口（`/run` `/stream` `/pause` `/resume` `/confirm` `/sessions`）。详见
  [`src/agent/README.md`](src/agent/README.md)。
- [`src/api-gateway/`](src/api-gateway/)：基于 **Spring Boot 3 + Spring Cloud Gateway** 的统一入口，
  负责路由转发、跨域、限流与访问日志。详见 [`src/api-gateway/README.md`](src/api-gateway/README.md)。

## 整体调用链路

```text
客户端 → API 网关(:8002, /api/agent/**) → Python Agent 服务(:8001) → MCP 工具服务(:8081)
```

## 快速开始

1. 启动后端 Agent 服务：

   ```bash
   cd src/agent
   conda activate ai
   pip install -r requirements.txt
   python main.py --serve            # 默认 127.0.0.1:8001
   ```

2. 启动 API 网关：

   ```bash
   cd src/api-gateway
   mvn spring-boot:run               # 默认 :8002
   ```

3. 验证：

   ```bash
   curl http://localhost:8002/api/agent/health
   ```

各子工程的详细说明、配置与测试方式，请参阅各自目录下的 README。
