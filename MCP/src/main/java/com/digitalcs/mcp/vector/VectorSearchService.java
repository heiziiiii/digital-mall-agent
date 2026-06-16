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

    /** metadata 字段：标记数据类型（商品详情 / 售后知识），随 payload 写入仅作溯源，检索分区已由集合承担 */
    public static final String TYPE = "type";
    /** metadata 字段：业务主键（商品=productNo，知识=自增序号） */
    public static final String BIZ_ID = "bizId";
    public static final String TYPE_PRODUCT = "product";
    public static final String TYPE_KNOWLEDGE = "knowledge";

    /** 命名向量：dense=DashScope 语义向量，sparse=jieba 词频关键词向量 */
    private static final String DENSE = "dense";
    private static final String SPARSE = "sparse";
    /** DashScope text-embedding-v3 维度 */
    private static final long DENSE_DIM = 1024L;

    private final QdrantClient qdrantClient;
    private final EmbeddingModel embeddingModel;
    private final SparseVectorizer sparseVectorizer;

    /** 商品详情集合名 */
    @org.springframework.beans.factory.annotation.Value("${app.qdrant.product-collection:digital_cs_products}")
    private final String productCollection;

    /** 售后知识集合名 */
    @org.springframework.beans.factory.annotation.Value("${app.qdrant.knowledge-collection:digital_cs_knowledge}")
    private final String knowledgeCollection;

    /** DashScope 嵌入 API Key：未配置或以 sk-dummy 开头时视为「无可用嵌入模型」，dense 侧关闭。 */
    @org.springframework.beans.factory.annotation.Value("${spring.ai.dashscope.api-key:}")
    private final String dashScopeApiKey;

    /** type → 对应集合：商品与知识各自独立 collection，集合即分区，不再共用、不再靠 payload.type 过滤。 */
    private String collectionOf(String type) {
        return TYPE_KNOWLEDGE.equals(type) ? knowledgeCollection : productCollection;
    }

    /** 嵌入模型是否可用：未配置真实 key 时关闭 dense 侧，避免空转调用 DashScope 触发 401 重试。 */
    private boolean embeddingEnabled() {
        return StringUtils.hasText(dashScopeApiKey) && !dashScopeApiKey.startsWith("sk-dummy");
    }

    /** 商品 + 知识两个集合均按需创建（不存在才建）。供灌库前调用，失败仅记日志。 */
    public void ensureCollections() {
        ensureCollection(productCollection);
        ensureCollection(knowledgeCollection);
    }

    /** 单个集合不存在则创建：dense(1024/COSINE) + sparse(IDF) 双命名向量。失败仅记日志。 */
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

    /** 删除商品 + 知识两个集合(连同全部点)；用于重置，重灌前由 ensureCollections 重建。失败仅记日志。 */
    public void deleteCollections() {
        deleteCollection(productCollection);
        deleteCollection(knowledgeCollection);
    }

    /** 删除单个集合(连同全部点)；集合不存在或不可用时仅记日志，不抛错。 */
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

    /** 统计某类型(product/knowledge)所在集合的向量点数；Qdrant 不可用时抛出由调用方处理。供启动自动灌库判断是否已加载。 */
    public long count(String type) throws Exception {
        return qdrantClient.countAsync(collectionOf(type)).get();
    }

    /** 按类型混合检索，返回命中的 Document（含 payload metadata），按 RRF 融合分排序；不可用时返回空。 */
    public List<Document> search(String type, String query, int topK) {
        return search(type, query, topK, null);
    }

    /**
     * 按类型混合检索，支持附加 payload 等值过滤（如 category/brand）。
     * query 为空时退化为「纯过滤浏览」（无向量查询，仅按过滤条件返回；无过滤条件则返回集合内任意 topK 条）。不可用时返回空。
     */
    public List<Document> search(String type, String query, int topK, Map<String, String> equalsFilters) {
        String collectionName = collectionOf(type);
        // 集合即分区，无需 type 过滤；仅按业务等值条件下推
        Filter.Builder fb = Filter.newBuilder();
        if (equalsFilters != null) {
            equalsFilters.forEach((k, v) -> {
                if (StringUtils.hasText(v)) {
                    fb.addMust(matchKeyword(k, v));
                }
            });
        }
        Filter filter = fb.build();

        // query 为空：仅按类目/品牌等过滤浏览（无向量打分）
        if (!StringUtils.hasText(query)) {
            return filterOnly(collectionName, filter, topK);
        }

        QueryPoints.Builder qb = QueryPoints.newBuilder()
                .setCollectionName(collectionName)
                .setQuery(fusion(Fusion.RRF))
                .setLimit(topK)
                .setWithPayload(enable(true));

        boolean hasSignal = false;
        // sparse 关键词通道：query 切词非空即下发（嵌入不可用时这是唯一通道 → 纯关键词检索）
        SparseVectorizer.Sparse sp = sparseVectorizer.toSparse(query);
        if (!sp.isEmpty()) {
            qb.addPrefetch(PrefetchQuery.newBuilder()
                    .setQuery(nearest(sp.values(), sp.indices()))
                    .setUsing(SPARSE).setFilter(filter).setLimit(topK * 4L).build());
            hasSignal = true;
        }
        // dense 语义通道：仅在嵌入模型可用时下发
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

    /** 纯过滤浏览：无向量查询，仅按 filter 返回最多 topK 条（用于 query 为空、仅按类目/品牌筛选）。 */
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

    /** 按业务主键取单条 Document（用于按 productNo 取商品详情）；未命中或不可用时返回 null。 */
    public Document fetchByBizId(String type, String bizId) {
        if (!StringUtils.hasText(bizId)) {
            return null;
        }
        try {
            // 纯 payload 过滤（无向量查询）取首条；集合已按类型分区，仅需匹配 bizId
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

    /** ScoredPoint 的 payload(Map<String,Value>) → Document（text 取标题/名称占位，业务字段进 metadata）。 */
    private Document toDocument(Map<String, Value> payloadMap) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        payloadMap.forEach((k, v) -> metadata.put(k, fromValue(v)));
        Object text = metadata.getOrDefault("title", metadata.getOrDefault("name", metadata.get(BIZ_ID)));
        return Document.builder()
                .text(text == null ? "-" : String.valueOf(text))
                .metadata(metadata)
                .build();
    }

    /** Qdrant Value → Java 对象（payload 全部以字符串写入，少量数值/布尔做兜底）。 */
    private Object fromValue(Value v) {
        return switch (v.getKindCase()) {
            case STRING_VALUE -> v.getStringValue();
            case INTEGER_VALUE -> v.getIntegerValue();
            case DOUBLE_VALUE -> v.getDoubleValue();
            case BOOL_VALUE -> v.getBoolValue();
            default -> "";
        };
    }

    /** type:bizId 派生稳定 UUID 作为 point id，保证重灌库覆盖同一条而非新增。 */
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

    /** 一条待写入向量库的记录。 */
    public record Record(String bizId, String text, Map<String, Object> payload) {
    }
}
