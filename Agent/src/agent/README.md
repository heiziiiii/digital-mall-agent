# 智能数码商城客服 Agent（PydanticAI 构建）

一个面向数码商城的多 Agent 客服系统，覆盖**产品推荐 / 订单查询 / 售后服务 / 常见问题解答**。
基于 **PydanticAI** 多 Agent 协作，工具能力通过 **MCP（SSE）** 接入。

本目录是一个**自包含的 Python 工程**：包代码在 [`agent/`](agent/)，入口为 [`main.py`](main.py)。

## 多 Agent 运行链路

```
记忆提取 → 任务规划（LLM 产出带优先级/依赖的专家任务）
        →（按依赖分波、波内并发执行专家 Agent：产品 / 技术 / 订单售后）
        → 生成回答 → 记忆保存
```

采用「规划—并行执行」模式：编排 Agent（[`agent/agents/orchestrator.py`](agent/agents/orchestrator.py)）把输入分解为带
`priority`（越小越优先）与 `depends_on` 的任务；客服主 Agent（[`agent/customer_agent.py`](agent/customer_agent.py)）按依赖
分波，波内同优先级且互不依赖的任务用 `asyncio.gather` 并发执行。整体是一个**可流式、可在阶段/波次边界暂停/恢复**
的同步生成器（[`agent/customer_agent.py`](agent/customer_agent.py)）；每完成一个阶段或专家任务即产出一条进度事件。

## 目录说明

```text
agent/
├── config.py            # 配置（pydantic-settings，从 .env 读取）
├── customer_agent.py    # 客服主 Agent：初始化子 Agent、编排、分波执行、汇总
├── llm/model.py         # PydanticAI 模型工厂（OpenAI 兼容接口）
├── tools/mcp_client.py  # MCP 工具集 + 按 Agent 过滤
├── prompts/             # 提示词（SKILL.md）与加载器
├── agents/              # PydanticAI 子 Agent 能力模块
└── api/                 # FastAPI：/run /stream /pause /resume /confirm /sessions
```

## 快速开始

> 以下命令均在本目录（`src/agent/`）下执行；`.env` 也位于本目录。

依赖统一在 conda 环境 `ai` 中安装：

```bash
conda activate ai
pip install -r requirements.txt
```

配置 `.env`（关键项）：

```env
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus
MCP_SERVER_URL=http://localhost:8081/sse
```

运行 CLI：

```bash
python main.py --once "推荐一款拍照好的手机"   # 单次问答
python main.py --chat                          # 多轮对话窗口（记忆跨轮累积）
python main.py --stream "查一下我的订单"        # 单次，逐阶段流式打印
```

启动 API 服务：

```bash
python main.py --serve            # 默认 127.0.0.1:8001
```

接口文档见 [`docs/api.md`](docs/api.md)，工具清单见 [`docs/tool.md`](docs/tool.md)。
生产环境建议通过同级的 [`../api-gateway/`](../api-gateway/) 统一入口对外暴露。

## 设计说明

- **流程精简**：主 Agent 当前不接入安全审核阶段，生成回答后直接进入记忆保存。
- **工具隔离**：每个专家 Agent 仅能看到自己领域的 MCP 工具（定义层面过滤）。
- **防幻觉**：产品推荐会对照工具原始返回做事实校验，剔除无据可依的条目。
- **记忆**：本地缓存保存热数据，Redis 保存温数据（近期历史、滚动摘要、当前任务状态等），Qdrant 保存可回源的会话/消息快照与长期语义记忆，MySQL 保存最终会话状态与消息流水；写入先更新缓存，再异步落 Qdrant/MySQL。

## 测试

```bash
pytest
```
