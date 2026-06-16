package com.digitalmall.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * API 网关启动类。
 *
 * <p>作为智能数码商城客服系统的统一入口，对外暴露 HTTP 接口，
 * 负责将请求路由转发到后端的 Python Agent 服务（FastAPI），
 * 并统一处理跨域、限流、访问日志等横切关注点。
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class ApiGatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(ApiGatewayApplication.class, args);
    }
}
