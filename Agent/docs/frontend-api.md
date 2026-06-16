# 前端联调 API 文档

本文档面向前端联调。前端统一访问 API 网关，不直接访问 Python Agent 服务。

## 基础信息

- 网关地址：`http://localhost:8002`
- 请求格式：`Content-Type: application/json`
- 鉴权方式：登录后在请求头携带 `Authorization: Bearer <token>`
- 放行接口：`POST /api/auth/login`
- 受保护接口：除登录和 `/actuator/**` 外，均需要登录

## 通用响应

网关本地鉴权接口使用统一响应体：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

规则：

- `code = 0` 表示成功。
- `code != 0` 表示失败，错误信息看 `message`。
- Agent 业务接口由网关转发，响应体保持 Agent 原始结构。

## 鉴权接口

### 登录

`POST /api/auth/login`

请求：

```json
{
  "phone": "13800000333",
  "password": "123456"
}
```

成功响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "token": "jwt-token",
    "expiresIn": 7200,
    "customerId": 1,
    "customerNo": "C000001",
    "nickname": "张三",
    "memberLevel": 1,
    "historySessionIds": [
      "3e263ec8cc604e63885b88760b50983e",
      "4a85da0db0314553b4713639e07a3a98"
    ]
  }
}
```

说明：

- `phone` 为手机号。
- `expiresIn` 单位为秒。
- 前端保存 `token`，后续请求放入 `Authorization` 请求头。
- `historySessionIds` 为当前客户历史客服记忆会话 ID 列表，按最近更新时间倒序返回；前端可展示为“历史对话”，用户选择后把对应值作为 Agent 请求体里的 `session_id` 继续对话。
- 如果 `historySessionIds` 为空，表示暂无可恢复的历史会话；新对话时不传 `session_id` 或传 `null` 即可。

### 获取当前用户

`GET /api/auth/me`

请求头：

```http
Authorization: Bearer <token>
```

成功响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "customerId": 1,
    "customerNo": "C000001",
    "nickname": "张三",
    "memberLevel": 1
  }
}
```

### 登出

`POST /api/auth/logout`

请求头：

```http
Authorization: Bearer <token>
```

成功响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": null
}
```

登出后当前 token 会失效。

## Agent 会话接口

Agent 接口统一走 `/api/agent/**`，网关会转发到后端 Python Agent。

订单/售后身份由登录态提供：前端只需携带 `Authorization: Bearer <token>`，网关会向 Python Agent 透传 `X-Customer-Id` 和 `X-Customer-No`。`session_id` 仅用于会话连续性，不要把它当用户 ID。

### `thread_id` 与 `session_id`

| 字段 | 用途 | 生命周期 | 前端怎么用 |
| ---- | ---- | -------- | ---------- |
| `thread_id` | 本轮 Agent 执行 ID | 每次 `/run` 或 `/stream` 都不同 | 查询、暂停、恢复、确认当前这次运行 |
| `session_id` | 记忆会话 ID | 多轮对话复用 | 继续历史对话时放进下一次请求体 |

规则：

- 新对话：不传 `session_id`，或传 `null`，后端会自动生成新的 `session_id`。
- 继续历史对话：传登录响应 `historySessionIds` 中用户选中的那个 `session_id`。
- 轮询状态、暂停、恢复、确认审核时使用 `thread_id`。
- 不要把 `thread_id` 当作下一轮的 `session_id` 保存；后端目前会做兼容纠偏，但前端应以返回的 `session_id` 为准。

### 创建会话并后台执行

`POST /api/agent/run`

请求：

```json
{
  "message": "推荐一款 5000 元左右的轻薄笔记本",
  "session_id": "optional-session-id",
  "new_session": false
}
```

响应：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998",
  "session_id": "3e263ec8cc604e63885b88760b50983e",
  "status": "running",
  "final_answer": "",
  "error": "",
  "pending_action": null
}
```

说明：

- `message` 必填，不能为空。
- `session_id` 可选，不传或传 `null` 则后端自动生成；它不是用户 ID。
- `new_session` 可选，默认 `false`；为 `true` 时会忽略传入的 `session_id`，强制开启全新记忆会话。
- 返回 `running` 后，前端用 `thread_id` 轮询查询结果。
- 前端应保存响应中的 `session_id`，用于当前聊天窗口的后续多轮请求。

### 查询会话状态

`GET /api/agent/sessions/{thread_id}`

响应：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998",
  "session_id": "3e263ec8cc604e63885b88760b50983e",
  "status": "completed",
  "final_answer": "为你推荐以下几款...",
  "error": "",
  "pending_action": null
}
```

`status` 取值：

| 状态               | 含义                                    |
| ------------------ | --------------------------------------- |
| `running`          | 生成中                                  |
| `paused`           | 已暂停                                  |
| `awaiting_review`  | 待用户审核确认（高风险写操作，见下）    |
| `completed`        | 已完成                                  |
| `error`            | 执行失败                                |

当 `status=awaiting_review` 时，响应额外带 `pending_action`，表示模型发起的、需用户检查/修改后
才执行的高风险写操作（当前为创建售后单）：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998",
  "session_id": "3e263ec8cc604e63885b88760b50983e",
  "status": "awaiting_review",
  "final_answer": "",
  "error": "",
  "pending_action": {
    "state": "awaiting_review",
    "kind": "tool_approval",
    "agent": "order",
    "tool": "createAfterSale",
    "call_id": "call_xxx",
    "args": { "orderNo": "O100", "type": 1, "reason": "屏幕碎裂", "refundAmount": 4999 },
    "known_fields": { "orderNo": "O100", "type": 1, "reason": "屏幕碎裂", "refundAmount": 4999 },
    "missing_fields": [],
    "required_fields": ["orderNo", "type", "reason"],
    "editable_fields": ["orderNo", "type", "reason", "refundAmount"],
    "instruction": "请核对售后申请信息；如有缺失请补全，确认后才会真正提交。"
  }
}
```

前端应把 `pending_action.args` 渲染成可编辑表单（订单号 / 类型 / 原因 / 退款金额），由用户检查、
修改或取消，再调用 `POST /api/agent/confirm`（见下）。
若 `missing_fields` 非空，前端必须让用户补齐后才能确认；后端也会在确认执行前再次校验。

### 流式会话

`POST /api/agent/stream`

请求：

```json
{
  "message": "我想买一台适合学生用的平板",
  "session_id": "optional-session-id",
  "new_session": false
}
```

响应类型：`text/event-stream`

事件格式：

```text
data: {"type":"start","thread_id":"d6d6bb5ec75844ddbe9f137697aeb998","session_id":"3e263ec8cc604e63885b88760b50983e"}

data: {"type":"stage","stage":"memory_load","label":"记忆提取","update":{"rolling_summary":"...","current_emotion":"中性"}}

data: {"type":"stage","stage":"decide","label":"任务编排","update":{"intent":"order","tasks":[{"agent":"order","priority":10,"depends_on":[]}]}}

data: {"type":"stage","stage":"order_agent","label":"订单售后","update":{"agent_results":{"order":"..."},"status":"done"}}

data: {"type":"done","thread_id":"d6d6bb5ec75844ddbe9f137697aeb998","session_id":"3e263ec8cc604e63885b88760b50983e","status":"completed","final_answer":"..."}
```

事件类型：

| type      | 含义                            |
| --------- | ------------------------------- |
| `start` | 流开始，返回 `thread_id` 和 `session_id` |
| `stage` | 一个阶段（或一个任务）完成，可展示进度 |
| `done`  | 全部完成，读取 `final_answer` |
| `error` | 执行失败，读取 `message` |

`stage` 取值与节奏：先是 `memory_load`（记忆提取）、`decide`（任务编排，`update.tasks` 给出本轮带优先级/依赖的任务计划），随后**按依赖分波**逐个产出各任务阶段 `order_agent` / `tech_agent` / `product_agent`（同一波内的独立任务并发执行、逐个产出事件），最后 `summarize`（生成回答）、`safety`（安全审核）、`memory_save`（记忆保存）。纯闲聊轮没有任务阶段。

前端建议：

- 该接口是 `POST + SSE`，浏览器原生 `EventSource` 不支持 POST，建议用 `fetch` 读取流。
- 收到 `done` 后关闭读取。
- 收到 `error` 后展示失败提示。

### 暂停会话

`POST /api/agent/pause`

请求：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998"
}
```

响应：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998",
  "session_id": "3e263ec8cc604e63885b88760b50983e",
  "status": "running",
  "final_answer": "",
  "error": "",
  "pending_action": null
}
```

说明：暂停在运行阶段边界生效，因此接口返回后状态可能短时间仍为 `running`。

### 恢复会话

`POST /api/agent/resume`

请求：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998"
}
```

响应：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998",
  "session_id": "3e263ec8cc604e63885b88760b50983e",
  "status": "running",
  "final_answer": "",
  "error": "",
  "pending_action": null
}
```

只有 `paused` 状态的会话可以恢复。

### 确认/修改高风险写操作（用户审核确认）

`POST /api/agent/confirm`

当会话进入 `awaiting_review`（如创建售后单）时，前端展示 `pending_action` 并让用户检查、修改或取消，
然后调用本接口恢复执行。

请求（确认并修改参数）：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998",
  "approved": true,
  "args": { "orderNo": "O100", "type": 1, "reason": "屏幕碎裂", "refundAmount": 4699 }
}
```

请求（取消）：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998",
  "approved": false,
  "message": "用户放弃申请售后"
}
```

请求（否认当前方案并要求后端按意见重新生成）：

```json
{
  "thread_id": "d6d6bb5ec75844ddbe9f137697aeb998",
  "approved": false,
  "regenerate": true,
  "message": "改成仅退款，原因是买错了"
}
```

字段说明：

- `approved` 必填。`true` 确认执行，`false` 取消。
- `regenerate` 可选，默认 `false`；仅在 `approved=false` 时有意义，`true` 表示不执行当前方案，但把 `message` 作为修改意见交回后端继续生成新的待确认方案。
- `args` 可选，仅在 `approved=true` 时生效；传入用户修改后的参数（可只改部分字段，建议回传完整 `pending_action.args`），不传则沿用模型原参数。
- `message` 可选，取消时给用户的说明，或重新生成时的修改意见。

响应：恢复为 `running`，随后继续轮询 `GET /api/agent/sessions/{thread_id}` 直至 `completed`，
`final_answer` 会反映真实落库结果（确认时含售后单号，取消时为已取消说明）。仅 `awaiting_review`
状态可确认，否则返回 `409`。

### 健康检查

`GET /api/agent/health`

响应：

```json
{
  "status": "ok"
}
```

## 推荐调用流程

非流式：

```text
1. POST /api/auth/login 获取 token
2. 如果用户选择历史对话，把对应 historySessionIds[i] 作为 session_id；如果新对话则不传 session_id
3. POST /api/agent/run 创建本轮运行，保存响应里的 thread_id 和 session_id
4. GET /api/agent/sessions/{thread_id} 轮询
5. status=awaiting_review 时：展示 pending_action，让用户检查/修改，
   再 POST /api/agent/confirm（approved + 可选 args）恢复，继续轮询
6. status=completed 时展示 final_answer
```

> 用户审核确认（HITL）只支持非流式轮询路径；`/stream` 不承载确认交互。

流式：

```text
1. POST /api/auth/login 获取 token
2. 如果用户选择历史对话，把对应 historySessionIds[i] 作为 session_id；如果新对话则不传 session_id
3. POST /api/agent/stream，保存 start 事件里的 thread_id 和 session_id
4. 按 SSE data 行解析 JSON
5. 收到 stage 更新进度，收到 done 展示 final_answer
```

## 常见状态码

| HTTP 状态码 | 场景                                   |
| ----------- | -------------------------------------- |
| `200`     | 请求成功                               |
| `401`     | 未登录、token 缺失、token 无效或已登出 |
| `403`     | 无权访问                               |
| `404`     | 会话不存在                             |
| `409`     | 会话状态冲突，例如非暂停状态执行恢复   |
| `422`     | 请求体字段校验失败                     |
| `429`     | 网关限流                               |
| `500`     | 服务端异常                             |
