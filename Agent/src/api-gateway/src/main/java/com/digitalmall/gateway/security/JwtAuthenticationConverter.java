package com.digitalmall.gateway.security;

import com.digitalmall.gateway.support.BearerTokenResolver;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.server.authentication.ServerAuthenticationConverter;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * 从请求中提取 Bearer token，包装为待认证的 {@link Authentication}。
 *
 * <p>仅负责提取，真正的验签/校验交给 {@link JwtReactiveAuthenticationManager}。
 * 未携带 token 时返回 {@link Mono#empty()}，由 Security 决定是否放行（白名单）或拒绝。
 */
@Component
public class JwtAuthenticationConverter implements ServerAuthenticationConverter {

    @Override
    public Mono<Authentication> convert(ServerWebExchange exchange) {
        String token = BearerTokenResolver.resolve(exchange.getRequest());
        if (token == null) {
            return Mono.empty();
        }
        // 二参构造 => 未认证状态；token 放入 credentials 供认证管理器解析
        return Mono.just(new UsernamePasswordAuthenticationToken(token, token));
    }
}
