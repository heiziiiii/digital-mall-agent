package com.digitalcs.mcp.service;

/**
 * 商品搜索排序方式（即面向 LLM 的枚举契约）。
 * 仅按已有数据设计：销量/评分无数据来源，故以库存降序替代；价格/发布时间存于 Qdrant payload。
 */
public enum ProductSortBy {
    /** 检索相关度：保持混合检索 RRF 融合顺序（有 query 时的默认） */
    relevance,
    /** 价格升序 */
    price_asc,
    /** 价格降序 */
    price_desc,
    /** 库存降序：货源充足优先 */
    stock_desc,
    /** 发布时间最近优先（无任何参数时的默认） */
    newest
}
