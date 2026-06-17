import { useEffect, useState } from 'react'
import { cancelAfterSale, getMyAfterSales, type AfterSale } from '../api'
import {
  afterSaleStatusInfo,
  afterSaleTypeLabel,
  formatDateTime,
} from '../orderDisplay'

type AfterSalesViewProps = {
  onMenu: () => void
}

// 「我的售后」页面：拉取当前用户全部售后单，按卡片展示类型、进度、原因。
export default function AfterSalesView({ onMenu }: AfterSalesViewProps) {
  const [afterSales, setAfterSales] = useState<AfterSale[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    setError('')
    getMyAfterSales()
      .then(setAfterSales)
      .catch(() => setError('售后记录加载失败，请稍后重试。'))
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
          <span className="header-name">我的售后</span>
          <span className="header-sub">查看退换货、维修与退款进度</span>
        </div>
        <div className="header-spacer" />
        <button className="btn-logout" onClick={load} disabled={loading}>
          {loading ? '刷新中…' : '刷新'}
        </button>
      </header>

      <div className="scroll">
        <div className="page-body">
          {loading ? (
            <div className="page-state">正在加载售后记录…</div>
          ) : error ? (
            <div className="page-state error">{error}</div>
          ) : afterSales.length === 0 ? (
            <div className="page-state">暂无售后记录。</div>
          ) : (
            afterSales.map((item) => (
              <AfterSaleCard key={item.afterSaleNo} afterSale={item} onChanged={load} />
            ))
          )}
        </div>
      </div>
    </div>
  )
}

function AfterSaleCard({ afterSale, onChanged }: { afterSale: AfterSale; onChanged: () => void }) {
  const status = afterSaleStatusInfo(afterSale.status)
  const [cancelling, setCancelling] = useState(false)

  // 仅「待审核」(status=0) 的售后单可撤销
  const canCancel = afterSale.status === 0

  const handleCancel = () => {
    if (!window.confirm('确认撤销该售后申请？撤销后申请将被删除，且无法恢复。')) return
    setCancelling(true)
    cancelAfterSale(afterSale.afterSaleNo)
      .then(onChanged)
      .catch(() => window.alert('撤销失败，请稍后重试。'))
      .finally(() => setCancelling(false))
  }

  return (
    <div className="order-card">
      <div className="order-head">
        <div className="order-head-left">
          <span className="order-product">{afterSaleTypeLabel(afterSale.type)}</span>
          <span className="order-no">
            售后号 {afterSale.afterSaleNo} · {formatDateTime(afterSale.createdAt)}
          </span>
        </div>
        <span className={`tag tag-${status.tone}`}>{status.label}</span>
      </div>

      <dl className="order-fields">
        <div className="order-field">
          <dt>关联订单</dt>
          <dd>{afterSale.orderNo}</dd>
        </div>
        {afterSale.reason && (
          <div className="order-field">
            <dt>申请原因</dt>
            <dd>{afterSale.reason}</dd>
          </div>
        )}
        {afterSale.remark && (
          <div className="order-field">
            <dt>处理备注</dt>
            <dd>{afterSale.remark}</dd>
          </div>
        )}
      </dl>

      {canCancel && (
        <div className="order-actions">
          <button className="btn-cancel" onClick={handleCancel} disabled={cancelling}>
            {cancelling ? '撤销中…' : '撤销申请'}
          </button>
        </div>
      )}
    </div>
  )
}
