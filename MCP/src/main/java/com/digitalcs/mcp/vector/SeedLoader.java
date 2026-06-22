package com.digitalcs.mcp.vector;

import com.digitalcs.mcp.vector.VectorSearchService.Record;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import javax.sql.DataSource;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 种子数据灌库：种子文件统一放 classpath seed/ 下——seed/mysql.sql(MySQL 权威库)、
 * seed/products.json、seed/knowledge.json(Qdrant 商品详情 / 售后知识)。
 * 启动时自动按需灌 Qdrant（{@link #run}）；/admin/reindex 重灌 Qdrant；/admin/reset 同时重置 MySQL+Qdrant。
 * Qdrant 的 index() 以 type:bizId 派生稳定 UUID 写入，故重灌仅覆盖同条不会产生重复点。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SeedLoader implements ApplicationRunner {

    private final VectorSearchService vectorSearchService;
    private final ObjectMapper objectMapper;
    private final DataSource dataSource;

    @Override
    public void run(ApplicationArguments args) {
        try {
            vectorSearchService.ensureCollections();
            loadIfAbsent(VectorSearchService.TYPE_PRODUCT, "商品详情", loadProducts());
            loadIfAbsent(VectorSearchService.TYPE_KNOWLEDGE, "售后知识", loadKnowledge());
        } catch (Exception e) {
            log.warn("启动自动灌库失败，已跳过（可稍后手动 POST /admin/reindex）: {}", e.getMessage());
        }
    }

    private void loadIfAbsent(String type, String label, List<Record> records) throws Exception {
        if (vectorSearchService.count(type) > 0) {
            log.info("启动自动灌库：{}已存在，跳过", label);
            return;
        }
        log.info("启动自动灌库：{}写入 {} 条", label, vectorSearchService.index(type, records));
    }

    /**
     * 全量重置：清空并重灌 MySQL + Qdrant，全部来自 seed 下种子文件。供 /admin/reset 调用。
     * MySQL 执行 seed/mysql.sql(TRUNCATE+INSERT)；Qdrant 删除集合后重建并重新灌入 JSON。
     */
    public Map<String, Object> reset() throws IOException {
        resetMysql();
        vectorSearchService.deleteCollections();
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("mysql", "reset from seed/mysql.sql");
        result.putAll(reindex());
        return result;
    }

    /** 执行 seed/mysql.sql 重置 MySQL 4 张表(清空+灌种子)；失败抛出由调用方处理(MySQL 为硬依赖)。 */
    private void resetMysql() {
        try (Connection conn = dataSource.getConnection()) {
            ensureCustomerPasswordColumn(conn);
            ScriptUtils.executeSqlScript(conn,
                    new EncodedResource(new ClassPathResource("seed/mysql.sql"), StandardCharsets.UTF_8));
        } catch (Exception e) {
            throw new IllegalStateException("MySQL 种子重置失败: " + e.getMessage(), e);
        }
    }

    private void ensureCustomerPasswordColumn(Connection conn) throws Exception {
        try (ResultSet rs = conn.getMetaData().getColumns(conn.getCatalog(), null, "customer", "password")) {
            if (rs.next()) {
                return;
            }
        }
        try (Statement stmt = conn.createStatement()) {
            stmt.execute("""
                    ALTER TABLE customer
                    ADD COLUMN password VARCHAR(128) NOT NULL DEFAULT '123456' COMMENT '登录密码(测试环境明文)' AFTER phone
                    """);
        }
    }

    public Map<String, Object> reindex() throws IOException {
        vectorSearchService.ensureCollections();
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("qdrantProducts",
                vectorSearchService.index(VectorSearchService.TYPE_PRODUCT, loadProducts()));
        result.put("qdrantKnowledge",
                vectorSearchService.index(VectorSearchService.TYPE_KNOWLEDGE, loadKnowledge()));
        return result;
    }

    /**
     * 商品详情：bizId=productNo，嵌入文本拼接名称/分类/品牌/标签/描述/规格（价格/发布时间不进嵌入文本，仅作过滤排序用）；
     * payload 保留全部详情字段 + price/marketPrice/publishedAt。
     */
    private List<Record> loadProducts() throws IOException {
        List<Record> records = new ArrayList<>();
        for (Map<String, Object> p : readArray("seed/products.json")) {
            String tags = str(p.get("tags"));
            String specs = str(p.get("specs"));
            String text = join(str(p.get("name")), str(p.get("subtitle")), str(p.get("category")),
                    str(p.get("brand")), tags, str(p.get("description")), specs);
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("name", str(p.get("name")));
            payload.put("subtitle", str(p.get("subtitle")));
            payload.put("category", str(p.get("category")));
            payload.put("brand", str(p.get("brand")));
            payload.put("tags", tags);
            payload.put("price", str(p.get("price")));
            payload.put("marketPrice", str(p.get("marketPrice")));
            payload.put("publishedAt", str(p.get("publishedAt")));
            payload.put("description", str(p.get("description")));
            payload.put("specs", specs);
            records.add(new Record(str(p.get("productNo")), text, payload));
        }
        return records;
    }

    private List<Record> loadKnowledge() throws IOException {
        List<Record> records = new ArrayList<>();
        List<Map<String, Object>> items = readArray("seed/knowledge.json");
        for (int i = 0; i < items.size(); i++) {
            Map<String, Object> k = items.get(i);
            String text = join(str(k.get("title")), str(k.get("content")), str(k.get("keywords")));
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("kbType", str(k.get("kbType")));
            payload.put("title", str(k.get("title")));
            payload.put("content", str(k.get("content")));
            payload.put("keywords", str(k.get("keywords")));
            records.add(new Record(String.valueOf(i + 1), text, payload));
        }
        return records;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> readArray(String path) throws IOException {
        try (InputStream in = new ClassPathResource(path).getInputStream()) {
            return objectMapper.readValue(in, List.class);
        }
    }

    /** specs 等非字符串字段统一序列化为 JSON 字符串，避免 Qdrant payload 存嵌套结构。 */
    private String str(Object o) {
        if (o == null) {
            return "";
        }
        if (o instanceof String s) {
            return s;
        }
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            return String.valueOf(o);
        }
    }

    private static String join(String... parts) {
        StringBuilder sb = new StringBuilder();
        for (String p : parts) {
            if (StringUtils.hasText(p)) {
                sb.append(p).append(' ');
            }
        }
        return sb.toString().trim();
    }
}
