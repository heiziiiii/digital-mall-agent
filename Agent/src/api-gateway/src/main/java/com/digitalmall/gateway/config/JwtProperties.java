package com.digitalmall.gateway.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

/**
 * JWT 配置项，绑定 application.yml 中的 {@code gateway.jwt.*}。
 *
 * @param secret HS256 签名密钥（长度需 >= 32 字节）
 * @param ttl    token 有效期
 * @param issuer 签发者标识（写入 iss 声明）
 */
@ConfigurationProperties(prefix = "gateway.jwt")
public record JwtProperties(
        String secret,
        Duration ttl,
        String issuer
) {
    public JwtProperties {
        if (ttl == null || ttl.isZero() || ttl.isNegative()) {
            ttl = Duration.ofHours(2);
        }
        if (issuer == null || issuer.isBlank()) {
            issuer = "api-gateway";
        }
    }
}
