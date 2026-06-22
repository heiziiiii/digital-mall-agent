const BASE_URL = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
const AGENT_PREFIX = '/api/agent'
const AUTH_PREFIX = '/api/auth'
const CUSTOMER_PREFIX = '/api/customer'
const AUTH_TOKEN_KEY = 'token'

function getAuthToken(): string {
  const envToken = import.meta.env.VITE_API_TOKEN as string | undefined
  try {
    const legacyToken = localStorage.getItem(AUTH_TOKEN_KEY)
    if (legacyToken) localStorage.removeItem(AUTH_TOKEN_KEY)
    return sessionStorage.getItem(AUTH_TOKEN_KEY) || envToken || ''
  } catch {
    return envToken || ''
  }
}

function jsonHeaders(options: { auth?: boolean } = {}): HeadersInit {
  const includeAuth = options.auth ?? true
  const token = getAuthToken()
  return {
    'Content-Type': 'application/json',
    ...(includeAuth && token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export type SessionStatus = 'running' | 'paused' | 'awaiting_review' | 'completed' | 'error'

type ApiEnvelope<T> = {
  code: number
  message: string
  data: T
}

export type LoginResponse = {
  token: string
  expiresIn: number
  customerId?: number
  id?: string | number
  userId?: string
  user_id?: string
  customerNo: string
  nickname: string
  memberLevel: number
  historySessionIds?: string[]
  historySessions?: HistorySession[]
}

export type HistorySession = {
  sessionId: string
  rollingSummary?: string
  lastUserMessage?: string
  lastAssistantMessage?: string
  updatedAt?: string
}

export type HistoryMessage = {
  role: string
  content: string
  turn?: number
  createdAt?: string
}

export type HistoryConversation = {
  session: HistorySession
  messages: HistoryMessage[]
}

export type CurrentUserResponse = {
  customerId?: number
  id?: string | number
  userId?: string
  user_id?: string
  customerNo: string
  nickname: string
  memberLevel: number
}

export type OrderItem = {
  productNo: string
  productName: string
  spec?: string
  price: string | number
  quantity: number
}

export type LogisticsTrace = {
  time: string
  location?: string
  description: string
}

export type Logistics = {
  company?: string
  trackingNo?: string
  status: number
  traces?: LogisticsTrace[]
}

export type Order = {
  id: number
  orderNo: string
  customerId: number
  totalAmount: string | number
  payAmount: string | number
  orderStatus: number
  payStatus: number
  receiverName?: string
  receiverPhone?: string
  receiverAddress?: string
  items?: OrderItem[]
  logistics?: Logistics | null
  createdAt?: string
  updatedAt?: string
}

export type AfterSale = {
  id: number
  afterSaleNo: string
  orderNo: string
  customerId: number
  type: number
  reason?: string
  status: number
  remark?: string
  createdAt?: string
  updatedAt?: string
}

export type SessionResponse = {
  thread_id: string
  session_id?: string
  status: SessionStatus
  final_answer: string
  error: string
  pending_action?: PendingAction
}

export type PendingAction = {
  state: 'awaiting_review'
  kind: string
  agent: string
  tool: string
  call_id: string
  args: Record<string, unknown>
  known_fields?: Record<string, unknown>
  missing_fields?: string[]
  required_fields?: string[]
  editable_fields?: string[]
  instruction?: string
  guide_message?: string
}

export type ConfirmPayload =
  | { thread_id: string; approved: true; args?: Record<string, unknown> }
  | { thread_id: string; approved: false; regenerate?: boolean; message?: string }

export type ProductRecommendation = {
  productNo: string
  name: string
  price: string
  stockStatus: string
  highlights: string[]
  reason: string
}

export type StreamResult = SessionResponse & { products: ProductRecommendation[] }

// 从可能带 ```json 围栏或前后杂字的文本里提取首个 JSON 对象
function safeParseJsonObject(text: string): Record<string, any> | null {
  const tryParse = (s: string): Record<string, any> | null => {
    try {
      const v = JSON.parse(s)
      return v && typeof v === 'object' && !Array.isArray(v) ? v : null
    } catch {
      return null
    }
  }
  const direct = tryParse(text.trim())
  if (direct) return direct
  const fenced = text.match(/\{[\s\S]*\}/)
  return fenced ? tryParse(fenced[0]) : null
}

// 解析 product_agent 节点写入的状态增量，提取结构化商品推荐。
// 非结构化输出（澄清/转交话术）会被安全地忽略，返回空数组。
function parseProductRecommendations(update: Record<string, unknown>): ProductRecommendation[] {
  const results = update?.agent_results as Record<string, unknown> | undefined
  const raw = results?.product
  if (typeof raw !== 'string') return []

  const obj = safeParseJsonObject(raw)
  if (!obj || obj.reply_type !== 'product_recommendation') return []

  const recs = Array.isArray(obj.recommendations) ? obj.recommendations : []
  return recs
    .filter((r): r is Record<string, unknown> => !!r && typeof r === 'object')
    .map((r) => ({
      productNo: String(r.product_no ?? ''),
      name: String(r.name ?? ''),
      price: r.price == null ? '' : String(r.price),
      stockStatus: String(r.stock_status ?? ''),
      highlights: Array.isArray(r.highlights) ? r.highlights.map(String) : [],
      reason: String(r.reason ?? ''),
    }))
    .filter((r) => r.name)
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit, options?: { auth?: boolean }): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...jsonHeaders(options),
      ...init?.headers,
    },
  })
  if (!res.ok) {
    let detail = ''
    try {
      detail = JSON.stringify(await res.json())
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`)
  }
  return (await res.json()) as T
}

async function requestEnvelope<T>(path: string, init?: RequestInit, options?: { auth?: boolean }): Promise<T> {
  const body = await request<ApiEnvelope<T>>(path, init, options)
  if (body.code !== 0) throw new ApiError(200, body.message || '请求失败')
  return body.data
}

export function saveAuthToken(token: string) {
  sessionStorage.setItem(AUTH_TOKEN_KEY, token)
  try {
    localStorage.removeItem(AUTH_TOKEN_KEY)
  } catch {
    /* 忽略旧 token 清理失败 */
  }
}

export function clearAuthToken() {
  sessionStorage.removeItem(AUTH_TOKEN_KEY)
  try {
    localStorage.removeItem(AUTH_TOKEN_KEY)
  } catch {
    /* 忽略旧 token 清理失败 */
  }
}

export function hasAuthToken(): boolean {
  return Boolean(getAuthToken())
}

export async function login(phone: string, password: string): Promise<LoginResponse> {
  const data = await requestEnvelope<LoginResponse>(`${AUTH_PREFIX}/login`, {
    method: 'POST',
    body: JSON.stringify({ phone, password }),
  }, { auth: false })
  saveAuthToken(data.token)
  return data
}

export function getCurrentUser(): Promise<CurrentUserResponse> {
  return requestEnvelope<CurrentUserResponse>(`${AUTH_PREFIX}/me`)
}

export function getHistorySessions(): Promise<HistorySession[]> {
  return requestEnvelope<HistorySession[]>(`${AUTH_PREFIX}/history`)
}

export function getHistoryConversation(sessionId: string): Promise<HistoryConversation> {
  return requestEnvelope<HistoryConversation>(`${AUTH_PREFIX}/history/${encodeURIComponent(sessionId)}`)
}

export function deleteHistoryConversation(sessionId: string): Promise<boolean> {
  return requestEnvelope<boolean>(`${AUTH_PREFIX}/history/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
}

export async function logout(): Promise<void> {
  try {
    await requestEnvelope<null>(`${AUTH_PREFIX}/logout`, { method: 'POST' })
  } finally {
    clearAuthToken()
  }
}

export async function getMyOrders(): Promise<Order[]> {
  const data = await requestEnvelope<Order[] | null>(`${CUSTOMER_PREFIX}/orders`)
  return data ?? []
}

export function getOrderDetail(orderNo: string): Promise<Order> {
  return requestEnvelope<Order>(`${CUSTOMER_PREFIX}/orders/${encodeURIComponent(orderNo)}`)
}

export type CreateOrderInput = {
  productNo: string
  quantity?: number
  spec?: string
  receiverName?: string
  receiverPhone?: string
  receiverAddress?: string
}

export function createOrder(input: CreateOrderInput): Promise<Order> {
  return requestEnvelope<Order>(`${CUSTOMER_PREFIX}/orders`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function appendAgentMemory(input: {
  sessionId?: string
  userMessage: string
  assistantMessage: string
}): Promise<SessionResponse> {
  return request<SessionResponse>(`${AGENT_PREFIX}/memory/append`, {
    method: 'POST',
    body: JSON.stringify({
      session_id: input.sessionId,
      user_message: input.userMessage,
      assistant_message: input.assistantMessage,
    }),
  })
}

export function cancelOrder(orderNo: string): Promise<Order> {
  return requestEnvelope<Order>(`${CUSTOMER_PREFIX}/orders/${encodeURIComponent(orderNo)}/cancel`, {
    method: 'POST',
  })
}

export async function getMyAfterSales(): Promise<AfterSale[]> {
  const data = await requestEnvelope<AfterSale[] | null>(`${CUSTOMER_PREFIX}/aftersales`)
  return data ?? []
}

export function getAfterSaleDetail(afterSaleNo: string): Promise<AfterSale> {
  return requestEnvelope<AfterSale>(`${CUSTOMER_PREFIX}/aftersales/${encodeURIComponent(afterSaleNo)}`)
}

export function cancelAfterSale(afterSaleNo: string): Promise<null> {
  return requestEnvelope<null>(`${CUSTOMER_PREFIX}/aftersales/${encodeURIComponent(afterSaleNo)}/cancel`, {
    method: 'POST',
  })
}

function chatPayload(message: string, sessionId?: string, newSession = false) {
  return {
    message,
    new_session: newSession,
    ...(sessionId ? { session_id: sessionId } : {}),
  }
}

export function runChat(
  message: string,
  options: { userId?: string; sessionId?: string; newSession?: boolean } = {},
): Promise<SessionResponse> {
  return request<SessionResponse>(`${AGENT_PREFIX}/run`, {
    method: 'POST',
    body: JSON.stringify(chatPayload(message, options.sessionId, options.newSession)),
  })
}

export type StreamEvent =
  | { type: 'start'; thread_id: string; session_id?: string }
  | { type: 'stage'; stage: string; label: string; update: Record<string, unknown> }
  | { type: 'node'; node: string; label: string; update: Record<string, unknown> }
  | { type: 'done'; thread_id?: string; session_id?: string; final_answer: string; status: 'completed' }
  | { type: 'error'; message: string; status: 'error' }

export type StreamHandlers = {
  onStart?: (threadId: string, sessionId?: string) => void
  onStage?: (stage: string, label: string, update: Record<string, unknown>) => void
  onNode?: (node: string, label: string, update: Record<string, unknown>) => void
  onProducts?: (products: ProductRecommendation[]) => void
  onReview?: (action: PendingAction) => void
  onDone?: (finalAnswer: string, sessionId?: string) => void
  onError?: (message: string) => void
}

function isPendingAction(value: unknown): value is PendingAction {
  return !!value && typeof value === 'object' && (value as PendingAction).state === 'awaiting_review'
}

export async function streamChat(
  message: string,
  handlers: StreamHandlers = {},
  options: { userId?: string; sessionId?: string; newSession?: boolean; signal?: AbortSignal } = {},
): Promise<StreamResult> {
  const { sessionId, newSession, signal } = options
  const res = await fetch(`${BASE_URL}${AGENT_PREFIX}/stream`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(chatPayload(message, sessionId, newSession)),
    signal,
  })
  if (!res.ok || !res.body) {
    let detail = ''
    try {
      detail = JSON.stringify(await res.json())
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let threadId = ''
  let memorySessionId = sessionId
  let result: SessionResponse | null = null
  let products: ProductRecommendation[] = []

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? '' // 末尾可能是半条，留到下次
    for (const part of parts) {
      const line = part.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      let evt: StreamEvent
      try {
        evt = JSON.parse(line.slice(6)) as StreamEvent
      } catch {
        continue // 忽略无法解析的片段
      }
      switch (evt.type) {
        case 'start':
          threadId = evt.thread_id
          if (evt.session_id) memorySessionId = evt.session_id
          handlers.onStart?.(evt.thread_id, evt.session_id)
          break
        case 'stage':
          handlers.onStage?.(evt.stage, evt.label, evt.update)
          handlers.onNode?.(evt.stage, evt.label, evt.update)
          if (evt.stage === 'awaiting_review' && isPendingAction(evt.update.pending_action)) {
            const pendingAction = evt.update.pending_action
            handlers.onReview?.(pendingAction)
            result = {
              thread_id: threadId,
              session_id: memorySessionId,
              status: 'awaiting_review',
              final_answer: '',
              error: '',
              pending_action: pendingAction,
            }
          }
          if (evt.stage === 'product_agent') {
            const parsed = parseProductRecommendations(evt.update)
            if (parsed.length) {
              products = parsed
              handlers.onProducts?.(parsed)
            }
          }
          break
        case 'node':
          handlers.onNode?.(evt.node, evt.label, evt.update)
          if (evt.node === 'product_agent') {
            const parsed = parseProductRecommendations(evt.update)
            if (parsed.length) {
              products = parsed
              handlers.onProducts?.(parsed)
            }
          }
          break
        case 'done':
          if (evt.thread_id) threadId = evt.thread_id
          if (evt.session_id) memorySessionId = evt.session_id
          handlers.onDone?.(evt.final_answer, evt.session_id)
          result = {
            thread_id: threadId,
            session_id: memorySessionId,
            status: 'completed',
            final_answer: evt.final_answer,
            error: '',
          }
          break
        case 'error':
          handlers.onError?.(evt.message)
          result = { thread_id: threadId, session_id: memorySessionId, status: 'error', final_answer: '', error: evt.message }
          break
      }
    }
  }

  const base = result ?? {
    thread_id: threadId,
    session_id: memorySessionId,
    status: 'completed' as const,
    final_answer: '',
    error: '',
  }
  return { ...base, products }
}

export function pauseChat(threadId: string): Promise<SessionResponse> {
  return request<SessionResponse>(`${AGENT_PREFIX}/pause`, {
    method: 'POST',
    body: JSON.stringify({ thread_id: threadId }),
  })
}

export function resumeChat(threadId: string): Promise<SessionResponse> {
  return request<SessionResponse>(`${AGENT_PREFIX}/resume`, {
    method: 'POST',
    body: JSON.stringify({ thread_id: threadId }),
  })
}

export function confirmAction(payload: ConfirmPayload): Promise<SessionResponse> {
  return request<SessionResponse>(`${AGENT_PREFIX}/confirm`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getSession(threadId: string): Promise<SessionResponse> {
  return request<SessionResponse>(`${AGENT_PREFIX}/sessions/${encodeURIComponent(threadId)}`)
}

export function checkHealth(): Promise<{ status: string }> {
  return request<{ status: string }>(`${AGENT_PREFIX}/health`)
}

export { ApiError }
