import { useRef } from 'react'

type ComposerProps = {
  value: string
  disabled?: boolean
  onChange: (value: string) => void
  onSend: () => void
  onQuick: (quickReply: string) => void
}

const QUICK = ['🛍️ 推荐产品', '📦 查看订单', '🛠️ 售后服务', '🧩 技术问题']

export default function Composer({ value, disabled, onChange, onSend, onQuick }: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement | null>(null)

  const autoGrow = (element: HTMLTextAreaElement) => {
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 140)}px`
  }

  const handleKey = (event: import('react').KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSend()
    }
  }

  return (
    <div className="composer-wrap">
      <div className="quick-replies">
        {QUICK.map((quickReply) => (
          <button key={quickReply} className="chip" onClick={() => onQuick(quickReply)} disabled={disabled}>
            {quickReply}
          </button>
        ))}
      </div>
      <div className="composer">
        <textarea
          ref={ref}
          rows={1}
          value={value}
          placeholder='说说您的需求，例如「预算 4000 想要拍照好、续航久的」或「查一下我的订单」'
          disabled={disabled}
          onChange={(event) => {
            onChange(event.target.value)
            autoGrow(event.target)
          }}
          onKeyDown={handleKey}
        />
        <button className="send-btn" onClick={onSend} disabled={disabled || !value.trim()} aria-label="发送">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M4 12l16-8-6 8 6 8-16-8z" fill="currentColor" />
          </svg>
        </button>
      </div>
      <div className="composer-note">由阿数 AI 智能客服提供 · 关键操作将与你确认后执行</div>
    </div>
  )
}
