package com.digitalmall.gateway.service;

import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.time.Duration;

/**
 * JWT 登出黑名单（基于 Redis）。
 *
 * <p>登出时把 token 的 jti 写入黑名单，TTL 设为该 token 距过期的剩余时间——
 * token 自然过期后黑名单项也随之清除，无需额外清理。
 */
@Service
public class TokenBlacklistService {

    private static final String BLACKLIST_KEY_PREFIX = "auth:blacklist:";

    private final ReactiveStringRedisTemplate redis;

    public TokenBlacklistService(ReactiveStringRedisTemplate redis) {
        this.redis = redis;
    }

    /** 把 jti 加入黑名单，保留到其原本的过期时刻。ttl 非正时视为已过期，直接跳过。 */
    public Mono<Boolean> blacklist(String jti, Duration ttl) {
        if (jti == null || jti.isBlank() || ttl == null || ttl.isZero() || ttl.isNegative()) {
            return Mono.just(false);
        }
        return redis.opsForValue().set(BLACKLIST_KEY_PREFIX + jti, "1", ttl);
    }

    /** 判断 jti 是否已被拉黑。 */
    public Mono<Boolean> isBlacklisted(String jti) {
        if (jti == null || jti.isBlank()) {
            return Mono.just(false);
        }
        return redis.hasKey(BLACKLIST_KEY_PREFIX + jti);
    }
}
