import { describe, expect, it } from 'vitest'
import { cleanSummary, historySubtitle, historyTitle } from './historyDisplay'

describe('历史对话展示文案', () => {
  it('清理滚动摘要中的统计和编号前缀', () => {
    const summary = '共2条：①换货单AS202606030001正在处理中；②用户想了解退款进度'

    expect(cleanSummary(summary)).toBe('换货单AS202606030001正在处理中；用户想了解退款进度')
    expect(historyTitle({ sessionId: 's1', rollingSummary: summary }, 0)).toBe('换货单 AS202606030001')
    expect(historySubtitle({ sessionId: 's1', rollingSummary: summary })).toBe(
      '换货单AS202606030001正在处理中；用户想了解退款进度',
    )
  })

  it('没有摘要时使用稳定兜底标题', () => {
    expect(historyTitle({ sessionId: 's1' }, 1)).toBe('对话 2')
    expect(historySubtitle({ sessionId: 's1' })).toBe('历史对话')
  })
})
