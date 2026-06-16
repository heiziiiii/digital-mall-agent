package com.digitalmall.gateway.filter;

import com.digitalmall.gateway.dto.SessionUser;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * 身份透传过滤器：把已登录用户身份注入转发请求头，供下游 Agent 服务使用，下游无需再鉴权。
 *
 * <p>认证由 Spring Security 完成，此处仅从 {@code exchange.getPrincipal()} 读取结果。
 * 对未认证放行的请求（如登录）principal 为空，原样转发。
 */
@Component
public class IdentityRelayGlobalFilter implements GlobalFilter, Ordered {

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        return exchange.getPrincipal()
                .filter(Authentication.class::isInstance)
                .cast(Authentication.class)
                .map(auth -> {
                    ServerHttpRequest.Builder builder = exchange.getRequest().mutate()
                            .header("X-Customer-No", auth.getName());
                    if (auth.getDetails() instanceof SessionUser user) {
                        if (user.customerId() != null) {
                            builder.header("X-Customer-Id", String.valueOf(user.customerId()));
                        }
                        if (user.memberLevel() != null) {
                            builder.header("X-Member-Level", String.valueOf(user.memberLevel()));
                        }
                    }
                    return exchange.mutate().request(builder.build()).build();
                })
                .defaultIfEmpty(exchange)
                .flatMap(chain::filter);
    }

    @Override
    public int getOrder() {
        // 在路由转发前注入；此时 Spring Security 已完成认证
        return Ordered.LOWEST_PRECEDENCE - 1;
    }
}
