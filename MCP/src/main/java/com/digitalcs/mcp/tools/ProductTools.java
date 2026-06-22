package com.digitalcs.mcp.tools;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import com.digitalcs.mcp.service.ProductService;
import com.digitalcs.mcp.service.ProductSortBy;

import lombok.RequiredArgsConstructor;

@Component
@RequiredArgsConstructor
public class ProductTools {

    private final ProductService productService;

    @Tool(description = "按客户需求检索本店数码商品，支持目标商品短语、类目、品牌、预算和排序。适合找商品、推荐商品、筛选或对比候选款；客户已明确某个商品编号并追问价格、库存或规格时，改用 getProductDetail。")
    public List<Map<String, Object>> searchProducts(
            @ToolParam(description = "面向 RAG/向量检索的目标商品短语，描述用户期待的机型或产品，如 '三星高端旗舰手机'、'华为长续航手机'、'苹果大存储手机'；不要写 '用户想找'、'优先推荐' 这类指导性话语", required = false) String query,
            @ToolParam(description = "类目过滤，需与商品类目一致，如 '手机'、'笔记本电脑'", required = false) String category,
            @ToolParam(description = "品牌过滤，如 '华为'、'苹果'、'小米'", required = false) String brand,
            @ToolParam(description = "最低价格(元)，含此价", required = false) Double minPrice,
            @ToolParam(description = "最高价格(元)，含此价", required = false) Double maxPrice,
            @ToolParam(description = "排序方式：relevance 相关度/price_asc 价格升序/price_desc 价格降序/stock_desc 库存降序/newest 发布时间最近。不传时：有 query 按相关度，无 query 按发布时间最近", required = false) ProductSortBy sortBy,
            @ToolParam(description = "返回数量上限，默认 10", required = false) Integer limit) {
        return productService.search(query, category, brand,
                toPrice(minPrice), toPrice(maxPrice), sortBy, limit == null ? 10 : limit);
    }

    private static BigDecimal toPrice(Double v) {
        return v == null ? null : BigDecimal.valueOf(v);
    }

    @Tool(description = "查询指定商品的价格、库存、品牌、类目和规格等详情。适合客户已明确商品编号后追问多少钱、有没有货、参数如何；如果客户只是模糊描述想买什么，先用 searchProducts 找候选。")
    public Map<String, Object> getProductDetail(
            @ToolParam(description = "商品编号(product_no)") String productNo) {
        return productService.getDetail(productNo);
    }
}
