package com.digitalmall.gateway.controller;

import com.digitalmall.gateway.dto.ApiResult;
import com.digitalmall.gateway.dto.LoginRequest;
import com.digitalmall.gateway.dto.LoginResponse;
import com.digitalmall.gateway.dto.SessionUser;
import com.digitalmall.gateway.service.AuthService;
import com.digitalmall.gateway.support.BearerTokenResolver;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * 登录鉴权接口。
 *
 * <p>{@code /login} 在 Security 中放行；{@code /me}、{@code /logout} 需已认证
 * （由 Spring Security 过滤链保证），因此可直接从认证上下文读取当前用户。
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    /** 登录：手机号 + 密码，成功返回 JWT。 */
    @PostMapping("/login")
    public Mono<ApiResult<LoginResponse>> login(@RequestBody LoginRequest req, ServerWebExchange exchange) {
        ServerHttpRequest request = exchange.getRequest();
        String ipAddress = clientIp(request);
        String userAgent = request.getHeaders().getFirst("User-Agent");
        return authService.login(req.phone(), req.password(), ipAddress, userAgent)
                .map(ApiResult::ok)
                .switchIfEmpty(Mono.just(ApiResult.error(401, "手机号或密码错误")));
    }

    private static String clientIp(ServerHttpRequest request) {
        String forwardedFor = request.getHeaders().getFirst("X-Forwarded-For");
        if (forwardedFor != null && !forwardedFor.isBlank()) {
            return forwardedFor.split(",", 2)[0].trim();
        }
        String realIp = request.getHeaders().getFirst("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) {
            return realIp.trim();
        }
        return request.getRemoteAddress() != null
                ? request.getRemoteAddress().getAddress().getHostAddress()
                : null;
    }

    /** 登出：把当前 token 加入黑名单使其失效。 */
    @PostMapping("/logout")
    public Mono<ApiResult<Void>> logout(ServerWebExchange exchange) {
        String token = BearerTokenResolver.resolve(exchange.getRequest());
        return authService.logout(token).thenReturn(ApiResult.<Void>ok(null));
    }

    /** 获取当前登录用户信息。 */
    @GetMapping("/me")
    public Mono<ApiResult<SessionUser>> me(ServerWebExchange exchange) {
        return exchange.getPrincipal()
                .cast(Authentication.class)
                .map(auth -> auth.getDetails() instanceof SessionUser user
                        ? user
                        : new SessionUser(null, auth.getName(), null, null))
                .map(ApiResult::ok)
                .defaultIfEmpty(ApiResult.error(401, "未登录或登录已过期"));
    }
}
