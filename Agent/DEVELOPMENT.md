# 智能数码商城客服 Agent 系统

## 项目定位

本仓库包含面向智能数码商城的客服 Agent，核心 Python 工程位于 `src/agent/`，用于处理产品推荐、技术/FAQ 咨询、订单物流、售后查询与售后创建等场景。

当前 `src/agent` 是一个自包含的 PydanticAI 多 Agent 工程：包代码在 `src/agent/agent/`，入口在 `src/agent/main.py`，配置文件、测试、文档分别位于 `src/agent/.env`、`src/agent/tests/`、`src/agent/docs/`。

## 核心技术栈

- 语言/环境：Python 3.x；默认使用 Conda 环境 `ai`。
- Agent 框架：PydanticAI，使用 OpenAI 兼容模型接口与原生 MCP SSE 工具集。
- Web 服务：FastAPI + Uvicorn，服务入口为 `agent.api.app:app`，默认端口 `127.0.0.1:8001`。
- 配置管理：`pydantic-settings`，从 `src/agent/.env` 读取。
- 记忆存储：L1 本地缓存、L2 Redis、L3 MySQL、L4 Qdrant 语义记忆。
- 工具接入：MCP SSE，默认地址由 `MCP_SERVER_URL` 指定。
- 测试：pytest / pytest-asyncio。

依赖安装统一在 `src/agent/` 下执行：

```bash
conda activate ai
pip install -r requirements.txt
```

## 当前运行链路

`src/agent/agent/customer_agent.py` 中的 `CustomerAgent` 是客服主 Agent，负责初始化子 Agent、编排任务、分波执行和汇总结果，使用同步生成器逐阶段推进：

```text
记忆提取
→ LLM 任务编排
→ 按依赖/优先级分波执行专家 Agent（同波并发）
→ 总结生成最终回答
→ 记忆保存
```

重要约定：

- 编排能力位于 `agent/agents/orchestrator.py`，由 LLM 输出带 `priority` 与 `depends_on` 的任务计划。
- 执行上下文为 `AgentContext`，任务类型为 `Task`，均定义在 `agent/customer_agent.py`。
- 专家 Agent 位于 `agent/agents/`，目前包括 `ProductAgent`、`TechAgent`、`OrderAgent`，分别只提供商品推荐、技术/知识库、订单/售后能力。
- 专家任务按 `depends_on` 和 `priority` 分波；同一波用 `asyncio.gather` 并发执行。
- 安全审核位于 `agent/agents/safety.py`，当前不接入主 Agent 流程；如需恢复，优先继续使用本地规则审核。
- 不再保留 `agent/agents/executor.py` 主流程入口；不要在 `agents/` 下新增执行器或调度器。
- 不再使用旧的 `agent/workflow/` 模块；不要新增或引用 `WorkflowContext`。

## 目录结构重点

- `src/agent/main.py`：CLI、流式调试、聊天窗口、API 服务启动入口。
- `src/agent/agent/config.py`：集中配置，包含模型、MCP、Redis、MySQL、Qdrant、Embedding、记忆参数。
- `src/agent/agent/llm/model.py`：PydanticAI 模型初始化与获取。
- `src/agent/agent/customer_agent.py`：客服主 Agent，负责完整流程编排与执行。
- `src/agent/agent/agents/`：子 Agent 能力模块，包括编排、产品、技术、订单、总结、记忆提取等；安全审核模块保留但当前不接入主流程。
- `src/agent/agent/api/`：FastAPI 应用、路由、请求/响应模型、运行管理器。
- `src/agent/agent/memory/`：多层记忆后端与运行时。
- `src/agent/agent/tools/mcp_client.py`：MCP 工具集、专家工具隔离、认证客户 ID 注入。
- `src/agent/agent/prompts/skills/`：提示词 Skill，每个目录使用 `SKILL.md`。
- `src/agent/docs/api.md`：API 文档。
- `src/agent/docs/tool.md`：MCP 工具清单与工具规范。
- `src/agent/logs/`：Agent 调用和 Tool 调用的 JSONL 日志。

## 常用命令

以下命令默认在 `src/agent/` 下执行：

```bash
python main.py --once "推荐一款拍照好的手机"
python main.py --stream "查一下我的订单"
python main.py --chat
python main.py --serve
pytest
```

调试参数：

- `--raw`：配合 `--stream` 或 `--chat`，原样打印 SSE 事件 JSON。
- `--verbose`：开启 DEBUG 日志和 OpenAI/httpx 请求级日志。
- `--customer-id` / `--customer-no`：CLI 中模拟登录用户身份，订单/售后专家会使用该身份。

## API 约定

FastAPI 路由位于 `agent/api/routes.py`：

- `GET /health`：健康检查。
- `POST /run`：后台启动一次 Agent 运行，立即返回 `thread_id`。
- `POST /stream`：SSE 流式返回 `start`、`stage`、`done`、`error` 事件。
- `POST /pause`：请求暂停，暂停只在阶段边界生效。
- `POST /resume`：从阶段边界恢复，继续消费同一个生成器。
- `POST /confirm`：高风险写操作的人工审核确认（HITL）。仅 `awaiting_review` 状态可确认，`approved=true` 时可在 `args` 传入修改后的参数后落库并继续。
- `GET /sessions/{thread_id}`：查询后台会话状态和最终回答。

身份透传：

- 前端/网关应通过请求头向 Python Agent 透传 `X-Customer-Id`、`X-Customer-No`。
- `session_id` 只表示记忆会话标识，不可当作客户 ID 使用。
- 当前用户类工具的 `customerId` 由运行上下文注入，不能让模型填写或猜测。

## 记忆系统规范

多层记忆由 `agent/memory/store.py` 编排：

- 读取：L1 本地缓存 → L2 Redis → Qdrant 记忆快照 → L3 MySQL 最终记录逐层降级回源，并通过 Qdrant 做长期语义召回。
- 写入：历史写穿 L1/L2，消息流水和会话状态落 L3 MySQL，长期语义记忆写入 L4 Qdrant。
- 用户画像按 `MEMORY_PROFILE_UPDATE_INTERVAL` 降频异步更新。
- `agent/memory/runtime.py` 持有单独的后台事件循环，数据库、Redis、Qdrant、Embedding 等异步 I/O 必须走该运行时。
- LLM 对话模型调用不走 memory runtime，避免事件循环绑定冲突。

修改记忆相关逻辑时，要特别注意事件循环归属，不要在多个 `asyncio.run` 临时 loop 中复用异步连接池。

## MCP 工具规范

- 工具清单和说明统一维护在 `src/agent/docs/tool.md`。
- Agent 侧只在 `agent/tools/mcp_client.py` 做专家工具白名单、当前用户身份注入和调用日志，不重写 MCP 服务端工具本体。
- 新增、删除或改名 MCP 工具时，必须同步更新：
  - MCP 服务端工具定义；
  - `agent/tools/mcp_client.py` 的专家工具白名单；
  - `src/agent/docs/tool.md`。
- 订单/售后类“当前用户”工具必须隐藏 `customerId` 参数，由 `RunContext.deps.customer_id` 自动注入。
- 写操作工具（如 `createAfterSale`）必须在提示词和代码约束中要求用户明确确认关键参数。

## 提示词规范

- 提示词位于 `src/agent/agent/prompts/skills/<name>/SKILL.md`。
- 通过 `agent/prompts/loader.py` 的 `render_skill()` 加载，不要在 Agent 文件里硬编码长提示词。
- 新增提示词 Skill 时必须包含 frontmatter，并明确是否 `prepend_base`。
- 修改专家职责、工具使用边界或回答风格时，优先更新对应 Skill，而不是把规则散落到执行器里。

## 代码风格与工程规范

- 保持代码简洁，避免过度封装。
- 遵循 PEP8，新增 Python 代码应带清晰类型标注。
- 不要堆叠过多兜底和宽泛 `try/except`；确有必要时说明原因，并确保异常不会掩盖关键错误。
- 优先复用现有模块边界：客服主流程放 CustomerAgent，子能力放 agents，API 会话控制放 runner，工具隔离放 mcp_client，记忆 I/O 放 memory。
- 修改对外接口时同步更新 `src/agent/docs/api.md`。
- 尽量充分使用pydantic ai框架

## 网关说明

仓库中仍包含 `src/api-gateway/` Java API 网关工程，用于统一入口、认证和身份透传。Agent 侧开发时只需遵守其透传契约：订单/售后相关能力依赖 `X-Customer-Id` 或可解析出的认证客户身份。
