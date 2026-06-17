package com.digitalcs.mcp;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

import java.time.format.DateTimeFormatter;

import com.digitalcs.mcp.tools.AfterSaleTools;
import com.digitalcs.mcp.tools.HumanServiceTools;
import com.digitalcs.mcp.tools.KnowledgeTools;
import com.digitalcs.mcp.tools.OrderTools;
import com.digitalcs.mcp.tools.ProductTools;

/**
 * 数码智能客服系统 — MCP 服务器入口。
 * 启动后通过 Spring AI MCP Server(WebMVC SSE) 暴露
 * {@link org.springframework.ai.tool.annotation.Tool} 工具。
 */
@SpringBootApplication
@MapperScan("com.digitalcs.mcp.mapper")
public class McpServerApplication {

    public static void main(String[] args) {
        SpringApplication.run(McpServerApplication.class, args);
    }

    /**
     * 把各业务工具类中的 @Tool 方法注册为 MCP 工具。
     */
    @Bean
    public ToolCallbackProvider customerServiceTools(ProductTools productTools,
            OrderTools orderTools,
            AfterSaleTools afterSaleTools,
            HumanServiceTools humanServiceTools,
            KnowledgeTools knowledgeTools) {
        return MethodToolCallbackProvider.builder()
                .toolObjects(productTools, orderTools, afterSaleTools, humanServiceTools, knowledgeTools)
                .build();
    }

    /** 售后单号时间戳格式器：线程安全且不可变，交由 Spring 以单例 Bean 管理，避免每次生成单号都新建。 */
    @Bean
    public DateTimeFormatter afterSaleNoFormatter() {
        return DateTimeFormatter.ofPattern("yyyyMMddHHmmssSSS");
    }
}
