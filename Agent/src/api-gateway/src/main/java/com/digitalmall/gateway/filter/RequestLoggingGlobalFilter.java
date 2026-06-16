package com.digitalmall.gateway.filter;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * 访问日志全局过滤器：记录每个请求的方法、路径、状态码与耗时，便于排查与监控。
 */
@Component
public class RequestLoggingGlobalFilter implements GlobalFilter, Ordered {

    private static final Logger log = LoggerFactory.getLogger(RequestLoggingGlobalFilter.class);

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        long start = System.currentTimeMillis();
        String method = exchange.getRequest().getMethod().name();
        String path = exchange.getRequest().getURI().getRawPath();

        // 在响应完成后统一打印一行访问日志（无论成功或异常）
        return chain.filter(exchange).doFinally(signal -> {
            long cost = System.currentTimeMillis() - start;
            var statusCode = exchange.getResponse().getStatusCode();
            log.info("{} {} -> {} ({}ms)", method, path,
                    statusCode != null ? statusCode.value() : "-", cost);
        });
    }

    @Override
    public int getOrder() {
        // 最先进入、最后完成，从而覆盖整条过滤链的耗时
        return Ordered.HIGHEST_PRECEDENCE;
    }
}
