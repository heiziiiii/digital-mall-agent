package com.digitalmall.gateway.support;

import org.springframework.http.HttpHeaders;
import org.springframework.http.server.reactive.ServerHttpRequest;

/**
 * 从请求头解析会话 token 的工具类。
 *
 * <p>优先识别标准的 {@code Authorization: Bearer <token>}；为方便调试也兼容直接传裸 token。
 */
public final class BearerTokenResolver {

    private static final String BEARER_PREFIX = "Bearer ";

    private BearerTokenResolver() {
    }

    /** 解析 token，未携带时返回 {@code null}。 */
    public static String resolve(ServerHttpRequest request) {
        String header = request.getHeaders().getFirst(HttpHeaders.AUTHORIZATION);
        if (header == null || header.isBlank()) {
            return null;
        }
        header = header.trim();
        if (header.regionMatches(true, 0, BEARER_PREFIX, 0, BEARER_PREFIX.length())) {
            String token = header.substring(BEARER_PREFIX.length()).trim();
            return token.isEmpty() ? null : token;
        }
        // 兼容直接传 token（不带 Bearer 前缀）的调试场景
        return header;
    }
}
