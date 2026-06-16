package com.digitalcs.mcp.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.digitalcs.mcp.entity.Product;
import com.digitalcs.mcp.mapper.ProductMapper;
import com.digitalcs.mcp.vector.VectorSearchService;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.document.Document;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import static com.digitalcs.mcp.vector.VectorSearchService.BIZ_ID;
import static com.digitalcs.mcp.vector.VectorSearchService.TYPE_PRODUCT;

/**
 * 商品服务：详情/价格/发布时间走 Qdrant（语义检索 + payload），库存回 MySQL。
 * 搜索 = Qdrant 召回详情 → 按 productNo 批量补 MySQL 库存后合并返回。
 */
@Service
@RequiredArgsConstructor
public class ProductService {

    private final ProductMapper productMapper;
    private final VectorSearchService vectorSearchService;

    /**
     * 搜索/筛选商品：Qdrant 召回详情(支持 query 语义检索 + 类目/品牌过滤) → 回 MySQL 补价格库存 →
     * 按价格区间过滤 → 排序 → 截断至 limit。query 为空时退化为按类目/品牌/价格的纯筛选浏览。
     */
    public List<Map<String, Object>> search(String query, String category, String brand,
                                             BigDecimal minPrice, BigDecimal maxPrice,
                                             ProductSortBy sortBy, int limit) {
        // 未指定排序时：有关键词按相关度，无关键词(纯浏览)按发布时间最近优先。
        ProductSortBy sort = sortBy != null ? sortBy
                : (StringUtils.hasText(query) ? ProductSortBy.relevance : ProductSortBy.newest);
        // 价格过滤与排序在内存完成，需多召回候选；数据集小，给足上限即可。
        int pool = Math.max(limit * 4, 20);
        Map<String, String> filters = new LinkedHashMap<>();
        if (StringUtils.hasText(category)) {
            filters.put("category", category);
        }
        if (StringUtils.hasText(brand)) {
            filters.put("brand", brand);
        }

        List<Document> docs = vectorSearchService.search(TYPE_PRODUCT, query, pool, filters);
        if (docs.isEmpty()) {
            return List.of();
        }
        List<String> productNos = docs.stream()
                .map(d -> str(d.getMetadata().get(BIZ_ID)))
                .filter(s -> !s.isEmpty())
                .toList();
        Map<String, Product> stockByNo = productNos.isEmpty() ? Map.of() : productMapper.selectList(
                        new LambdaQueryWrapper<Product>().in(Product::getProductNo, productNos)).stream()
                .collect(Collectors.toMap(Product::getProductNo, Function.identity(), (a, b) -> a));

        List<Map<String, Object>> merged = docs.stream()
                .map(d -> merge(d, stockByNo.get(str(d.getMetadata().get(BIZ_ID)))))
                .filter(m -> priceInRange((BigDecimal) m.get("price"), minPrice, maxPrice))
                .collect(Collectors.toList());
        sortInPlace(merged, sort);
        return merged.size() > limit ? merged.subList(0, limit) : merged;
    }

    /** 价格区间判断；未指定区间则全通过，指定了区间但无价格数据则排除。 */
    private boolean priceInRange(BigDecimal price, BigDecimal min, BigDecimal max) {
        if (min == null && max == null) {
            return true;
        }
        if (price == null) {
            return false;
        }
        if (min != null && price.compareTo(min) < 0) {
            return false;
        }
        return max == null || price.compareTo(max) <= 0;
    }

    /** 按排序方式就地排序；relevance 保持 Qdrant 融合相关度顺序，无价格/库存数据排最后。 */
    private void sortInPlace(List<Map<String, Object>> items, ProductSortBy sort) {
        switch (sort) {
            case price_asc -> items.sort(Comparator.comparing(
                    m -> (BigDecimal) m.get("price"), Comparator.nullsLast(Comparator.naturalOrder())));
            case price_desc -> items.sort(Comparator.comparing(
                    m -> (BigDecimal) m.get("price"), Comparator.nullsLast(Comparator.reverseOrder())));
            case stock_desc -> items.sort(Comparator.comparing(
                    m -> (Integer) m.get("stock"), Comparator.nullsLast(Comparator.reverseOrder())));
            // publishedAt 为 ISO 日期串，字典序即时间序，倒序 = 最近优先
            case newest -> items.sort(Comparator.comparing(
                    m -> (String) m.get("publishedAt"), Comparator.nullsLast(Comparator.reverseOrder())));
            case relevance -> { /* 保持召回相关度顺序 */ }
        }
    }

    /** 按商品编号查询详情：Qdrant 详情/价格 + MySQL 库存合并；未找到返回 found=false。 */
    public Map<String, Object> getDetail(String productNo) {
        Product stock = findByNo(productNo);
        Document detail = vectorSearchService.fetchByBizId(TYPE_PRODUCT, productNo);
        if (stock == null && detail == null) {
            return Map.of("found", false, "message", "未找到商品: " + productNo);
        }
        Map<String, Object> result = merge(detail, stock);
        result.put("found", true);
        return result;
    }

    private Product findByNo(String productNo) {
        return productMapper.selectOne(
                new LambdaQueryWrapper<Product>().eq(Product::getProductNo, productNo));
    }

    /**
     * 把 Qdrant 详情 payload（含 price/marketPrice/publishedAt）与 MySQL 库存合并为面向 LLM 的 Map。
     * 价格在 payload 中以字符串存储，统一解析为 BigDecimal 便于过滤/排序与展示。
     */
    private Map<String, Object> merge(Document detail, Product stock) {
        Map<String, Object> m = new LinkedHashMap<>();
        if (detail != null) {
            detail.getMetadata().forEach((k, v) -> {
                if (VectorSearchService.TYPE.equals(k)) {
                    return;
                }
                String key = BIZ_ID.equals(k) ? "productNo" : k;
                m.put(key, ("price".equals(key) || "marketPrice".equals(key)) ? parsePrice(v) : v);
            });
        }
        if (stock != null) {
            m.put("productNo", stock.getProductNo());
            m.putIfAbsent("name", stock.getName());
            m.put("stock", stock.getStock());
            m.put("inStock", stock.getStock() != null && stock.getStock() > 0);
        }
        return m;
    }

    /** Qdrant payload 中的价格字符串 → BigDecimal；空或非法返回 null。 */
    private static BigDecimal parsePrice(Object v) {
        if (v == null) {
            return null;
        }
        String s = String.valueOf(v).trim();
        if (s.isEmpty()) {
            return null;
        }
        try {
            return new BigDecimal(s);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }
}
