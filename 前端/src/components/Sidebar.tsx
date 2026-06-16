import type { Conversation, UserInfo } from '../App'

type SidebarProps = {
  conversations: Conversation[]
  activeId: number
  user: UserInfo
  open: boolean
  onSelect: (id: number) => void
  onNew: () => void
  onClose: () => void
}

// 侧边栏：Logo · 新建对话 · 历史对话 · 用户信息（含 VIP 状态）
export default function Sidebar({
  conversations,
  activeId,
  user,
  open,
  onSelect,
  onNew,
  onClose,
}: SidebarProps) {
  const renderItem = (c: Conversation) => (
    <button
      key={c.id}
      className={`conv-item${c.id === activeId ? ' active' : ''}`}
      onClick={() => onSelect(c.id)}
    >
      <span className="conv-dot" />
      <span className="conv-body">
        <span className="conv-title">{c.title}</span>
        <span className="conv-preview">{c.preview}</span>
      </span>
      <span className="conv-time">{c.time}</span>
    </button>
  )

  return (
    <>
      <div className={`sidebar-scrim${open ? ' show' : ''}`} onClick={onClose} />
      <aside className={`sidebar${open ? ' open' : ''}`}>
        {/* Logo 区域 */}
        <div className="brand">
          <div className="brand-mark">数</div>
          <div className="brand-text">
            <span className="brand-name">阿数</span>
            <span className="brand-sub">AI 智能客服</span>
          </div>
        </div>

        {/* 新建对话 */}
        <button className="new-chat" onClick={onNew}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 5v14M5 12h14"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
            />
          </svg>
          新建对话
        </button>

        {/* 历史对话 */}
        <div className="conv-scroll">
          <div className="conv-group">
            <div className="conv-label">历史对话</div>
            {conversations.map(renderItem)}
          </div>
        </div>

        {/* 用户信息 + VIP 状态 */}
        <div className="user-card">
          <div className="user-avatar">{user.avatar}</div>
          <div className="user-meta">
            <div className="user-name-row">
              <span className="user-name">{user.name}</span>
              <span className="vip-badge">{user.vipTag}</span>
            </div>
            <span className="user-level">{user.vipLevel} · {user.customerNo}</span>
          </div>
          <button className="user-more" aria-label="账户设置">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="5" cy="12" r="2" />
              <circle cx="12" cy="12" r="2" />
              <circle cx="19" cy="12" r="2" />
            </svg>
          </button>
        </div>
      </aside>
    </>
  )
}
