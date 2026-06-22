package com.digitalmall.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * 冒烟测试：验证 Spring 上下文（含网关路由与全局过滤器）能正常装配。
 */
@SpringBootTest(properties = {
        "gateway.jwt.secret=test-only-secret-for-context-load-32b",
        "gateway.security.require-env-jwt-secret=false",
        "spring.r2dbc.username=test",
        "spring.r2dbc.password=test"
})
class ApiGatewayApplicationTests {

    @Test
    void contextLoads() {
        // 上下文加载成功即视为通过
    }
}
