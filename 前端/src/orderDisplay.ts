// 订单 / 售后的状态文案与格式化工具，供「我的订单」「我的售后」页面共用。
import type { AfterSale, Order } from './api'

// 语义色调：用于给状态徽章上不同颜色（见 global.css 的 .tag-* 类）
export type Tone = 'neutral' | 'brand' | 'success' | 'warn' | 'danger'

const ORDER_STATUS: Record<number, { label: string; tone: Tone }> = {
  0: { label: '待付款', tone: 'warn' },
  1: { label: '待发货', tone: 'brand' },
  2: { label: '待收货', tone: 'brand' },
  3: { label: '已完成', tone: 'success' },
  4: { label: '已取消', tone: 'neutral' },
}

const PAY_STATUS: Record<number, { label: string; tone: Tone }> = {
  0: { label: '未付款', tone: 'warn' },
  1: { label: '已付款', tone: 'success' },
  2: { label: '已退款', tone: 'neutral' },
}

const LOGISTICS_STATUS: Record<number, { label: string; tone: Tone }> = {
  0: { label: '待发货', tone: 'warn' },
  1: { label: '已发货', tone: 'brand' },
  2: { label: '运输中', tone: 'brand' },
  3: { label: '已签收', tone: 'success' },
  4: { label: '物流异常', tone: 'danger' },
}

const AFTER_SALE_TYPE: Record<number, string> = {
  1: '退货退款',
  2: '换货',
  3: '仅退款',
  4: '维修',
}

const AFTER_SALE_STATUS: Record<number, { label: string; tone: Tone }> = {
  0: { label: '待审核', tone: 'warn' },
  1: { label: '已通过', tone: 'success' },
  2: { label: '已拒绝', tone: 'danger' },
  3: { label: '处理中', tone: 'brand' },
  4: { label: '已完成', tone: 'success' },
}

const fallback = (label: string): { label: string; tone: Tone } => ({ label, tone: 'neutral' })

export const orderStatusInfo = (status: number) => ORDER_STATUS[status] ?? fallback('未知状态')
export const payStatusInfo = (status: number) => PAY_STATUS[status] ?? fallback('未知')
export const logisticsStatusInfo = (status: number) => LOGISTICS_STATUS[status] ?? fallback('未知')
export const afterSaleTypeLabel = (type: number) => AFTER_SALE_TYPE[type] ?? '其他'
export const afterSaleStatusInfo = (status: number) => AFTER_SALE_STATUS[status] ?? fallback('未知状态')

// 金额：兼容字符串 / 数字，统一千分位展示，无效值回退为 '0.00'
export const formatMoney = (value: string | number | undefined | null): string => {
  if (value == null || value === '') return '0.00'
  const num = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(num)) return String(value)
  return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// 时间：把后端 ISO 字符串裁成 "YYYY-MM-DD HH:mm"，无法解析时原样返回
export const formatDateTime = (value: string | undefined | null): string => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

// 订单标题：取首个商品名，多个商品追加 "等 N 件"
export const orderSummaryTitle = (order: Order): string => {
  const items = order.items ?? []
  if (!items.length) return `订单 ${order.orderNo}`
  const first = items[0].productName || '商品'
  const totalQty = items.reduce((sum, item) => sum + (Number(item.quantity) || 0), 0)
  return items.length > 1 || totalQty > 1 ? `${first} 等 ${totalQty} 件` : first
}

// 售后标题
export const afterSaleTitle = (afterSale: AfterSale): string =>
  `${afterSaleTypeLabel(afterSale.type)} · ${afterSale.orderNo}`
