import { useEffect, useMemo, useRef, useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatHeader from './components/ChatHeader'
import Welcome from './components/Welcome'
import MessageBubble from './components/MessageBubble'
import Composer from './components/Composer'
import OrdersView from './components/OrdersView'
import AfterSalesView from './components/AfterSalesView'
import { historySubtitle, historyTitle } from './historyDisplay'
import {
  appendAgentMemory,
  clearAuthToken,
  confirmAction,
  createOrder,
  deleteHistoryConversation,
  getCurrentUser,
  getHistoryConversation,
  getHistorySessions,
  getSession,
  hasAuthToken,
  login,
  logout,
  runChat,
  streamChat,
  type CurrentUserResponse,
  type HistoryMessage,
  type HistorySession,
  type LoginResponse,
  type Order,
  type PendingAction,
  type ProductRecommendation,
  type SessionResponse,
} from './api'

/* ----------------------------- 类型定义 ----------------------------- */

type MessageRole = 'user' | 'bot'
type AuthStatus = 'checking' | 'authenticated' | 'anonymous'

// 主内容区当前视图：聊天 / 我的订单 / 我的售后
export type View = 'chat' | 'orders' | 'aftersales'

type TextBlock = { type: 'text'; value: string }
type ProductBlock = { type: 'product'; value: ProductData }
type ReviewBlock = { type: 'review'; value: PendingAction }

export type MessageBlock = TextBlock | ProductBlock | ReviewBlock

export type Message = {
  id: number
  role: MessageRole
  blocks: MessageBlock[]
}

// 商品卡数据直接复用后端产品 Agent 的结构化推荐结果
export type ProductData = ProductRecommendation

export type Conversation = {
  id: number
  title: string
  preview: string
  time: string
  messages: Message[]
  sessionId?: string
  threadId?: string
  historyLoaded?: boolean
  historyLoading?: boolean
}

export type UserInfo = {
  userId: string
  customerNo: string
  name: string
  avatar: string
  vipLevel: string
  vipTag: string
}

/* ----------------------------- 用户信息转换 ----------------------------- */

const getAvatarText = (name: string, customerNo: string) => {
  const source = name.trim() || customerNo.trim() || '用户'
  return Array.from(source)[0] ?? '用'
}

const toUserInfo = (profile: LoginResponse | CurrentUserResponse): UserInfo => {
  const memberLevel = Number(profile.memberLevel) || 0
  const name = profile.nickname?.trim() || profile.customerNo || '用户'
  const userId = String(profile.userId ?? profile.user_id ?? profile.id ?? profile.customerId ?? profile.customerNo).trim()

  return {
    userId,
    customerNo: profile.customerNo,
    name,
    avatar: getAvatarText(name, profile.customerNo),
    vipLevel: memberLevel > 0 ? `会员 V${memberLevel}` : '普通用户',
    vipTag: memberLevel > 0 ? `V${memberLevel}` : '普通',
  }
}

const GREETING_TEXT =
  '你好呀，我是 **阿数** ✨ 你的 AI 智能客服。推荐产品、查看订单、售后服务、解决技术问题，都可以直接跟我说。先说说你的需求吧～'

const REVIEW_FLOW_RE = /售后|退款|退货|换货|维修|退换|取消订单|申请|下单|购买|买这|就要|帮我买/
const SESSION_ID_KEY = 'agent_session_id'
const HISTORY_CACHE_PREFIX = 'agent_history_sessions'

// 计数器挂在 globalThis 上，避免热更新（HMR）时模块重载导致 id 从 0 重置，
// 与仍被 React 保留的旧 state 中的 id 冲突（出现重复 key 警告）。
const idStore = globalThis as unknown as { __nextId?: number }
const newId = () => (idStore.__nextId = (idStore.__nextId ?? 0) + 1)

const greetingMessage = (): Message => ({
  id: newId(),
  role: 'bot',
  blocks: [{ type: 'text', value: GREETING_TEXT }],
})

const saveSessionId = (sessionId: string) => {
  try {
    localStorage.setItem(SESSION_ID_KEY, sessionId)
  } catch {
    /* 忽略本地存储不可用的情况 */
  }
}

const clearSessionId = () => {
  try {
    localStorage.removeItem(SESSION_ID_KEY)
  } catch {
    /* 忽略本地存储不可用的情况 */
  }
}

const historyCacheKey = (customerNo?: string) => `${HISTORY_CACHE_PREFIX}:${customerNo || 'default'}`

const loadHistoryCache = (customerNo?: string): HistorySession[] => {
  try {
    const raw = localStorage.getItem(historyCacheKey(customerNo))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is HistorySession => item && typeof item.sessionId === 'string')
      .map((item) => ({
        sessionId: item.sessionId,
        rollingSummary: typeof item.rollingSummary === 'string' ? item.rollingSummary : undefined,
        lastUserMessage: typeof item.lastUserMessage === 'string' ? item.lastUserMessage : undefined,
        lastAssistantMessage: typeof item.lastAssistantMessage === 'string' ? item.lastAssistantMessage : undefined,
        updatedAt: typeof item.updatedAt === 'string' ? item.updatedAt : undefined,
      }))
  } catch {
    return []
  }
}

const saveHistoryCache = (customerNo: string | undefined, sessions: HistorySession[]) => {
  try {
    localStorage.setItem(historyCacheKey(customerNo), JSON.stringify(sessions))
  } catch {
    /* 忽略本地存储不可用的情况 */
  }
}

const clearHistoryCache = (customerNo?: string) => {
  try {
    localStorage.removeItem(historyCacheKey(customerNo))
  } catch {
    /* 忽略本地存储不可用的情况 */
  }
}

const restoredHistoryMessage = (session: HistorySession): Message => ({
  id: newId(),
  role: 'bot',
  blocks: [{
    type: 'text',
    value: session.rollingSummary
      ? `已恢复历史上下文：${historySubtitle(session)}`
      : '正在加载完整历史对话...',
  }],
})

const loadingHistoryMessage = (): Message => ({
  id: newId(),
  role: 'bot',
  blocks: [{ type: 'text', value: '正在加载完整历史对话...' }],
})

const historyLoadFailedMessage = (session: HistorySession): Message => ({
  id: newId(),
  role: 'bot',
  blocks: [{
    type: 'text',
    value: session.rollingSummary
      ? `完整历史对话暂时加载失败，先为你保留摘要：${historySubtitle(session)}`
      : '完整历史对话暂时加载失败，请稍后再试。',
  }],
})

const emptyHistoryMessage = (): Message => ({
  id: newId(),
  role: 'bot',
  blocks: [{ type: 'text', value: '这段历史暂无可展示的消息。' }],
})

const errorMessage = (error: unknown, fallback: string) => {
  if (!(error instanceof Error) || !error.message) return fallback
  try {
    const parsed = JSON.parse(error.message)
    if (typeof parsed?.detail === 'string' && parsed.detail.trim()) return parsed.detail
    if (typeof parsed?.message === 'string' && parsed.message.trim()) return parsed.message
  } catch {
    /* 忽略非 JSON 错误消息 */
  }
  return error.message || fallback
}

const firstTextBlock = (message: Message) => {
  const text = message.blocks.find((block): block is TextBlock => block.type === 'text')
  return text?.value.trim() || ''
}

const recentDialogueLabels = (messages: Message[], fallbackTitle = '新的咨询', fallbackPreview = '开始一段新对话') => {
  const lastUser = [...messages].reverse().find((message) => message.role === 'user')
  const lastBot = [...messages].reverse().find((message) => message.role === 'bot' && firstTextBlock(message))
  return {
    title: firstTextBlock(lastUser ?? messages[0]) || fallbackTitle,
    preview: firstTextBlock(lastBot ?? messages[0]) || fallbackPreview,
  }
}

const historyListLabels = (session: HistorySession, fallbackIndex: number) => ({
  title: session.lastUserMessage?.trim() || historyTitle(session, fallbackIndex),
  preview: session.lastAssistantMessage?.trim() || historySubtitle(session),
})

const toChatMessage = (message: HistoryMessage): Message => ({
  id: newId(),
  role: message.role === 'user' ? 'user' : 'bot',
  blocks: [{ type: 'text', value: message.content || '（空消息）' }],
})

/* ----------------------------- 初始会话 ----------------------------- */

// 一条全新的空白会话：仅有欢迎语、没有 sessionId，
// 在用户发送第一条消息前不会与后端发生任何交互（惰性新建）。
const newConversationItem = (): Conversation => ({
  id: newId(),
  title: '新的咨询',
  preview: '开始一段新对话',
  time: '刚刚',
  messages: [greetingMessage()],
})

// 每次进入/登录都从一条全新空白会话开始；历史会话只在侧边栏按需加载，
// 不再自动恢复“上次对话”，避免拿到失效 sessionId 反复请求后端。
const seedConversations = (): Conversation[] => [newConversationItem()]

/* ----------------------------- 主组件 ----------------------------- */

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>(seedConversations)
  const [activeId, setActiveId] = useState<number>(() => conversations[0].id)
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [progress, setProgress] = useState('')
  const [reviewBusy, setReviewBusy] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [view, setView] = useState<View>('chat')
  const [user, setUser] = useState<UserInfo | null>(null)
  const [authStatus, setAuthStatus] = useState<AuthStatus>(() => (hasAuthToken() ? 'checking' : 'anonymous'))
  const [phone, setPhone] = useState('13500005555')
  const [password, setPassword] = useState('123456')
  const [authError, setAuthError] = useState('')

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const typingTimerRef = useRef<number | null>(null)
  const loadingHistoryRef = useRef<Set<number>>(new Set())
  const preloadingHistoryRef = useRef<Set<string>>(new Set())

  const active = useMemo(
    () => conversations.find((c) => c.id === activeId) ?? conversations[0],
    [conversations, activeId],
  )
  const messages = active.messages

  useEffect(() => () => {
    if (typingTimerRef.current) window.clearTimeout(typingTimerRef.current)
  }, [])

  useEffect(() => {
    if (!hasAuthToken()) return
    getCurrentUser()
      .then((profile) => {
        setUser(toUserInfo(profile))
        setAuthStatus('authenticated')
        const cachedHistory = loadHistoryCache(profile.customerNo)
        if (cachedHistory.length) hydrateHistory(cachedHistory)
        getHistorySessions()
          .then((historySessions) => {
            saveHistoryCache(profile.customerNo, historySessions)
            hydrateHistory(historySessions)
          })
          .catch(() => {
            /* 历史列表加载失败不影响当前登录态 */
          })
      })
      .catch(() => {
        clearAuthToken()
        setUser(null)
        setAuthStatus('anonymous')
      })
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, typing])

  // 更新当前会话的局部状态
  const patchConversation = (conversationId: number, updater: (c: Conversation) => Conversation) =>
    setConversations((list) => list.map((c) => (c.id === conversationId ? updater(c) : c)))

  const patchActive = (updater: (c: Conversation) => Conversation) =>
    patchConversation(activeId, updater)

  const appendMessage = (msg: Message, conversationId = activeId) =>
    patchConversation(conversationId, (c) => ({ ...c, messages: [...c.messages, msg] }))

  const replaceMessage = (id: number, blocks: MessageBlock[], conversationId = activeId) =>
    patchConversation(conversationId, (c) => ({
      ...c,
      messages: c.messages.map((m) => (m.id === id ? { ...m, blocks } : m)),
    }))

  const setConversationSession = (conversationId: number, sessionId?: string, threadId?: string) => {
    if (sessionId) saveSessionId(sessionId)
    patchConversation(conversationId, (c) => ({
      ...c,
      sessionId: sessionId ?? c.sessionId,
      threadId: threadId ?? c.threadId,
    }))
  }

  const hydrateHistory = (historySessions: HistorySession[] = [], fallbackSessionIds: string[] = []) => {
    const mergedSessions = historySessions.length
      ? historySessions
      : fallbackSessionIds.map((sessionId) => ({ sessionId }))
    const uniqueSessions = Array.from(
      new Map(mergedSessions.filter((s) => s.sessionId).map((s) => [s.sessionId, s])).values(),
    )
    if (!uniqueSessions.length) return

    setConversations((list) => {
      const sessionsById = new Map(uniqueSessions.map((session) => [session.sessionId, session]))
      const updatedList = list.map((conversation) => {
        const session = conversation.sessionId ? sessionsById.get(conversation.sessionId) : undefined
        const onlyInitialGreeting =
          conversation.messages.length === 1 && conversation.messages[0].role === 'bot'
        if (!session || !onlyInitialGreeting) return conversation
        if (conversation.historyLoaded === true) return conversation
        if (conversation.historyLoaded === false || conversation.historyLoading === false) {
          return {
            ...conversation,
            ...historyListLabels(session, 0),
            messages: [restoredHistoryMessage(session)],
            historyLoading: false,
          }
        }
        return {
          ...conversation,
          ...historyListLabels(session, 0),
          time: '历史',
          messages: [restoredHistoryMessage(session)],
          historyLoaded: false,
          historyLoading: false,
        }
      })
      const existing = new Set(updatedList.map((c) => c.sessionId).filter(Boolean))
      const historyItems = uniqueSessions
        .filter((session) => !existing.has(session.sessionId))
        .map((session, index): Conversation => ({
          id: newId(),
          ...historyListLabels(session, index),
          time: '历史',
          messages: [restoredHistoryMessage(session)],
          sessionId: session.sessionId,
          historyLoaded: false,
          historyLoading: false,
        }))
      return historyItems.length ? [...updatedList, ...historyItems] : updatedList
    })
  }

  const loadHistory = async (conversationId: number, sessionId: string) => {
    const current = conversations.find((c) => c.id === conversationId)
    if (current?.historyLoaded || current?.historyLoading || loadingHistoryRef.current.has(conversationId)) return
    loadingHistoryRef.current.add(conversationId)

    patchConversation(conversationId, (c) => ({
      ...c,
      historyLoading: true,
      messages: [loadingHistoryMessage()],
    }))

    try {
      const detail = await getHistoryConversation(sessionId)
      const loadedMessages = detail.messages.map(toChatMessage)
      const labels = recentDialogueLabels(
        loadedMessages,
        historyTitle(detail.session, 0),
        historySubtitle(detail.session),
      )
      patchConversation(conversationId, (c) => ({
        ...c,
        title: labels.title,
        preview: labels.preview,
        messages: loadedMessages.length ? loadedMessages : [emptyHistoryMessage()],
        historyLoaded: true,
        historyLoading: false,
      }))
    } catch {
      patchConversation(conversationId, (c) => ({
        ...c,
        messages: [historyLoadFailedMessage({
          sessionId,
          rollingSummary: c.preview,
        })],
        historyLoaded: true,
        historyLoading: false,
      }))
    } finally {
      loadingHistoryRef.current.delete(conversationId)
    }
  }

  useEffect(() => {
    if (authStatus !== 'authenticated') return
    if (active.sessionId && active.historyLoaded === false && !active.historyLoading) {
      loadHistory(active.id, active.sessionId)
    }
  }, [authStatus, active.id, active.sessionId, active.historyLoaded, active.historyLoading])

  useEffect(() => {
    if (authStatus !== 'authenticated') return
    conversations.forEach((conversation) => {
      if (!conversation.sessionId || conversation.historyLoaded !== false || conversation.historyLoading) return
      if (preloadingHistoryRef.current.has(conversation.sessionId)) return
      preloadingHistoryRef.current.add(conversation.sessionId)
      loadHistory(conversation.id, conversation.sessionId)
        .finally(() => preloadingHistoryRef.current.delete(conversation.sessionId!))
    })
  }, [authStatus, conversations])

  // 打字机：逐字渲染文本，完成后把卡片块追加到同一条消息
  const typeOut = (text: string, extras: MessageBlock[], conversationId = activeId) =>
    new Promise<void>((resolve) => {
      const id = newId()
      appendMessage({ id, role: 'bot', blocks: [{ type: 'text', value: '' }] }, conversationId)
      let i = 0
      const tick = () => {
        i = Math.min(text.length, i + 2)
        const shown = text.slice(0, i)
        patchConversation(conversationId, (c) => ({
          ...c,
          messages: c.messages.map((m) =>
            m.id === id ? { ...m, blocks: [{ type: 'text', value: shown }] } : m,
          ),
        }))
        if (i < text.length) {
          typingTimerRef.current = window.setTimeout(tick, 16)
        } else {
          typingTimerRef.current = null
          if (extras.length) {
            patchConversation(conversationId, (c) => ({
              ...c,
              messages: c.messages.map((m) =>
                m.id === id ? { ...m, blocks: [m.blocks[0], ...extras] } : m,
              ),
            }))
          }
          patchConversation(conversationId, (c) => ({
            ...c,
            preview: text || c.preview,
            time: '刚刚',
          }))
          resolve()
        }
      }
      tick()
    })

  const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

  const waitSession = async (session: SessionResponse): Promise<SessionResponse> => {
    let current = session
    while (current.status === 'running') {
      setProgress('生成中')
      await sleep(1100)
      current = await getSession(current.thread_id)
    }
    return current
  }

  const showSessionResult = async (result: SessionResponse, conversationId = activeId) => {
    setConversationSession(conversationId, result.session_id, result.thread_id)

    if (result.status === 'awaiting_review' && result.pending_action) {
      const answer = result.final_answer || '这一步会执行需要确认的业务操作，请先核对。'
      appendMessage({
        id: newId(),
        role: 'bot',
        blocks: [
          { type: 'text', value: answer },
          { type: 'review', value: result.pending_action },
        ],
      }, conversationId)
      patchConversation(conversationId, (c) => ({ ...c, preview: answer, time: '刚刚' }))
      return
    }

    const answer =
      result.status === 'error'
        ? `抱歉，生成回答时出错了：${result.error || '未知错误'}`
        : result.status === 'paused'
          ? '会话已暂停。'
          : result.final_answer || '（暂无回答内容）'
    await typeOut(answer, [], conversationId)
  }

  const respondWithReviewFlow = async (text: string, conversationId: number, sessionId?: string) => {
    const started = await runChat(text, { sessionId })
    setConversationSession(conversationId, started.session_id, started.thread_id)
    const result = await waitSession(started)
    setTyping(false)
    setProgress('')
    await showSessionResult(result, conversationId)
  }

  const respondWithStream = async (text: string, conversationId: number, sessionId?: string) => {
    const result = await streamChat(
      text,
      {
        onStart: (threadId, startedSessionId) => setConversationSession(conversationId, startedSessionId, threadId),
        onStage: (_stage, label) => setProgress(label),
      },
      { sessionId },
    )
    setConversationSession(conversationId, result.session_id, result.thread_id)
    setTyping(false)
    setProgress('')
    if (result.status === 'awaiting_review') {
      await showSessionResult(result, conversationId)
      return
    }
    const answer =
      result.status === 'error'
        ? `抱歉，生成回答时出错了：${result.error || '未知错误'}`
        : result.final_answer || '（暂无回答内容）'
    const productBlocks: MessageBlock[] =
      result.status === 'error'
        ? []
        : result.products.map((p) => ({ type: 'product', value: p }))
    await typeOut(answer, productBlocks, conversationId)
  }

  const respond = async (text: string, conversationId: number, sessionId?: string) => {
    setTyping(true)
    setProgress('')
    try {
      if (REVIEW_FLOW_RE.test(text)) {
        await respondWithReviewFlow(text, conversationId, sessionId)
      } else {
        await respondWithStream(text, conversationId, sessionId)
      }
    } catch {
      setTyping(false)
      setProgress('')
      await typeOut('抱歉，暂时连不上服务，请稍后再试～可告诉我你的预算、品牌偏好或订单号。', [], conversationId)
    }
  }

  const send = (raw?: string) => {
    const text = (raw ?? input).trim()
    if (!text || typing || reviewBusy) return
    const conversationId = active.id
    const sessionId = active.sessionId
    appendMessage({ id: newId(), role: 'user', blocks: [{ type: 'text', value: text }] })
    patchActive((c) => ({
      ...c,
      title: text,
      preview: '等待回答...',
      time: '刚刚',
    }))
    setInput('')
    respond(text, conversationId, sessionId)
  }

  const orderProduct = (product: ProductData) => {
    if (!product.productNo || typing || reviewBusy) return
    const conversationId = active.id
    const sessionId = active.sessionId
    const userMessage = `立即下单：${product.name}（${product.productNo}）x1`
    appendMessage({ id: newId(), role: 'user', blocks: [{ type: 'text', value: userMessage }] }, conversationId)
    patchConversation(conversationId, (c) => ({
      ...c,
      title: product.name ? `下单 ${product.name}` : c.title,
      preview: '正在创建订单...',
      time: '刚刚',
    }))

    const orderSummary = (order: Order) => {
      const item = order.items?.[0]
      const productName = item?.productName || product.name
      const amount = order.totalAmount == null ? '' : `，订单金额 ¥${order.totalAmount}`
      return `已为你创建待付款订单 ${order.orderNo}：${productName} x${item?.quantity ?? 1}${amount}。这笔订单已经记入当前对话，后面你可以直接问“刚才那单”。`
    }

    return createOrder({ productNo: product.productNo, quantity: 1 })
      .then(async (order) => {
        const assistantMessage = orderSummary(order)
        appendMessage({ id: newId(), role: 'bot', blocks: [{ type: 'text', value: assistantMessage }] }, conversationId)
        patchConversation(conversationId, (c) => ({ ...c, preview: assistantMessage, time: '刚刚' }))
        try {
          const memory = await appendAgentMemory({
            sessionId,
            userMessage,
            assistantMessage,
          })
          setConversationSession(conversationId, memory.session_id || sessionId, memory.thread_id)
        } catch {
          appendMessage({
            id: newId(),
            role: 'bot',
            blocks: [{ type: 'text', value: '订单已创建，但这次下单记录暂时没有写入会话记忆。' }],
          }, conversationId)
        }
      })
      .catch((error) => {
        const message = errorMessage(error, '下单失败，请稍后重试。')
        appendMessage({ id: newId(), role: 'bot', blocks: [{ type: 'text', value: message }] }, conversationId)
        patchConversation(conversationId, (c) => ({ ...c, preview: message, time: '刚刚' }))
        throw error
      })
  }

  const navigateTo = (next: View) => {
    setView(next)
    setSidebarOpen(false)
  }

  const newConversation = () => {
    setView('chat')
    // 当前会话没有任何用户输入时，直接复用，不重复新建
    if (!active.messages.some((m) => m.role === 'user')) {
      setSidebarOpen(false)
      return
    }
    clearSessionId()
    const conv = newConversationItem()
    setConversations((list) => [conv, ...list])
    setActiveId(conv.id)
    setSidebarOpen(false)
  }

  const selectConversation = (id: number) => {
    const next = conversations.find((c) => c.id === id)
    if (next?.sessionId) {
      saveSessionId(next.sessionId)
    } else {
      clearSessionId()
    }
    setView('chat')
    setActiveId(id)
    setSidebarOpen(false)
    if (next?.sessionId && next.historyLoaded === false && !next.historyLoading) {
      loadHistory(id, next.sessionId)
    }
  }

  const deleteConversation = async (id: number) => {
    const target = conversations.find((c) => c.id === id)
    if (!target) return
    if (!window.confirm('确定删除这段对话吗？删除后无法恢复。')) return

    // 已落库的历史会话需先请求后端删除；本地未发起过的新会话只在前端移除。
    if (target.sessionId) {
      try {
        await deleteHistoryConversation(target.sessionId)
      } catch {
        window.alert('删除失败，请稍后再试。')
        return
      }
      // 同步清理本地历史缓存
      const cached = loadHistoryCache(user?.customerNo)
      saveHistoryCache(user?.customerNo, cached.filter((s) => s.sessionId !== target.sessionId))
    }

    const remaining = conversations.filter((c) => c.id !== id)
    const nextList = remaining.length ? remaining : seedConversations()
    setConversations(nextList)

    // 删除的是当前激活会话时，切换到剩余的第一条并同步 session 存储
    if (activeId === id) {
      const next = nextList[0]
      setActiveId(next.id)
      if (next.sessionId) saveSessionId(next.sessionId)
      else clearSessionId()
    }
  }

  const submitLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setAuthError('')
    setAuthStatus('checking')
    try {
      const profile = await login(phone.trim(), password)
      clearSessionId()
      const next = seedConversations()
      setConversations(next)
      setActiveId(next[0].id)
      setUser(toUserInfo(profile))
      const loginHistory = profile.historySessions?.length
        ? profile.historySessions
        : (profile.historySessionIds ?? []).map((sessionId) => ({ sessionId }))
      hydrateHistory(loginHistory)
      if (loginHistory.length) {
        saveHistoryCache(profile.customerNo, loginHistory)
      } else {
        clearHistoryCache(profile.customerNo)
      }
      setAuthStatus('authenticated')
    } catch {
      setUser(null)
      setAuthStatus('anonymous')
      setAuthError('登录失败，请检查手机号和密码。')
    }
  }

  const signOut = async () => {
    const previousCustomerNo = user?.customerNo
    try {
      await logout()
    } finally {
      clearSessionId()
      clearHistoryCache(previousCustomerNo)
      const next = seedConversations()
      setUser(null)
      setAuthStatus('anonymous')
      setConversations(next)
      setActiveId(next[0].id)
      setSidebarOpen(false)
    }
  }

  const continueAfterConfirm = async (messageId: number, payload: Parameters<typeof confirmAction>[0], conversationId = activeId) => {
    setReviewBusy(true)
    setTyping(true)
    setProgress('继续执行')
    replaceMessage(
      messageId,
      [{ type: 'text', value: payload.approved ? '已确认，正在提交...' : '已收到，将继续处理...' }],
      conversationId,
    )
    try {
      const resumed = await confirmAction(payload)
      const result = await waitSession(resumed)
      setReviewBusy(false)
      setTyping(false)
      setProgress('')
      await showSessionResult(result, conversationId)
    } catch (error) {
      setReviewBusy(false)
      setTyping(false)
      setProgress('')
      await typeOut(errorMessage(error, '确认操作失败，请稍后再试。'), [], conversationId)
    }
  }

  const approveReview = (messageId: number, args: Record<string, unknown>) => {
    if (!active.threadId) return
    continueAfterConfirm(messageId, { thread_id: active.threadId, approved: true, args }, active.id)
  }

  const cancelReview = (messageId: number, message: string, regenerate?: boolean) => {
    if (!active.threadId) return
    continueAfterConfirm(messageId, { thread_id: active.threadId, approved: false, regenerate, message }, active.id)
  }

  const onlyGreeting = messages.length === 1 && messages[0].role === 'bot'

  if (authStatus !== 'authenticated') {
    return (
      <div className="login-shell">
        <form className="login-panel" onSubmit={submitLogin}>
          <div>
            <div className="login-kicker">智能客服网关</div>
            <h1>登录后继续咨询</h1>
          </div>

          <label className="login-field">
            <span>手机号</span>
            <input
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              inputMode="tel"
              autoComplete="username"
              placeholder="请输入手机号"
              disabled={authStatus === 'checking'}
            />
          </label>

          <label className="login-field">
            <span>密码</span>
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete="current-password"
              placeholder="请输入密码"
              disabled={authStatus === 'checking'}
            />
          </label>

          {authError && <div className="login-error">{authError}</div>}

          <button className="login-submit" disabled={authStatus === 'checking' || !phone.trim() || !password}>
            {authStatus === 'checking' ? '正在登录...' : '登录'}
          </button>
        </form>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="login-shell">
        <div className="login-panel">
          <div className="login-kicker">智能客服网关</div>
          <h1>正在加载用户信息...</h1>
        </div>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        user={user}
        open={sidebarOpen}
        view={view}
        onSelect={selectConversation}
        onNew={newConversation}
        onDelete={deleteConversation}
        onNavigate={navigateTo}
        onClose={() => setSidebarOpen(false)}
      />

      {view === 'orders' ? (
        <div className="main">
          <OrdersView onMenu={() => setSidebarOpen(true)} />
        </div>
      ) : view === 'aftersales' ? (
        <div className="main">
          <AfterSalesView onMenu={() => setSidebarOpen(true)} />
        </div>
      ) : (
        <div className="main">
          <ChatHeader
            title={active.title}
            user={user}
            onMenu={() => setSidebarOpen(true)}
            onLogout={signOut}
          />

          <div className="scroll" ref={scrollRef}>
            <div className="thread">
              {onlyGreeting && <Welcome user={user} onPick={(s) => send(s)} />}

              {messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  msg={message}
                  user={user}
                  reviewBusy={reviewBusy}
                  onOrderProduct={orderProduct}
                  onApproveReview={approveReview}
                  onCancelReview={cancelReview}
                />
              ))}

              {typing && (
                <div className="msg bot">
                  <div className="avatar bot">数</div>
                  <div className="bubble-wrap">
                    <div className="bubble bot typing-bubble">
                      <div className="typing">
                        <span />
                        <span />
                        <span />
                      </div>
                      {progress && <span className="typing-label">{progress}</span>}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <Composer
            value={input}
            disabled={typing || reviewBusy}
            onChange={setInput}
            onSend={() => send()}
            onQuick={(q) => send(q)}
          />
        </div>
      )}
    </div>
  )
}
