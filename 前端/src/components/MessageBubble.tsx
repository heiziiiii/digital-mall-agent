import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ProductCard from './ProductCard'
import ReviewCard from './ReviewCard'
import type { Message, UserInfo } from '../App'

type MessageBubbleProps = {
  msg: Message
  user: UserInfo
  reviewBusy?: boolean
  onApproveReview?: (messageId: number, args: Record<string, unknown>) => void
  onCancelReview?: (messageId: number, message: string, regenerate?: boolean) => void
}

// 单条消息：根据 blocks 渲染文本 / 商品卡
export default function MessageBubble({
  msg,
  user,
  reviewBusy,
  onApproveReview,
  onCancelReview,
}: MessageBubbleProps) {
  const isUser = msg.role === 'user'

  return (
    <div className={`msg ${isUser ? 'user' : 'bot'}`}>
      <div className={`avatar ${isUser ? 'user' : 'bot'}`}>{isUser ? user.avatar : '数'}</div>
      <div className="bubble-wrap">
        {msg.blocks.map((block, index) => {
          if (block.type === 'text') {
            return (
              <div key={index} className={`bubble ${isUser ? 'user' : 'bot'}`}>
                {isUser ? (
                  block.value
                ) : (
                  <div className="markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.value}</ReactMarkdown>
                  </div>
                )}
              </div>
            )
          }

          if (block.type === 'product') return <ProductCard key={index} data={block.value} />

          if (block.type === 'review') {
            return (
              <ReviewCard
                key={index}
                action={block.value}
                busy={reviewBusy}
                onApprove={(args) => onApproveReview?.(msg.id, args)}
                onCancel={(message, regenerate) => onCancelReview?.(msg.id, message, regenerate)}
              />
            )
          }

          return null
        })}
        <span className="msg-meta">{isUser ? '已发送' : '阿数 · AI 客服'}</span>
      </div>
    </div>
  )
}
