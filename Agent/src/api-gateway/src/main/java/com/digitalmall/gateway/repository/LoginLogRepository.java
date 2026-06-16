package com.digitalmall.gateway.repository;

import com.digitalmall.gateway.domain.LoginLog;
import org.springframework.data.repository.reactive.ReactiveCrudRepository;

public interface LoginLogRepository extends ReactiveCrudRepository<LoginLog, Long> {
}
