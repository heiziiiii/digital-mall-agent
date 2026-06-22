# 前端应用

智能客服系统的用户界面，基于 React、TypeScript 和 Vite 构建。前端只访问 API Gateway，不直接调用 Python Agent 或 MCP 服务。

## 功能

- 登录和退出登录。
- 多轮客服聊天。
- SSE 流式展示 Agent 回复过程。
- 商品推荐卡片展示。
- 待确认操作卡片，例如售后申请、人工服务单。
- 我的订单、订单详情和撤销订单。
- 我的售后、售后详情和撤销售后申请。
- 历史会话列表和历史消息查看。

## 请求链路

```text
React 前端
  -> /api/auth/**      登录、当前用户、历史会话
  -> /api/agent/**     聊天、流式回复、暂停恢复、确认动作
  -> /api/customer/**  订单和售后自助页面
  -> API Gateway :8002
```

开发环境中，Vite 会将 `/api/*` 代理到 `http://127.0.0.1:8002`。

## 快速开始

```bash
cd 前端
npm install
npm run dev
```

访问：`http://localhost:5173`

如果需要指定后端地址：

```powershell
$env:VITE_API_BASE = "http://localhost:8002"
```

## 主要文件

| 路径 | 说明 |
| --- | --- |
| `src/App.tsx` | 主应用，组织聊天、登录、历史会话、订单售后视图。 |
| `src/api.ts` | API Gateway 客户端，封装登录、聊天、订单、售后接口。 |
| `src/components/Composer.tsx` | 输入框组件。 |
| `src/components/MessageBubble.tsx` | 消息气泡。 |
| `src/components/ReviewCard.tsx` | 待确认动作卡片。 |
| `src/components/ProductCard.tsx` | 商品推荐卡片。 |
| `src/components/OrdersView.tsx` | 我的订单视图。 |
| `src/components/AfterSalesView.tsx` | 我的售后视图。 |
| `src/components/Sidebar.tsx` | 会话和导航侧边栏。 |
| `vite.config.js` | Vite 配置和 `/api` 代理。 |

## 测试

```bash
npm test
npm run build
```
