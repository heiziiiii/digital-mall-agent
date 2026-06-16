package com.digitalmall.gateway.repository;

import com.digitalmall.gateway.domain.Customer;
import org.springframework.data.repository.reactive.ReactiveCrudRepository;
import reactor.core.publisher.Mono;

/**
 * 用户信息仓储（响应式 R2DBC）。
 *
 * <p>登录仅支持用手机号作为账号。
 */
public interface CustomerRepository extends ReactiveCrudRepository<Customer, Long> {

    /** 按手机号查找用户。 */
    Mono<Customer> findByPhone(String phone);
}
