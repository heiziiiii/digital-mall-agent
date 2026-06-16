package com.digitalmall.gateway.domain;

import org.springframework.data.annotation.Id;
import org.springframework.data.relational.core.mapping.Column;
import org.springframework.data.relational.core.mapping.Table;

import java.time.LocalDateTime;

@Table("login_log")
public record LoginLog(
        @Id Long id,
        String account,
        @Column("customer_id") Long customerId,
        @Column("customer_no") String customerNo,
        @Column("ip_address") String ipAddress,
        @Column("user_agent") String userAgent,
        String status,
        @Column("failure_reason") String failureReason,
        @Column("token_jti") String tokenJti,
        @Column("created_at") LocalDateTime createdAt
) {
}
