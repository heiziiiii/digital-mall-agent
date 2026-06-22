// 场景 1（端到端）：用户要求售后时，前端是否生成对应的反馈。
// 这里 mock 掉 ./api，只验证「输入售后诉求 → 走审核流程 → 渲染确认卡片 → 可确认提交」
// 这条前端交互链路，不依赖真实网关 / Agent。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// vi.mock 工厂会被提升到文件顶部，无法引用普通顶层变量；
// 共享的 mock 函数与样例数据统一放进 vi.hoisted，确保提前初始化。
const mocks = vi.hoisted(() => {
  const afterSaleAction = {
    state: 'awaiting_review',
    kind: 'tool_approval',
    agent: 'order',
    tool: 'createAfterSale',
    call_id: 'call_1',
    args: { orderNo: 'O100', type: 1, reason: '屏幕碎裂', refundAmount: 4999 },
    known_fields: { orderNo: 'O100', type: 1, reason: '屏幕碎裂', refundAmount: 4999 },
    missing_fields: [],
    required_fields: ['orderNo', 'type', 'reason'],
    editable_fields: ['orderNo', 'type', 'reason', 'refundAmount'],
    instruction: '请填写并核对售后申请表，确认后才会提交售后申请。',
    guide_message: 'HITL 引导 Agent：请填写售后申请表并核对原因。',
  }
  const reviewSession = {
    thread_id: 't1',
    session_id: 's1',
    status: 'awaiting_review',
    final_answer: '',
    error: '',
    pending_action: afterSaleAction,
  }
  return {
    runChat: vi.fn(async (..._args: any[]) => reviewSession),
    createOrder: vi.fn(async (..._args: any[]) => ({
      id: 1,
      orderNo: 'O200',
      customerId: 1,
      totalAmount: 5299,
      payAmount: 0,
      orderStatus: 0,
      payStatus: 0,
      items: [{ productNo: 'P10006', productName: '小米 14 Pro', price: 5299, quantity: 1 }],
    })),
    appendAgentMemory: vi.fn(async (..._args: any[]) => ({
      thread_id: '',
      session_id: 's1',
      status: 'completed',
      final_answer: 'memory saved',
      error: '',
    })),
    confirmAction: vi.fn(async (..._args: any[]) => ({
      thread_id: 't1',
      session_id: 's1',
      status: 'completed',
      final_answer: '已为你提交售后单 A123。',
      error: '',
    })),
  }
})

vi.mock('./api', () => ({
  hasAuthToken: () => false,
  login: vi.fn(async () => ({
    token: 'jwt',
    expiresIn: 7200,
    customerId: 1,
    customerNo: 'C000001',
    nickname: '张三',
    memberLevel: 1,
    historySessionIds: [],
  })),
  getCurrentUser: vi.fn(),
  getHistorySessions: vi.fn(async () => []),
  getHistoryConversation: vi.fn(),
  logout: vi.fn(async () => {}),
  clearAuthToken: vi.fn(),
  runChat: mocks.runChat,
  streamChat: vi.fn(),
  createOrder: mocks.createOrder,
  appendAgentMemory: mocks.appendAgentMemory,
  getSession: vi.fn(),
  confirmAction: mocks.confirmAction,
}))

import App from './App'

async function loginAndSend(text: string) {
  const user = userEvent.setup()
  render(<App />)

  await user.type(screen.getByPlaceholderText('请输入手机号'), '13800000333')
  await user.type(screen.getByPlaceholderText('请输入密码'), '123456')
  await user.click(screen.getByRole('button', { name: '登录' }))

  const composer = await screen.findByPlaceholderText(/说说您的需求/)
  await user.type(composer, text)
  await user.click(screen.getByRole('button', { name: '发送' }))
  return user
}

describe('用户要求售后 → 前端生成对应反馈', () => {
  beforeEach(() => {
    localStorage.clear()
    mocks.runChat.mockClear()
    mocks.confirmAction.mockClear()
  })

  it('售后诉求走审核流程并渲染待确认卡片', async () => {
    await loginAndSend('我要退货')

    // 走的是非流式审核流程（runChat），不是普通流式问答
    await waitFor(() => expect(mocks.runChat).toHaveBeenCalledTimes(1))
    expect(mocks.runChat.mock.calls[0][0]).toBe('我要退货')

    // 前端把 pending_action 渲染为确认卡片
    expect((await screen.findAllByText(/HITL 引导 Agent：请填写售后申请表并核对原因。/)).length).toBeGreaterThan(0)
    expect(
      await screen.findByText('请填写并核对售后申请表，确认后才会提交售后申请。'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认提交' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('O100')).toBeInTheDocument()
  })

  it('点击确认提交后调用 confirmAction 落库', async () => {
    const user = await loginAndSend('申请售后退款')

    const submit = await screen.findByRole('button', { name: '确认提交' })
    await user.click(submit)

    await waitFor(() => expect(mocks.confirmAction).toHaveBeenCalledTimes(1))
    const payload = mocks.confirmAction.mock.calls[0][0] as Record<string, any>
    expect(payload).toMatchObject({ thread_id: 't1', approved: true })
    expect(payload.args).toMatchObject({ orderNo: 'O100', reason: '屏幕碎裂' })
  })

  it('确认提交失败时展示后端订单归属反馈', async () => {
    mocks.confirmAction.mockRejectedValueOnce(new Error('{"detail":"订单 O100 不属于当前登录用户，不能提交该操作。"}'))
    const user = await loginAndSend('申请售后退款')

    const submit = await screen.findByRole('button', { name: '确认提交' })
    await user.click(submit)

    expect((await screen.findAllByText('订单 O100 不属于当前登录用户，不能提交该操作。')).length).toBeGreaterThan(0)
  })

  it('登录后不会沿用本地残留的旧 sessionId', async () => {
    localStorage.setItem('agent_session_id', 'old-user-session')

    await loginAndSend('我要退货')

    await waitFor(() => expect(mocks.runChat).toHaveBeenCalledTimes(1))
    expect(mocks.runChat.mock.calls[0][1]).toMatchObject({ sessionId: undefined })
    expect(localStorage.getItem('agent_session_id')).toBe('s1')
  })
})
