import type { ProductData } from '../App'

type ProductCardProps = {
  data: ProductData
}

// 库存紧张/无货时高亮提示
const isLowStock = (status: string) => /紧张|无货|缺货|售罄|仅剩/.test(status)

// 价格可能是 "6899" / "¥6899" / "" 等多种形态，统一去掉符号只留数值部分（¥ 由展示层补）
const formatPrice = (price: string): string | null => {
  const text = price.trim().replace(/^¥/, '')
  return text || null
}

// 内嵌商品卡：名称 / 卖点 / 实时价格 / 库存 / 推荐理由（数据均来自后端产品 Agent）
export default function ProductCard({ data }: ProductCardProps) {
  const price = formatPrice(data.price)
  const low = isLowStock(data.stockStatus)

  return (
    <div className="product-card">
      <div className="product-media">
        {data.stockStatus && <span className="product-tag">{data.stockStatus}</span>}
        <div className="product-phone" />
      </div>
      <div className="product-body">
        <div className="product-name">{data.name}</div>

        {data.highlights.length > 0 && (
          <div className="product-specs">
            {data.highlights.map((spec) => (
              <span key={spec} className="spec-chip">
                {spec}
              </span>
            ))}
          </div>
        )}

        {data.reason && <div className="product-reason">{data.reason}</div>}

        <div className="product-foot">
          <div className="product-price">
            {price ? (
              <>
                <span className="cur">¥</span>
                <b>{price}</b>
              </>
            ) : (
              <span className="price-na">价格以详情为准</span>
            )}
          </div>
          {data.stockStatus && (
            <span className={`product-stock${low ? ' low' : ''}`}>{data.stockStatus}</span>
          )}
        </div>

        <div className="product-actions">
          <button className="btn btn-primary">立即下单</button>
          <button className="btn btn-outline">查看详情</button>
        </div>
      </div>
    </div>
  )
}
