package com.digitalcs.mcp.vector;

import io.qdrant.client.QdrantClient;
import io.qdrant.client.grpc.Collections.CreateCollection;
import io.qdrant.client.grpc.Collections.Distance;
import io.qdrant.client.grpc.Collections.Modifier;
import io.qdrant.client.grpc.Collections.SparseVectorConfig;
import io.qdrant.client.grpc.Collections.SparseVectorParams;
import io.qdrant.client.grpc.Collections.VectorParams;
import io.qdrant.client.grpc.Collections.VectorParamsMap;
import io.qdrant.client.grpc.Collections.VectorsConfig;
import io.qdrant.client.grpc.JsonWithInt.Value;
import io.qdrant.client.grpc.Points.Filter;
import io.qdrant.client.grpc.Points.Fusion;
import io.qdrant.client.grpc.Points.PointStruct;
import io.qdrant.client.grpc.Points.PrefetchQuery;
import io.qdrant.client.grpc.Points.QueryPoints;
import io.qdrant.client.grpc.Points.ScoredPoint;
import io.qdrant.client.grpc.Points.Vector;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static io.qdrant.client.ConditionFactory.matchKeyword;
import static io.qdrant.client.PointIdFactory.id;
import static io.qdrant.client.QueryFactory.fusion;
import static io.qdrant.client.QueryFactory.nearest;
import static io.qdrant.client.ValueFactory.value;
import static io.qdrant.client.VectorFactory.vector;
import static io.qdrant.client.VectorsFactory.namedVectors;
import static io.qdrant.client.WithPayloadSelectorFactory.enable;

/**
 * Qdrant 混合检索封装（sparse 关键词 + dense 语义，服务端 RRF 融合）。全项目唯一检索入口，直连原生
 * {@link QdrantClient}（Spring AI VectorStore 不支持混合检索）。商品详情与售后知识分库存储——各自独立
 * collection（{@code productCollection} / {@code knowledgeCollection}），由 type 映射到对应集合，集合本身
 * 即是数据分区，无需再靠 payload.type 过滤；payload 直接携带业务字段，检索结果即完整数据（知识库无需回 MySQL）。
 * Qdrant 不可用时降级为返回空 / 写入跳过；嵌入模型不可用时退化为纯 sparse 关键词检索。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class VectorSearchService {

    public static final String TYPE = "type";
    public static final String BIZ_ID = "bizId";
    public static final String TYPE_PRODUCT = "product";
    public static final String TYPE_KNOWLEDGE = "knowledge";

    private static final String DENSE = "dense";
    private static final String SPARSE = "sparse";
    private static final long DENSE_DIM = 1024L;

    private final QdrantClient qdrantClient;
    private final EmbeddingModel embeddingModel;
    private final SparseVectorizer sparseVectorizer;

    @org.springframework.beans.factory.annotation.Value("${app.qdrant.product-collection:digital_cs_products}")
    private final String productCollection;

    @org.springframework.beans.factory.annotation.Value("${app.qdrant.knowledge-collection:digital_cs_knowledge}")
    private final String knowledgeCollection;

    /** DashScope 嵌入 API Key：未配置或以 sk-dummy 开头时视为「无可用嵌入模型」，dense 侧关闭。 */
    @org.springframework.beans.factory.annotation.Value("${spring.ai.dashscope.api-key:}")
    private final String dashScopeApiKey;

    private String collectionOf(String type) {
        return TYPE_KNOWLEDGE.equals(type) ? knowledgeCollection : productCollection;
    }

    /** 嵌入模型是否可用：未配置真实 key 时关闭 dense 侧，避免空转调用 DashScope 触发 401 重试。 */
    private boolean embeddingEnabled() {
        return StringUtils.hasText(dashScopeApiKey) && !dashScopeApiKey.startsWith("sk-dummy");
    }

    public void ensureCollections() {
        ensureCollection(productCollection);
        ensureCollection(knowledgeCollection);
    }

    private void ensureCollection(String collectionName) {
        try {
            if (Boolean.TRUE.equals(qdrantClient.collectionExistsAsync(collectionName).get())) {
                return;
            }
            VectorsConfig dense = VectorsConfig.newBuilder()
                    .setParamsMap(VectorParamsMap.newBuilder().putMap(DENSE, VectorParams.newBuilder()
                            .setSize(DENSE_DIM).setDistance(Distance.Cosine).build()))
                    .build();
            SparseVectorConfig sparse = SparseVectorConfig.newBuilder()
                    .putMap(SPARSE, SparseVectorParams.newBuilder().setModifier(Modifier.Idf).build())
                    .build();
            qdrantClient.createCollectionAsync(CreateCollection.newBuilder()
                    .setCollectionName(collectionName)
                    .setVectorsConfig(dense)
                    .setSparseVectorsConfig(sparse)
                    .build()).get();
            log.info("已创建 Qdrant 集合 {}（dense+sparse 命名向量）", collectionName);
        } catch (Exception e) {
            Thread.currentThread().interrupt();
            log.warn("Qdrant 集合创建失败: {}", e.getMessage());
        }
    }

    public void deleteCollections() {
        deleteCollection(productCollection);
        deleteCollection(knowledgeCollection);
    }

    private void deleteCollection(String collectionName) {
        try {
            if (Boolean.TRUE.equals(qdrantClient.collectionExistsAsync(collectionName).get())) {
                qdrantClient.deleteCollectionAsync(collectionName).get();
                log.info("已删除 Qdrant 集合 {}", collectionName);
            }
        } catch (Exception e) {
            Thread.currentThread().interrupt();
            log.warn("Qdrant 集合删除失败: {}", e.getMessage());
        }
    }

    public long count(String type) throws Exception {
        return qdrantClient.countAsync(collectionOf(type)).get();
    }

    public List<Document> search(String type, String query, int topK) {
        return search(type, query, topK, null);
    }

    /**
     * 按类型混合检索，支持附加 payload 等值过滤（如 category/brand）。
     * query 为空时退化为「纯过滤浏览」（无向量查询，仅按过滤条件返回；无过滤条件则返回集合内任意 topK 条）。不可用时返回空。
     */
    public List<Document> search(String type, String query, int topK, Map<String, String> equalsFilters) {
        String collectionName = collectionOf(type);
        Filter.Builder fb = Filter.newBuilder();
        if (equalsFilters != null) {
            equalsFilters.forEach((k, v) -> {
                if (StringUtils.hasText(v)) {
                    fb.addMust(matchKeyword(k, v));
                }
            });
        }
        Filter filter = fb.build();

        if (!StringUtils.hasText(query)) {
            return filterOnly(collectionName, filter, topK);
        }

        QueryPoints.Builder qb = QueryPoints.newBuilder()
                .setCollectionName(collectionName)
                .setQuery(fusion(Fusion.RRF))
                .setLimit(topK)
                .setWithPayload(enable(true));

        boolean hasSignal = false;
        SparseVectorizer.Sparse sp = sparseVectorizer.toSparse(query);
        if (!sp.isEmpty()) {
            qb.addPrefetch(PrefetchQuery.newBuilder()
                    .setQuery(nearest(sp.values(), sp.indices()))
                    .setUsing(SPARSE).setFilter(filter).setLimit(topK * 4L).build());
            hasSignal = true;
        }
        if (embeddingEnabled()) {
            qb.addPrefetch(PrefetchQuery.newBuilder()
                    .setQuery(nearest(toFloatList(embeddingModel.embed(query))))
                    .setUsing(DENSE).setFilter(filter).setLimit(topK * 4L).build());
            hasSignal = true;
        }
        if (!hasSignal) {
            return List.of();
        }
        try {
            List<ScoredPoint> points = qdrantClient.queryAsync(qb.build()).get();
            return points.stream().map(p -> toDocument(p.getPayloadMap())).toList();
        } catch (Exception e) {
            Thread.currentThread().interrupt();
            log.warn("Qdrant 检索不可用: {}", e.getMessage());
            return List.of();
        }
    }

    private List<Document> filterOnly(String collectionName, Filter filter, int topK) {
        try {
            List<ScoredPoint> points = qdrantClient.queryAsync(QueryPoints.newBuilder()
                    .setCollectionName(collectionName)
                    .setFilter(filter)
                    .setLimit(topK)
                    .setWithPayload(enable(true))
                    .build()).get();
            return points.stream().map(p -> toDocument(p.getPayloadMap())).toList();
        } catch (Exception e) {
            Thread.currentThread().interrupt();
            log.warn("Qdrant 过滤浏览不可用: {}", e.getMessage());
            return List.of();
        }
    }

    public Document fetchByBizId(String type, String bizId) {
        if (!StringUtils.hasText(bizId)) {
            return null;
        }
        try {
            List<ScoredPoint> points = qdrantClient.queryAsync(QueryPoints.newBuilder()
                    .setCollectionName(collectionOf(type))
                    .setFilter(Filter.newBuilder()
                            .addMust(matchKeyword(BIZ_ID, bizId)).build())
                    .setLimit(1)
                    .setWithPayload(enable(true))
                    .build()).get();
            return points.isEmpty() ? null : toDocument(points.get(0).getPayloadMap());
        } catch (Exception e) {
            Thread.currentThread().interrupt();
            log.warn("Qdrant 按主键取详情不可用: {}", e.getMessage());
            return null;
        }
    }

    /**
     * 全量写入向量到类型对应集合，返回写入条数；不可用时返回 0。每条写 sparse（恒有）+ dense（嵌入可用时）。
     * @param type  数据类型（product / knowledge），决定写入哪个集合
     * @param items 每条记录：bizId=业务主键，text=待嵌入/切词文本，payload=随结果返回的业务字段
     */
    public int index(String type, List<Record> items) {
        if (items.isEmpty()) {
            return 0;
        }
        try {
            boolean dense = embeddingEnabled();
            List<PointStruct> points = new ArrayList<>(items.size());
            for (Record r : items) {
                Map<String, Vector> vectors = new LinkedHashMap<>();
                if (dense) {
                    vectors.put(DENSE, vector(toFloatList(embeddingModel.embed(r.text()))));
                }
                SparseVectorizer.Sparse sp = sparseVectorizer.toSparse(r.text());
                if (!sp.isEmpty()) {
                    vectors.put(SPARSE, vector(sp.values(), sp.indices()));
                }
                if (vectors.isEmpty()) {
                    continue;
                }
                Map<String, Value> payload = new LinkedHashMap<>();
                r.payload().forEach((k, v) -> payload.put(k, value(String.valueOf(v))));
                payload.put(TYPE, value(type));
                payload.put(BIZ_ID, value(r.bizId()));
                points.add(PointStruct.newBuilder()
                        .setId(id(stableUuid(type, r.bizId())))
                        .setVectors(namedVectors(vectors))
                        .putAllPayload(payload)
                        .build());
            }
            if (points.isEmpty()) {
                return 0;
            }
            qdrantClient.upsertAsync(collectionOf(type), points).get();
            return points.size();
        } catch (Exception e) {
            Thread.currentThread().interrupt();
            log.warn("Qdrant 向量写入失败，已跳过: {}", e.getMessage());
            return 0;
        }
    }

    private Document toDocument(Map<String, Value> payloadMap) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        payloadMap.forEach((k, v) -> metadata.put(k, fromValue(v)));
        Object text = metadata.getOrDefault("title", metadata.getOrDefault("name", metadata.get(BIZ_ID)));
        return Document.builder()
                .text(text == null ? "-" : String.valueOf(text))
                .metadata(metadata)
                .build();
    }

    private Object fromValue(Value v) {
        return switch (v.getKindCase()) {
            case STRING_VALUE -> v.getStringValue();
            case INTEGER_VALUE -> v.getIntegerValue();
            case DOUBLE_VALUE -> v.getDoubleValue();
            case BOOL_VALUE -> v.getBoolValue();
            default -> "";
        };
    }

    private UUID stableUuid(String type, String bizId) {
        return UUID.nameUUIDFromBytes((type + ":" + bizId).getBytes(StandardCharsets.UTF_8));
    }

    private static List<Float> toFloatList(float[] arr) {
        List<Float> list = new ArrayList<>(arr.length);
        for (float f : arr) {
            list.add(f);
        }
        return list;
    }

    public record Record(String bizId, String text, Map<String, Object> payload) {
    }
}
