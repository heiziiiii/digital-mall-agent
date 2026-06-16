package com.digitalmall.gateway;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * 冒烟测试：验证 Spring 上下文（含网关路由与全局过滤器）能正常装配。
 */
@SpringBootTest
class ApiGatewayApplicationTests {

    @Test
    void contextLoads() {
        // 上下文加载成功即视为通过
    }
}
