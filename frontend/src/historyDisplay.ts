import type { HistorySession } from './api'

const LIST_MARKER_RE = /^(?:[①②③④⑤⑥⑦⑧⑨⑩]|\(?[一二三四五六七八九十\d]{1,2}\)?[、.)．])/

export const clipText = (text: string, max: number) => {
  const chars = Array.from(text)
  return chars.length > max ? `${chars.slice(0, max).join('')}...` : text
}

export const cleanSummary = (summary?: string) =>
  (summary ?? '')
    .replace(/\s+/g, ' ')
    .replace(/^用户[^，。；;:：]*[，。；;:：]\s*/, '')
    .replace(/^共\s*[一二三四五六七八九十\d]+\s*条\s*[：:，,、-]?\s*/, '')
    .replace(/[①②③④⑤⑥⑦⑧⑨⑩]/g, '；')
    .replace(/(?:^|[；;]\s*)\(?[一二三四五六七八九十\d]{1,2}\)?[、.)．]\s*/g, '；')
    .replace(/^[；;，,、\s]+/, '')
    .replace(/[；;，,、\s]+$/, '')
    .replace(/[；;]\s*[；;]+/g, '；')
    .trim()

const cleanTitleFragment = (text: string) =>
  text
    .replace(/^共\s*[一二三四五六七八九十\d]+\s*条\s*[：:，,、-]?\s*/, '')
    .replace(LIST_MARKER_RE, '')
    .replace(/^[：:，,、；;\s]+/, '')
    .trim()

const extractBusinessTitle = (summary: string) => {
  const afterSale = summary.match(/(换货单|退货单|退款单|维修单|售后单)?\s*(AS\d{8,})/i)
  if (afterSale) {
    const label = afterSale[1] || '售后单'
    return `${label} ${afterSale[2].toUpperCase()}`
  }

  const order = summary.match(/(订单|订单号)?\s*((?:ORD|ORDER|O)\d{6,})/i)
  if (order) {
    const label = order[1] || '订单'
    return `${label} ${order[2].toUpperCase()}`
  }

  return ''
}

export const historyTitle = (session: HistorySession, fallbackIndex: number) => {
  const summary = cleanSummary(session.rollingSummary)
  if (!summary) return `对话 ${fallbackIndex + 1}`

  const businessTitle = extractBusinessTitle(summary)
  if (businessTitle) return clipText(businessTitle, 18)

  const firstSentence = summary.split(/[。；;.!?！？]/).map(cleanTitleFragment).find(Boolean)
  return clipText(firstSentence || summary, 18)
}

export const historySubtitle = (session: HistorySession) => {
  const summary = cleanSummary(session.rollingSummary)
  return summary ? clipText(summary, 32) : '历史对话'
}
