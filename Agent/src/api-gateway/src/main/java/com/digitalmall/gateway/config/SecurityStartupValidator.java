package com.digitalmall.gateway.config;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/**
 * 启动期安全配置校验：阻止生产服务带着开发默认值或文件内密钥启动。
 */
@Component
public class SecurityStartupValidator implements ApplicationRunner {

    private final Environment environment;

    public SecurityStartupValidator(Environment environment) {
        this.environment = environment;
    }

    @Override
    public void run(ApplicationArguments args) {
        boolean requireEnvSecret = environment.getProperty(
                "gateway.security.require-env-jwt-secret",
                Boolean.class,
                true);
        if (!requireEnvSecret) {
            return;
        }

        String jwtSecret = System.getenv("JWT_SECRET");
        if (jwtSecret == null || jwtSecret.isBlank()) {
            throw new IllegalStateException("JWT_SECRET 必须通过环境变量提供，禁止使用配置文件默认密钥启动网关");
        }
    }
}
