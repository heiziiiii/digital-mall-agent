package com.digitalmall.gateway.config;

import com.digitalmall.gateway.security.JwtAuthenticationConverter;
import com.digitalmall.gateway.security.JwtReactiveAuthenticationManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.security.config.annotation.web.reactive.EnableWebFluxSecurity;
import org.springframework.security.config.web.server.SecurityWebFiltersOrder;
import org.springframework.security.config.web.server.ServerHttpSecurity;
import org.springframework.security.web.server.SecurityWebFilterChain;
import org.springframework.security.web.server.authentication.AuthenticationWebFilter;
import org.springframework.security.web.server.context.NoOpServerSecurityContextRepository;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;

/**
 * Spring Security（WebFlux 响应式）安全配置。
 *
 * <p>无状态 JWT 鉴权：自定义 {@link AuthenticationWebFilter} 解析 Bearer token；
 * 登录接口与运维端点放行，其余一律要求认证；CORS 交由网关 globalcors 处理。
 *
 * <p>注意：Security 是 WebFilter，覆盖<b>所有</b>请求（含网关本地 /api/auth/**），
 * 这与只作用于转发请求的 GatewayFilter（限流）不同。
 */
@Configuration
@EnableWebFluxSecurity
public class SecurityConfig {

    @Bean
    public SecurityWebFilterChain securityWebFilterChain(
            ServerHttpSecurity http,
            JwtReactiveAuthenticationManager authenticationManager,
            JwtAuthenticationConverter authenticationConverter) {

        // 组装 JWT 认证过滤器
        AuthenticationWebFilter jwtFilter = new AuthenticationWebFilter(authenticationManager);
        jwtFilter.setServerAuthenticationConverter(authenticationConverter);
        // 关键：携带无效/过期 token 时认证失败，由 AuthenticationWebFilter 自身的失败处理器处理，
        // 默认是 HttpBasicServerAuthenticationEntryPoint，会返回 WWW-Authenticate: Basic 触发浏览器弹窗。
        // 这里覆盖为返回统一 JSON 401，与下方匿名请求的 authenticationEntryPoint 行为保持一致。
        jwtFilter.setAuthenticationFailureHandler((webFilterExchange, exception) ->
                writeError(webFilterExchange.getExchange(), HttpStatus.UNAUTHORIZED, "未登录或登录凭证无效"));

        return http
                // 网关无表单/会话，禁用一系列默认机制；CORS 由网关 globalcors 负责
                .csrf(ServerHttpSecurity.CsrfSpec::disable)
                .cors(ServerHttpSecurity.CorsSpec::disable)
                .httpBasic(ServerHttpSecurity.HttpBasicSpec::disable)
                .formLogin(ServerHttpSecurity.FormLoginSpec::disable)
                .logout(ServerHttpSecurity.LogoutSpec::disable)
                // 无状态：不保存 SecurityContext
                .securityContextRepository(NoOpServerSecurityContextRepository.getInstance())
                .authorizeExchange(ex -> ex
                        // 放行 CORS 预检
                        .pathMatchers(HttpMethod.OPTIONS).permitAll()
                        // 登录接口与健康检查免认证
                        .pathMatchers("/api/auth/login").permitAll()
                        .pathMatchers("/actuator/health").permitAll()
                        // 其余全部需要认证（/api/agent/**、/api/auth/me、/api/auth/logout 等）
                        .anyExchange().authenticated())
                .addFilterAt(jwtFilter, SecurityWebFiltersOrder.AUTHENTICATION)
                // 统一以 JSON 返回 401/403，而非默认的 WWW-Authenticate 弹窗
                .exceptionHandling(e -> e
                        .authenticationEntryPoint((exchange, ex) ->
                                writeError(exchange, HttpStatus.UNAUTHORIZED, "未登录或登录凭证无效"))
                        .accessDeniedHandler((exchange, ex) ->
                                writeError(exchange, HttpStatus.FORBIDDEN, "无权访问")))
                .build();
    }

    /** 写出统一格式的错误 JSON 响应。 */
    private Mono<Void> writeError(ServerWebExchange exchange, HttpStatus status, String message) {
        ServerHttpResponse response = exchange.getResponse();
        response.setStatusCode(status);
        response.getHeaders().setContentType(new MediaType(MediaType.APPLICATION_JSON, StandardCharsets.UTF_8));
        String body = "{\"code\":" + status.value() + ",\"message\":\"" + message + "\",\"data\":null}";
        DataBuffer buffer = response.bufferFactory().wrap(body.getBytes(StandardCharsets.UTF_8));
        return response.writeWith(Mono.just(buffer));
    }
}
