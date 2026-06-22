import { useMemo, useState } from 'react'
import type { PendingAction } from '../api'

type ReviewCardProps = {
  action: PendingAction
  busy?: boolean
  onApprove: (args: Record<string, unknown>) => void
  onCancel: (message: string, regenerate?: boolean) => void
}

const FIELD_LABELS: Record<string, string> = {
  orderNo: '订单号',
  afterSaleNo: '售后单号',
  productNo: '商品编号',
  quantity: '购买数量',
  spec: '商品规格',
  receiverName: '收货人',
  receiverPhone: '收货手机号',
  receiverAddress: '收货地址',
  type: '售后类型',
  reason: '我的诉求/原因',
  refundAmount: '退款金额',
}

const FIELD_PLACEHOLDERS: Record<string, string> = {
  orderNo: '请输入关联订单号',
  reason: '请补充具体问题或希望处理的事项',
}

const ACTION_TITLES: Record<string, string> = {
  createAfterSale: '售后申请表',
  createHumanService: '人工服务表',
  createOrder: '订单确认表',
}

const TYPE_OPTIONS = [
  { value: '1', label: '退货退款' },
  { value: '2', label: '换货' },
  { value: '3', label: '仅退款' },
  { value: '4', label: '维修' },
]

const HIDDEN_FIELDS = new Set(['afterSaleNo'])
const NUMBER_FIELDS = new Set(['refundAmount', 'type', 'quantity'])

const toText = (value: unknown) => (value == null ? '' : String(value))

export default function ReviewCard({ action, busy, onApprove, onCancel }: ReviewCardProps) {
  const fields = useMemo(
    () => Array.from(new Set([
      ...(action.editable_fields?.length ? action.editable_fields : Object.keys(action.args)),
      ...(action.missing_fields ?? []),
      ...(action.required_fields ?? []),
    ])).filter((key) => !HIDDEN_FIELDS.has(key)),
    [action],
  )
  const required = new Set(action.required_fields ?? [])
  const [values, setValues] = useState<Record<string, string>>(() =>
    fields.reduce((acc, key) => ({ ...acc, [key]: toText(action.args[key]) }), {}),
  )
  const [message, setMessage] = useState('')
  const missing = fields.filter((key) => required.has(key) && !values[key]?.trim())
  const title = ACTION_TITLES[action.tool] ?? '信息确认表'

  const approve = () => {
    if (missing.length) return
    const args = fields.reduce<Record<string, unknown>>((acc, key) => {
      const value = values[key]?.trim()
      acc[key] = NUMBER_FIELDS.has(key) ? Number(value || 0) : value
      return acc
    }, {})
    onApprove(args)
  }

  return (
    <div className="review-card">
      <div className="review-head">
        <span className="review-kicker">{title}</span>
        <strong>{action.instruction || '请核对信息后再提交'}</strong>
      </div>

      <div className="review-grid">
        {fields.map((key) => (
          <label key={key} className={`review-field ${key === 'reason' ? 'review-field-wide' : ''}`}>
            <span>
              {FIELD_LABELS[key] ?? key}
              {required.has(key) && <b>*</b>}
            </span>
            {key === 'type' ? (
              <select
                value={values[key] ?? ''}
                onChange={(event) => setValues((v) => ({ ...v, [key]: event.target.value }))}
                disabled={busy}
              >
                <option value="">请选择</option>
                {TYPE_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            ) : key === 'reason' ? (
              <textarea
                className="review-input-note"
                value={values[key] ?? ''}
                onChange={(event) => setValues((v) => ({ ...v, [key]: event.target.value }))}
                placeholder={FIELD_PLACEHOLDERS[key]}
                disabled={busy}
              />
            ) : (
              <input
                value={values[key] ?? ''}
                onChange={(event) => setValues((v) => ({ ...v, [key]: event.target.value }))}
                inputMode={key === 'refundAmount' ? 'decimal' : key === 'quantity' ? 'numeric' : 'text'}
                placeholder={FIELD_PLACEHOLDERS[key]}
                disabled={busy}
              />
            )}
          </label>
        ))}
      </div>

      <textarea
        className="review-note"
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        placeholder="取消或重新生成时可填写说明"
        disabled={busy}
      />

      <div className="review-actions">
        <button className="btn btn-primary" onClick={approve} disabled={busy || missing.length > 0}>
          确认提交
        </button>
        <button className="btn btn-outline" onClick={() => onCancel(message || '用户取消操作')} disabled={busy}>
          取消
        </button>
        <button className="btn btn-outline" onClick={() => onCancel(message, true)} disabled={busy || !message.trim()}>
          按意见重写
        </button>
      </div>
    </div>
  )
}
