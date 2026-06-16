package com.digitalcs.mcp.web;

import com.digitalcs.mcp.vector.SeedLoader;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.util.Map;

/**
 * 向量索引运维端点：把 classpath 种子 JSON（商品详情 / 售后知识，Qdrant 为其权威源）全量重灌入 Qdrant。
 * 用于数据修复或手动重灌（启动时已由 {@link SeedLoader} 按需自动灌库）；
 * 实际灌库逻辑见 {@link SeedLoader#reindex()}，以 type:bizId 稳定 UUID 写入，重灌覆盖同条不产生重复。
 */
@RestController
@RequestMapping("/admin")
@RequiredArgsConstructor
public class IndexAdminController {

    private final SeedLoader seedLoader;

    @PostMapping("/reindex")
    public Map<String, Object> reindex() throws IOException {
        return seedLoader.reindex();
    }

    /** 全量重置：清空 MySQL + Qdrant 并从 seed 下种子(mysql.sql / *.json)重新灌入。慎用，会丢弃现有业务数据。 */
    @PostMapping("/reset")
    public Map<String, Object> reset() throws IOException {
        return seedLoader.reset();
    }
}
