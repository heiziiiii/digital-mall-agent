package com.digitalmall.gateway.service;

import com.digitalmall.gateway.domain.Customer;
import com.digitalmall.gateway.dto.HistorySession;
import com.digitalmall.gateway.dto.LoginResponse;
import com.digitalmall.gateway.repository.AgentSessionRepository;
import com.digitalmall.gateway.repository.CustomerRepository;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * 登录鉴权服务：校验账号密码、签发 JWT、登出（拉黑 token）。
 *
 * <p>token 采用无状态 JWT（{@link JwtService}），登出通过把 jti 写入 Redis 黑名单
 * （{@link TokenBlacklistService}）实现服务端主动失效。
 */
@Service
public class AuthService {

    private final CustomerRepository customerRepository;
    private final AgentSessionRepository agentSessionRepository;
    private final JwtService jwtService;
    private final TokenBlacklistService blacklist;
    private final LoginLogService loginLogService;

    public AuthService(CustomerRepository customerRepository,
                       AgentSessionRepository agentSessionRepository,
                       JwtService jwtService,
                       TokenBlacklistService blacklist,
                       LoginLogService loginLogService) {
        this.customerRepository = customerRepository;
        this.agentSessionRepository = agentSessionRepository;
        this.jwtService = jwtService;
        this.blacklist = blacklist;
        this.loginLogService = loginLogService;
    }

    /**
     * 登录：校验手机号 + 密码，成功则签发 JWT。
     *
     * @return 成功返回 {@link LoginResponse}；手机号不存在或密码错误返回 {@link Mono#empty()}
     */
    public Mono<LoginResponse> login(String phone, String password, String ipAddress, String userAgent) {
        String account = phone == null ? null : phone.trim();
        if (account == null || account.isBlank() || password == null) {
            return loginLogService.failure(account, null, ipAddress, userAgent, "INVALID_REQUEST")
                    .then(Mono.empty());
        }
        return customerRepository.findByPhone(account)
                .map(Optional::of)
                .defaultIfEmpty(Optional.empty())
                .flatMap(customer -> customer
                        .map(c -> loginExistingCustomer(account, password, ipAddress, userAgent, c))
                        .orElseGet(() -> loginLogService.failure(
                                account, null, ipAddress, userAgent, "BAD_CREDENTIALS").then(Mono.empty())));
    }

    private Mono<LoginResponse> loginExistingCustomer(
            String account,
            String password,
            String ipAddress,
            String userAgent,
            Customer customer) {
        if (!password.equals(customer.password())) {
            return loginLogService.failure(account, customer, ipAddress, userAgent, "BAD_CREDENTIALS")
                    .then(Mono.empty());
        }
        JwtService.IssuedToken issued = jwtService.issue(
                customer.id(), customer.customerNo(), customer.nickname(), customer.memberLevel());
        return agentSessionRepository.findSessionsByCustomer(customer.id(), customer.customerNo())
                .collectList()
                .onErrorReturn(List.of())
                .map(historySessions -> new LoginResponse(
                        issued.token(),
                        issued.expiresInSeconds(),
                        customer.id(),
                        customer.customerNo(),
                        customer.nickname(),
                        customer.memberLevel(),
                        historySessions.stream().map(HistorySession::sessionId).toList(),
                        historySessions))
                .flatMap(response -> loginLogService.success(
                        account, customer, ipAddress, userAgent, issued.jti()).thenReturn(response));
    }

    /**
     * 登出：把 token 的 jti 加入黑名单（TTL=距过期剩余时间）。
     * token 已过期或无效则无需拉黑，直接返回 false。
     */
    public Mono<Boolean> logout(String token) {
        if (token == null || token.isBlank()) {
            return Mono.just(false);
        }
        final Claims claims;
        try {
            claims = jwtService.parse(token);
        } catch (JwtException | IllegalArgumentException e) {
            return Mono.just(false);
        }
        Duration remaining = Duration.between(Instant.now(), claims.getExpiration().toInstant());
        return blacklist.blacklist(claims.getId(), remaining);
    }
}
