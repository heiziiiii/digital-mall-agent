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
  reason: '原因',
  refundAmount: '退款金额',
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

  const approve = () => {
    if (missing.length) return
    const args = fields.reduce<Record<string, unknown>>((acc, key) => {
      const value = values[key]?.trim()
      acc[key] = NUMBER_FIELDS.has(key) ? Number(value || 0) : value
      return acc
    }, { ...action.args })
    onApprove(args)
  }

  return (
    <div className="review-card">
      <div className="review-head">
        <span className="review-kicker">需要确认</span>
        <strong>{action.instruction || '请核对信息后再提交'}</strong>
      </div>

      <div className="review-grid">
        {fields.map((key) => (
          <label key={key} className="review-field">
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
            ) : (
              <input
                value={values[key] ?? ''}
                onChange={(event) => setValues((v) => ({ ...v, [key]: event.target.value }))}
                inputMode={key === 'refundAmount' ? 'decimal' : key === 'quantity' ? 'numeric' : 'text'}
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
