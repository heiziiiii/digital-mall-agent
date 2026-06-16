package com.digitalmall.gateway.controller;

import com.digitalmall.gateway.dto.ApiResult;
import com.digitalmall.gateway.dto.HistoryConversation;
import com.digitalmall.gateway.dto.HistorySession;
import com.digitalmall.gateway.dto.SessionUser;
import com.digitalmall.gateway.repository.AgentSessionRepository;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.List;

/**
 * 当前登录用户的历史客服会话详情。
 */
@RestController
@RequestMapping("/api/auth/history")
public class HistoryController {

    private final AgentSessionRepository agentSessionRepository;

    public HistoryController(AgentSessionRepository agentSessionRepository) {
        this.agentSessionRepository = agentSessionRepository;
    }

    @GetMapping
    public Mono<ApiResult<List<HistorySession>>> list(ServerWebExchange exchange) {
        return currentUser(exchange)
                .flatMapMany(user -> agentSessionRepository
                        .findSessionsByCustomer(user.customerId(), user.customerNo()))
                .collectList()
                .map(ApiResult::ok)
                .switchIfEmpty(Mono.just(ApiResult.error(401, "未登录或登录已过期")));
    }

    @GetMapping("/{sessionId}")
    public Mono<ApiResult<HistoryConversation>> detail(
            @PathVariable String sessionId,
            ServerWebExchange exchange) {
        return currentUser(exchange)
                .flatMap(user -> agentSessionRepository
                        .findSessionByCustomer(sessionId, user.customerId(), user.customerNo())
                        .flatMap(session -> agentSessionRepository.findMessagesBySession(session.sessionId())
                                .collectList()
                                .map(messages -> ApiResult.ok(new HistoryConversation(session, messages)))))
                .defaultIfEmpty(ApiResult.error(404, "历史会话不存在或无权访问"));
    }

    private Mono<SessionUser> currentUser(ServerWebExchange exchange) {
        return exchange.getPrincipal()
                .cast(Authentication.class)
                .flatMap(auth -> auth.getDetails() instanceof SessionUser user
                        ? Mono.just(user)
                        : Mono.empty());
    }
}
