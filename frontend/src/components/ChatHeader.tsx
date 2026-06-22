import type { UserInfo } from '../App'

type ChatHeaderProps = {
  title: string
  user: UserInfo
  onMenu: () => void
  onLogout: () => void
}

// 对话区顶栏：菜单（移动端）· 当前会话 · 在线状态 · 账号操作
export default function ChatHeader({ title, user, onMenu, onLogout }: ChatHeaderProps) {
  return (
    <header className="header">
      <button className="menu-btn" onClick={onMenu} aria-label="打开菜单">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>

      <div className="header-title">
        <span className="header-name">{title}</span>
        <span className="header-sub">
          <span className="status-dot" />
          阿数 在线
        </span>
      </div>

      <div className="header-spacer" />

      <div className="header-user">
        <span className="header-user-name">Hi，{user.name}</span>
        <span className="header-vip">{user.vipLevel}</span>
      </div>

      <button className="btn-logout" onClick={onLogout}>
        退出
      </button>
    </header>
  )
}
