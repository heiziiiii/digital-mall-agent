package com.digitalmall.gateway.service;

import com.digitalmall.gateway.domain.Customer;
import com.digitalmall.gateway.domain.LoginLog;
import com.digitalmall.gateway.repository.LoginLogRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.time.LocalDateTime;

@Service
public class LoginLogService {

    private static final Logger log = LoggerFactory.getLogger(LoginLogService.class);
    private static final int ACCOUNT_MAX_LENGTH = 64;
    private static final int IP_MAX_LENGTH = 64;
    private static final int USER_AGENT_MAX_LENGTH = 512;
    private static final int REASON_MAX_LENGTH = 128;
    private static final int JTI_MAX_LENGTH = 64;

    private final LoginLogRepository repository;

    public LoginLogService(LoginLogRepository repository) {
        this.repository = repository;
    }

    public Mono<Void> success(String account, Customer customer, String ipAddress, String userAgent, String tokenJti) {
        return save(new LoginLog(
                null,
                limit(account, ACCOUNT_MAX_LENGTH),
                customer.id(),
                limit(customer.customerNo(), ACCOUNT_MAX_LENGTH),
                limit(ipAddress, IP_MAX_LENGTH),
                limit(userAgent, USER_AGENT_MAX_LENGTH),
                "SUCCESS",
                null,
                limit(tokenJti, JTI_MAX_LENGTH),
                LocalDateTime.now()));
    }

    public Mono<Void> failure(String account, Customer customer, String ipAddress, String userAgent, String reason) {
        Long customerId = customer != null ? customer.id() : null;
        String customerNo = customer != null ? customer.customerNo() : null;
        return save(new LoginLog(
                null,
                limit(account, ACCOUNT_MAX_LENGTH),
                customerId,
                limit(customerNo, ACCOUNT_MAX_LENGTH),
                limit(ipAddress, IP_MAX_LENGTH),
                limit(userAgent, USER_AGENT_MAX_LENGTH),
                "FAILURE",
                limit(reason, REASON_MAX_LENGTH),
                null,
                LocalDateTime.now()));
    }

    private Mono<Void> save(LoginLog loginLog) {
        return repository.save(loginLog)
                .doOnError(e -> log.warn("Failed to save login log: {}", e.getMessage()))
                .onErrorResume(e -> Mono.empty())
                .then();
    }

    private static String limit(String value, int maxLength) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        if (trimmed.isEmpty()) {
            return null;
        }
        return trimmed.length() <= maxLength ? trimmed : trimmed.substring(0, maxLength);
    }
}
