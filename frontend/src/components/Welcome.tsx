import type { UserInfo } from '../App'

type WelcomeProps = {
  user: UserInfo
  onPick: (value: string) => void
}

// 核心能力：发送的文本即用户意图，由后端意图识别路由到对应 Agent
const SUGGESTIONS = [
  { icon: '🛍️', label: '帮我推荐合适的产品', hint: '说预算和需求，智能选品' },
  { icon: '📦', label: '查看我的订单', hint: '订单状态 · 物流追踪' },
  { icon: '🛠️', label: '申请售后服务', hint: '退换 / 退款 / 维修' },
  { icon: '🧩', label: '解决我遇到的技术问题', hint: '使用 · 故障 · 操作指引' },
]

const HIGHLIGHTS = [
  { value: '智能选品', label: '按需求精准推荐' },
  { value: '全程可查', label: '订单售后实时追踪' },
  { value: '操作确认', label: '关键动作先确认' },
]

export default function Welcome({ user, onPick }: WelcomeProps) {
  return (
    <div className="welcome">
      <div className="welcome-hero">
        <span className="welcome-eyebrow">阿数 · AI 智能客服</span>
        <h1 className="welcome-title">
          Hi {user.name}，<span className="grad">我能帮你做点什么？</span>
        </h1>
        <p className="welcome-desc">
          推荐产品、查看订单、售后服务、解决技术问题，把你的需求或订单号告诉我，我来帮你清晰处理。
        </p>

        <div className="welcome-badge">
          <span className="vip-badge">{user.vipTag}</span>
          <span>{user.vipLevel}，享专属服务通道</span>
        </div>

        <div className="highlight-row">
          {HIGHLIGHTS.map((h) => (
            <div key={h.label} className="highlight-card">
              <strong>{h.value}</strong>
              <span>{h.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="suggest-grid">
        {SUGGESTIONS.map((s) => (
          <button key={s.label} className="suggest-card" onClick={() => onPick(s.label)}>
            <span className="suggest-icon">{s.icon}</span>
            <span className="suggest-body">
              <span className="suggest-label">{s.label}</span>
              <span className="suggest-hint">{s.hint}</span>
            </span>
            <span className="suggest-arrow">→</span>
          </button>
        ))}
      </div>
    </div>
  )
}
