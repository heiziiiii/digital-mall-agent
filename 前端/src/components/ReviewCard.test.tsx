// 场景 1（局部）：用户要求售后时，前端是否把待确认的写操作渲染成「对应反馈」——
// 即一张可编辑的售后确认卡片（订单号 / 售后类型 / 原因 / 退款金额 + 确认/取消/重写）。
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ReviewCard from './ReviewCard'
import type { PendingAction } from '../api'

// 后端 awaiting_review 阶段产出的售后待确认动作（对齐 docs/frontend-api.md）
function afterSaleAction(overrides: Partial<PendingAction> = {}): PendingAction {
  return {
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
    instruction: '请核对售后申请信息；如有缺失请补全，确认后才会真正提交。',
    ...overrides,
  }
}

describe('ReviewCard 售后确认反馈', () => {
  it('把售后待确认动作渲染成可编辑表单与操作按钮', () => {
    render(
      <ReviewCard action={afterSaleAction()} onApprove={() => {}} onCancel={() => {}} />,
    )

    // 指引文案 + 四个业务字段标签
    expect(screen.getByText('请核对售后申请信息；如有缺失请补全，确认后才会真正提交。')).toBeInTheDocument()
    expect(screen.getByText('订单号')).toBeInTheDocument()
    expect(screen.getByText('售后类型')).toBeInTheDocument()
    expect(screen.getByText('原因')).toBeInTheDocument()
    expect(screen.getByText('退款金额')).toBeInTheDocument()

    // 三个操作入口
    expect(screen.getByRole('button', { name: '确认提交' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '按意见重写' })).toBeInTheDocument()

    // 预填后端给出的已知字段值
    expect(screen.getByDisplayValue('O100')).toBeInTheDocument()
    expect(screen.getByDisplayValue('屏幕碎裂')).toBeInTheDocument()
  })

  it('确认提交回传合并后的参数，数值字段转成 number', async () => {
    const onApprove = vi.fn()
    render(<ReviewCard action={afterSaleAction()} onApprove={onApprove} onCancel={() => {}} />)

    await userEvent.click(screen.getByRole('button', { name: '确认提交' }))

    expect(onApprove).toHaveBeenCalledTimes(1)
    const args = onApprove.mock.calls[0][0]
    expect(args.orderNo).toBe('O100')
    expect(args.reason).toBe('屏幕碎裂')
    expect(args.type).toBe(1) // select 字符串 '1' → Number
    expect(args.refundAmount).toBe(4999)
  })

  it('必填字段缺失时禁用确认提交，补齐后恢复可用', async () => {
    // reason 缺失：required 含 reason，但 args.reason 为空
    const action = afterSaleAction({
      args: { orderNo: 'O100', type: 1, reason: '', refundAmount: 4999 },
      known_fields: { orderNo: 'O100', type: 1, refundAmount: 4999 },
      missing_fields: ['reason'],
    })
    const onApprove = vi.fn()
    render(<ReviewCard action={action} onApprove={onApprove} onCancel={() => {}} />)

    const submit = screen.getByRole('button', { name: '确认提交' })
    expect(submit).toBeDisabled()

    // 用户补齐原因后，确认按钮恢复可用并能提交
    await userEvent.type(screen.getByLabelText(/原因/), '无法开机')
    expect(submit).toBeEnabled()
    await userEvent.click(submit)
    expect(onApprove).toHaveBeenCalledTimes(1)
    expect(onApprove.mock.calls[0][0].reason).toBe('无法开机')
  })

  it('人工服务确认不展示也不提交售后单号', async () => {
    const onApprove = vi.fn()
    render(
      <ReviewCard
        action={afterSaleAction({
          tool: 'createHumanService',
          args: { orderNo: 'O100', afterSaleNo: 'AS100', reason: '要求人工处理' },
          known_fields: { orderNo: 'O100', afterSaleNo: 'AS100', reason: '要求人工处理' },
          required_fields: ['reason'],
          editable_fields: ['orderNo', 'afterSaleNo', 'reason'],
        })}
        onApprove={onApprove}
        onCancel={() => {}}
      />,
    )

    expect(screen.queryByText('售后单号')).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('AS100')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '确认提交' }))

    expect(onApprove).toHaveBeenCalledTimes(1)
    expect(onApprove.mock.calls[0][0].afterSaleNo).toBeUndefined()
    expect(onApprove.mock.calls[0][0]).toMatchObject({
      orderNo: 'O100',
      reason: '要求人工处理',
    })
  })

  it('创建订单确认展示订单字段，并把数量转成 number', async () => {
    const onApprove = vi.fn()
    render(
      <ReviewCard
        action={{
          state: 'awaiting_review',
          kind: 'tool_approval',
          agent: 'order',
          tool: 'createOrder',
          call_id: 'call_order_1',
          args: {
            productNo: 'P10006',
            quantity: 1,
            spec: '白色 512G',
            receiverName: '陈工',
            receiverPhone: '13500005555',
            receiverAddress: '广州市天河区体育西路66号',
          },
          known_fields: { productNo: 'P10006', quantity: 1 },
          missing_fields: [],
          required_fields: ['productNo', 'quantity', 'receiverName', 'receiverPhone', 'receiverAddress'],
          editable_fields: ['productNo', 'quantity', 'spec', 'receiverName', 'receiverPhone', 'receiverAddress'],
          instruction: '请核对订单信息；如有缺失请补全，确认后才会真正创建订单。',
        }}
        onApprove={onApprove}
        onCancel={() => {}}
      />,
    )

    expect(screen.getByText('请核对订单信息；如有缺失请补全，确认后才会真正创建订单。')).toBeInTheDocument()
    expect(screen.getByText('商品编号')).toBeInTheDocument()
    expect(screen.getByText('购买数量')).toBeInTheDocument()
    expect(screen.getByText('收货地址')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '确认提交' }))

    expect(onApprove).toHaveBeenCalledTimes(1)
    expect(onApprove.mock.calls[0][0]).toMatchObject({
      productNo: 'P10006',
      quantity: 1,
      receiverName: '陈工',
    })
  })
})
