import type { Conversation, UserInfo, View } from '../App'

type SidebarProps = {
  conversations: Conversation[]
  activeId: number
  user: UserInfo
  open: boolean
  view: View
  onSelect: (id: number) => void
  onNew: () => void
  onDelete: (id: number) => void
  onNavigate: (view: View) => void
  onClose: () => void
}

// 侧边栏：Logo · 新建对话 · 我的订单/售后 · 历史对话 · 用户信息（含 VIP 状态）
export default function Sidebar({
  conversations,
  activeId,
  user,
  open,
  view,
  onSelect,
  onNew,
  onDelete,
  onNavigate,
  onClose,
}: SidebarProps) {
  const renderItem = (c: Conversation) => (
    <div
      key={c.id}
      className={`conv-item${view === 'chat' && c.id === activeId ? ' active' : ''}`}
      onClick={() => onSelect(c.id)}
    >
      <span className="conv-dot" />
      <span className="conv-body">
        <span className="conv-title">{c.title}</span>
        <span className="conv-preview">{c.preview}</span>
      </span>
      <span className="conv-time">{c.time}</span>
      <button
        type="button"
        className="conv-delete"
        aria-label="删除对话"
        title="删除对话"
        onClick={(event) => {
          event.stopPropagation()
          onDelete(c.id)
        }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path
            d="M6 7h12M9 7V5h6v2m-7 0v12a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V7M10 11v6M14 11v6"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </div>
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

        {/* 快捷入口：我的订单 / 我的售后 */}
        <div className="nav-group">
          <button
            type="button"
            className={`nav-item${view === 'orders' ? ' active' : ''}`}
            onClick={() => onNavigate('orders')}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path
                d="M6 4h9l4 4v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
              <path d="M9 12h6M9 16h6M9 8h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            我的订单
          </button>
          <button
            type="button"
            className={`nav-item${view === 'aftersales' ? ' active' : ''}`}
            onClick={() => onNavigate('aftersales')}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 3 5 6v5c0 4 3 7 7 9 4-2 7-5 7-9V6l-7-3Z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
              <path d="m9 11 2 2 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            我的售后
          </button>
        </div>

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
