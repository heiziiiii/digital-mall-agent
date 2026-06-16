package com.digitalmall.gateway.domain;

import org.springframework.data.annotation.Id;
import org.springframework.data.relational.core.mapping.Column;
import org.springframework.data.relational.core.mapping.Table;

import java.time.LocalDateTime;

/**
 * 用户信息实体，映射 MySQL {@code customer} 表（见 docs/server.md）。
 *
 * <p>仅用于网关登录校验，故只读不写。属性名到列名的映射用 {@link Column} 显式声明，
 * 避免依赖命名策略导致的下划线/驼峰不一致。
 */
@Table("customer")
public record Customer(
        @Id Long id,
        @Column("customer_no") String customerNo,
        String nickname,
        String phone,
        String password,
        @Column("member_level") Integer memberLevel,
        @Column("created_at") LocalDateTime createdAt
) {
}
