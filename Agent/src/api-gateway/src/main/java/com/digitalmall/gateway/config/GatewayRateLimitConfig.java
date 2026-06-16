package com.digitalmall.gateway.config;

import org.springframework.cloud.gateway.filter.ratelimit.KeyResolver;
import org.springframework.cloud.gateway.filter.ratelimit.PrincipalNameKeyResolver;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 限流 KeyResolver 配置。
 *
 * <p>使用 Spring Cloud Gateway 自带的 {@link PrincipalNameKeyResolver}：取认证后的
 * principal 名称作为限流维度。本系统 principal 即客户编号，因此<b>限流粒度为用户 ID</b>。
 * 被限流的 {@code /api/agent/**} 均要求已登录，principal 必然存在。
 */
@Configuration
public class GatewayRateLimitConfig {

    @Bean
    public KeyResolver userKeyResolver() {
        return new PrincipalNameKeyResolver();
    }
}
