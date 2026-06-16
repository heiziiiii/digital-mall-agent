package com.digitalmall.gateway.security;

import com.digitalmall.gateway.dto.SessionUser;
import com.digitalmall.gateway.service.JwtService;
import com.digitalmall.gateway.service.TokenBlacklistService;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.ReactiveAuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

import java.util.List;

/**
 * JWT 认证管理器：验签解析 token、校验登出黑名单，成功则构建已认证的 {@link Authentication}。
 *
 * <p>principal 设为客户编号（customer_no），故 {@code Authentication#getName()} 即用户 ID，
 * 既用于限流 KeyResolver，也用于向下游透传身份。
 */
@Component
public class JwtReactiveAuthenticationManager implements ReactiveAuthenticationManager {

    private final JwtService jwtService;
    private final TokenBlacklistService blacklist;

    public JwtReactiveAuthenticationManager(JwtService jwtService, TokenBlacklistService blacklist) {
        this.jwtService = jwtService;
        this.blacklist = blacklist;
    }

    @Override
    public Mono<Authentication> authenticate(Authentication authentication) {
        String token = String.valueOf(authentication.getCredentials());
        // 验签 + 校验过期；jjwt 在失败时抛 JwtException，统一转为认证异常
        return Mono.fromCallable(() -> jwtService.parse(token))
                .onErrorMap(JwtException.class, e -> new BadCredentialsException("登录凭证无效或已过期", e))
                .flatMap(claims -> blacklist.isBlacklisted(claims.getId())
                        .flatMap(black -> black
                                ? Mono.error(new BadCredentialsException("登录凭证已失效，请重新登录"))
                                : Mono.just(toAuthentication(claims))));
    }

    /** 把 JWT 声明转为已认证的 Authentication，用户信息放入 details 供后续透传。 */
    private Authentication toAuthentication(Claims claims) {
        String customerNo = claims.getSubject();
        Long customerId = claims.get("customerId", Long.class);
        String nickname = claims.get("nickname", String.class);
        Integer memberLevel = claims.get("memberLevel", Integer.class);
        // 三参构造 => 已认证状态（authorities 非空即可，这里暂不细分角色）
        var auth = new UsernamePasswordAuthenticationToken(customerNo, null, List.of());
        auth.setDetails(new SessionUser(customerId, customerNo, nickname, memberLevel));
        return auth;
    }
}
