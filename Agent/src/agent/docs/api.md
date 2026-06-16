# Agent API 接口

Base URL：`http://127.0.0.1:8001`

除 `/health` 外，接口默认返回：

```json
{
  "thread_id": "会话线程 id",
  "session_id": "记忆会话 id",
  "status": "running | paused | awaiting_review | completed | error",
  "final_answer": "最终回答",
  "error": "错误信息",
  "pending_action": null
}
```

`/run`、`/resume` 与 `/confirm` 是异步接口，返回 `running` 后需查询 `/sessions/{thread_id}` 获取最终结果。需要实时进度时使用 `/stream`。

## 接口列表

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/health` | `GET` | 健康检查 |
| `/run` | `POST` | 创建新会话并开始生成 |
| `/stream` | `POST` | 创建新会话，以 SSE 推送阶段事件和最终回答 |
| `/pause` | `POST` | 暂停指定会话，在阶段边界生效 |
| `/resume` | `POST` | 恢复已暂停会话 |
| `/confirm` | `POST` | 用户确认、修改或取消待审核写操作 |
| `/sessions/{thread_id}` | `GET` | 查询会话状态与结果 |

## 请求体

`POST /run` 与 `POST /stream`：

```json
{
  "message": "推荐一款 5000 元左右的轻薄笔记本",
  "session_id": "可选，用于延续同一记忆会话",
  "new_session": false
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `message` | string | 是 | 用户输入，不能为空 |
| `session_id` | string | 否 | 记忆会话 id；传入后本轮会沿用同一会话记忆 |
| `new_session` | boolean | 否 | 为 `true` 时忽略传入的 `session_id`，强制开启全新记忆会话；默认 `false` |

身份来源：

- 前端统一通过 Java API 网关访问，并携带 `Authorization: Bearer <token>`。
- 网关认证后会向 Python Agent 透传 `X-Customer-Id`、`X-Customer-No`；订单/售后链路使用该认证身份查询“我的订单”。
- `session_id` 只表示会话线程/记忆标识，不再作为客户 ID 使用。

`POST /pause` 与 `POST /resume`：

```json
{
  "thread_id": "会话线程 id"
}
```

`POST /confirm`：

```json
{
  "thread_id": "会话线程 id",
  "approved": true,
  "regenerate": false,
  "args": {
    "type": "RETURN_REFUND",
    "reason": "商品不符合预期"
  },
  "message": "可选，取消说明或重新生成意见"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `thread_id` | string | 是 | 待确认会话线程 id |
| `approved` | boolean | 是 | `true` 表示确认执行，`false` 表示取消或要求重新生成 |
| `regenerate` | boolean | 否 | 仅 `approved=false` 时有意义；`true` 表示按 `message`/`args` 重新生成待确认方案，`false` 表示取消 |
| `args` | object | 否 | 用户修改后的工具参数；为空则沿用待确认操作中的原参数 |
| `message` | string | 否 | 取消说明或重新生成意见 |

`/confirm` 仅允许处理 `status=awaiting_review` 的会话。确认售后申请时，后端会校验 `orderNo`、`type`、`reason` 等待确认操作声明的必填字段；缺失时返回 `409`。

## 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `thread_id` | string | 本轮执行线程 id，用于暂停、恢复、确认与查询 |
| `session_id` | string | 记忆会话 id，可在下一轮作为请求体 `session_id` 传入以延续记忆 |
| `status` | string | `running`、`paused`、`awaiting_review`、`completed`、`error` |
| `final_answer` | string | 最终回答；仅完成后通常有值 |
| `error` | string | 异常信息；仅错误时通常有值 |
| `pending_action` | object/null | 待用户审核确认的高风险写操作；仅 `awaiting_review` 时通常有值 |

状态说明：

| status | 说明 | 前端建议 |
| --- | --- | --- |
| `running` | 会话正在执行 | 轮询 `/sessions/{thread_id}` 或使用 `/stream` |
| `paused` | 会话已在阶段边界暂停 | 可调用 `/resume` |
| `awaiting_review` | 会话等待用户审核确认高风险写操作 | 展示 `pending_action`，用户确认/修改/取消后调用 `/confirm` |
| `completed` | 会话完成 | 展示 `final_answer` |
| `error` | 会话执行失败 | 展示 `error`，必要时允许用户重试 |

## SSE 事件

`POST /stream` 返回 `text/event-stream`，每条事件格式为：

```text
data: {"type":"stage","stage":"decide","label":"任务编排","update":{"intent":"order","tasks":[{"agent":"order","priority":10,"depends_on":[],"query":"查询用户最近订单。","reason":"用户需要订单状态。","confidence":0.9}]}}
```

事件类型：

| type | 说明 |
| --- | --- |
| `start` | 流开始，返回 `thread_id`、`session_id` |
| `stage` | 一个阶段或一个专家任务完成 |
| `done` | 全部完成，返回 `thread_id`、`session_id`、`status`、`final_answer` |
| `error` | 执行出错 |

常见阶段标签：记忆提取、任务编排、产品咨询、技术支持、订单售后、待用户确认、生成回答、安全审核、记忆保存。其中 `decide` 的 `update.tasks` 给出本轮带优先级/依赖的任务计划，专家任务按依赖分波、波内并发产出。

当流式执行进入高风险写操作审核时，会发送 `stage=awaiting_review` 事件并结束本次 SSE 响应。前端应展示 `update.pending_action`，调用 `/confirm` 后再通过 `/sessions/{thread_id}` 轮询后续结果。

示例：

```text
data: {"type":"stage","stage":"awaiting_review","label":"待用户确认","update":{"pending_action":{"agent":"order","tool":"createAfterSale","call_id":"call_xxx","args":{"orderNo":"SO202606150001","type":"RETURN_REFUND","reason":""},"required_fields":["orderNo","type","reason"]}}}
```

## 调用流程

```text
POST /run -> 获取 thread_id
GET /sessions/{thread_id} -> 轮询至 status=completed
```

需要用户确认的流程：

```text
POST /run -> GET /sessions/{thread_id} 返回 status=awaiting_review
展示 pending_action -> POST /confirm -> GET /sessions/{thread_id} 轮询至 status=completed
```

流式流程：

```text
POST /stream -> 接收 start/stage/done
如收到 stage=awaiting_review -> 展示 pending_action -> POST /confirm -> 轮询 /sessions/{thread_id}
```

常见状态码：`200` 成功，`404` 会话不存在，`409` 状态冲突，`422` 请求体校验失败。

## 网关路径

生产或前端集成建议经 Java API 网关访问。网关默认监听 `http://127.0.0.1:8002`，并将 `/api/agent/**` 转发到 Python Agent：

| 网关路径 | Python Agent |
| --- | --- |
| `/api/agent/run` | `POST /run` |
| `/api/agent/stream` | `POST /stream` |
| `/api/agent/pause` | `POST /pause` |
| `/api/agent/resume` | `POST /resume` |
| `/api/agent/confirm` | `POST /confirm` |
| `/api/agent/sessions/{thread_id}` | `GET /sessions/{thread_id}` |
| `/api/agent/health` | `GET /health` |

