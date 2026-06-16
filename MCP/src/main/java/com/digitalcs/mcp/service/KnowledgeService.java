package com.digitalcs.mcp.service;

import com.digitalcs.mcp.vector.VectorSearchService;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.document.Document;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.digitalcs.mcp.vector.VectorSearchService.TYPE;
import static com.digitalcs.mcp.vector.VectorSearchService.TYPE_KNOWLEDGE;

/**
 * 售后技术问题解决方案知识库检索：数据只存 Qdrant，检索结果直接取 payload 返回(title/content 等)，不回 MySQL。
 */
@Service
@RequiredArgsConstructor
public class KnowledgeService {

    private final VectorSearchService vectorSearchService;

    public Map<String, Object> search(String query, int topK) {
        List<Document> docs = vectorSearchService.search(TYPE_KNOWLEDGE, query, topK);
        List<Map<String, Object>> results = docs.stream().map(d -> {
            Map<String, Object> item = new LinkedHashMap<>();
            d.getMetadata().forEach((k, v) -> {
                if (!TYPE.equals(k)) {
                    item.put(k, v);
                }
            });
            return item;
        }).toList();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("query", query);
        result.put("results", results);
        return result;
    }
}
