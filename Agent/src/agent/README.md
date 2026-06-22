# Python Agent 服务

这是智能客服系统的智能层，基于 PydanticAI 和 FastAPI 构建。它不直接保存商品、订单、售后等业务权威数据，而是通过 MCP 工具服务访问这些能力。

## 核心能力

- 接收前端或 Gateway 转发的客服请求。
- 从历史会话和长期记忆中提取上下文。
- 使用编排 Agent 生成专家任务计划。
- 并发调用产品、技术、订单售后等专家 Agent。
- 通过 MCP SSE 调用业务工具。
- 对写操作返回待确认动作，等待用户确认后执行。
- 将最终回答、会话状态和消息流水保存到记忆存储。

## Agent 内部架构

```mermaid
graph TB
    API[FastAPI<br/>/run /stream /pause /resume /confirm] --> CA[CustomerAgent]
    CA --> MEM[Memory Extract Agent]
    MEM --> ORCH[Orchestrator Agent]
    ORCH --> TASKS[专家任务计划]

    TASKS --> PROD[Product Agent]
    TASKS --> TECH[Tech Agent]
    TASKS --> ORDER[Order Agent]

    PROD --> TOOLS[MCP Client]
    TECH --> TOOLS
    ORDER --> TOOLS

    TOOLS --> MCP[MCP SSE Server]

    PROD --> SUM[Summarize Agent]
    TECH --> SUM
    ORDER --> SUM

    SUM --> REVIEW{待确认操作}
    REVIEW -->|无| FINAL[最终回答]
    REVIEW -->|有| PENDING[awaiting_review]

    FINAL --> STORE[Memory Store]
    PENDING --> API
```

## 运行链路

```text
1. 接收用户消息
2. 读取近期上下文与长期记忆
3. 编排 Agent 生成任务计划
4. 按 priority 和 depends_on 分波执行专家 Agent
5. 每个专家 Agent 只能访问自己领域的 MCP 工具
6. 汇总专家结果并生成最终回复
7. 如需执行写操作，先返回 pending_action 等待用户确认
8. 保存会话状态、消息流水和长期记忆
```

## 主要模块

| 路径 | 说明 |
| --- | --- |
| `main.py` | CLI 和 API 服务入口。 |
| `agent/customer_agent.py` | 主客服 Agent，负责初始化子 Agent、任务分波、并发执行和汇总。 |
| `agent/agents/orchestrator.py` | 编排 Agent，将用户诉求拆成专家任务。 |
| `agent/agents/product.py` | 产品咨询和商品推荐 Agent。 |
| `agent/agents/order.py` | 订单、物流、售后相关 Agent。 |
| `agent/agents/tech.py` | 技术支持和知识库问答 Agent。 |
| `agent/agents/memory_extract.py` | 会话记忆提取。 |
| `agent/agents/summarize.py` | 多专家结果汇总。 |
| `agent/tools/mcp_client.py` | MCP SSE 客户端和工具过滤。 |
| `agent/api/` | FastAPI 路由、请求响应模型和后台运行器。 |
| `agent/memory/` | 本地缓存、Redis、Qdrant、MySQL 记忆存储。 |
| `agent/prompts/` | 各 Agent 的提示词和技能说明。 |
| `tests/` | Agent 单元测试和运行时测试。 |

## 配置

在本目录创建 `.env`：

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

AGENT_MAX_WORKERS=8
AGENT_QUEUE_SIZE=32
RUN_SESSION_TTL_SECONDS=1800
RUN_REVIEW_TTL_SECONDS=900
RUN_CLEANUP_INTERVAL_SECONDS=60
```

说明：

- `OPENAI_MODEL` 用于主要回答。
- `OPENAI_ORCHESTRATOR_MODEL` 用于任务编排，默认 `qwen3.5-plus`。
- `OPENAI_EXPERT_MODEL` 可用于专家 Agent，适合配置更快的模型。
- `OPENAI_MEMORY_MODEL` 可用于记忆提取和摘要。
- `MCP_SERVER_URL` 必须指向 MCP 服务的 SSE 地址。
- `MYSQL_DSN` 如果使用 MCP 的 compose，宿主机端口通常是 `3307`。

## 运行

安装依赖：

```bash
conda activate ai
pip install -r requirements.txt
```

启动 API 服务：

```bash
python main.py --serve
```

CLI 调试：

```bash
python main.py --once "推荐一款拍照好的手机"
python main.py --stream "查一下我的订单物流"
python main.py --chat
```

## API

| 接口 | 说明 |
| --- | --- |
| `POST /run` | 单次非流式问答。 |
| `POST /stream` | SSE 流式问答。 |
| `POST /pause` | 暂停会话。 |
| `POST /resume` | 恢复会话。 |
| `POST /confirm` | 确认或拒绝待执行动作。 |
| `GET /sessions/{thread_id}` | 查询运行状态。 |
| `GET /health` | 健康检查。 |

更详细的接口字段见 [`docs/api.md`](docs/api.md)。

## 测试

```bash
pytest
```
