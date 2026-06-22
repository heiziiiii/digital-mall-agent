import { useEffect, useState } from 'react'
import { cancelOrder, getMyOrders, type Order } from '../api'
import {
  formatDateTime,
  formatMoney,
  logisticsStatusInfo,
  orderStatusInfo,
  orderSummaryTitle,
  payStatusInfo,
} from '../orderDisplay'

type OrdersViewProps = {
  onMenu: () => void
}

// 「我的订单」页面：拉取当前用户全部订单，按卡片展示明细、金额、物流概况。
export default function OrdersView({ onMenu }: OrdersViewProps) {
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    setError('')
    getMyOrders()
      .then(setOrders)
      .catch(() => setError('订单加载失败，请稍后重试。'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <div className="page">
      <header className="header">
        <button className="menu-btn" onClick={onMenu} aria-label="打开菜单">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
        <div className="header-title">
          <span className="header-name">我的订单</span>
          <span className="header-sub">查看你的全部订单与物流进度</span>
        </div>
        <div className="header-spacer" />
        <button className="btn-logout" onClick={load} disabled={loading}>
          {loading ? '刷新中…' : '刷新'}
        </button>
      </header>

      <div className="scroll">
        <div className="page-body">
          {loading ? (
            <div className="page-state">正在加载订单…</div>
          ) : error ? (
            <div className="page-state error">{error}</div>
          ) : orders.length === 0 ? (
            <div className="page-state">暂无订单记录。</div>
          ) : (
            orders.map((order) => <OrderCard key={order.orderNo} order={order} onChanged={load} />)
          )}
        </div>
      </div>
    </div>
  )
}

function OrderCard({ order, onChanged }: { order: Order; onChanged: () => void }) {
  const status = orderStatusInfo(order.orderStatus)
  const pay = payStatusInfo(order.payStatus)
  const items = order.items ?? []
  const logistics = order.logistics
  const latestTrace = logistics?.traces?.[0]
  const [cancelling, setCancelling] = useState(false)

  // 仅「待付款」(orderStatus=0) 的订单可撤销
  const canCancel = order.orderStatus === 0

  const handleCancel = () => {
    if (!window.confirm('确认撤销该订单？撤销后订单将被取消，且无法恢复。')) return
    setCancelling(true)
    cancelOrder(order.orderNo)
      .then(onChanged)
      .catch(() => window.alert('撤销失败，请稍后重试。'))
      .finally(() => setCancelling(false))
  }

  return (
    <div className="order-card">
      <div className="order-head">
        <div className="order-head-left">
          <span className="order-product">{orderSummaryTitle(order)}</span>
          <span className="order-no">订单号 {order.orderNo} · {formatDateTime(order.createdAt)}</span>
        </div>
        <span className={`tag tag-${status.tone}`}>{status.label}</span>
      </div>

      {items.length > 0 && (
        <ul className="order-items">
          {items.map((item, index) => (
            <li key={`${item.productNo}-${index}`} className="order-item">
              <span className="order-item-name">
                {item.productName}
                {item.spec ? <em className="order-item-spec">{item.spec}</em> : null}
              </span>
              <span className="order-item-meta">
                <span className="order-item-price">¥{formatMoney(item.price)}</span>
                <span className="order-item-qty">×{item.quantity}</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {logistics && (
        <div className="order-logistics">
          <span className={`tag tag-${logisticsStatusInfo(logistics.status).tone}`}>
            {logisticsStatusInfo(logistics.status).label}
          </span>
          <span className="order-logistics-text">
            {[logistics.company, logistics.trackingNo].filter(Boolean).join(' ')}
            {latestTrace ? ` · ${latestTrace.description}` : ''}
          </span>
        </div>
      )}

      <div className="order-foot">
        <span className={`tag tag-${pay.tone} tag-soft`}>{pay.label}</span>
        <div className="order-amount">
          实付
          <span className="cur">¥</span>
          <b>{formatMoney(order.payAmount)}</b>
        </div>
      </div>

      {canCancel && (
        <div className="order-actions">
          <button className="btn-cancel" onClick={handleCancel} disabled={cancelling}>
            {cancelling ? '撤销中…' : '撤销订单'}
          </button>
        </div>
      )}
    </div>
  )
}
