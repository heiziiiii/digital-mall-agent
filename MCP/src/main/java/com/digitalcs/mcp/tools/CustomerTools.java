package com.digitalcs.mcp.tools;

import java.util.Map;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import com.digitalcs.mcp.service.CustomerService;

import lombok.RequiredArgsConstructor;

/**
 * 用户信息域 MCP 工具：自助模式下只允许查询当前用户本人的资料。
 */
@Component
@RequiredArgsConstructor
public class CustomerTools {

    private final CustomerService customerService;

    @Tool(description = "查询当前客户的基础资料，如昵称、手机号和会员等级。适合需要确认称呼、判断会员权益，或客户询问自己资料时使用；回复时只提及当前问题需要的信息。")
    public Map<String, Object> getCustomerById(
            @ToolParam(description = "当前会话客户ID") Long userId) {
        return customerService.getMyProfile(userId);
    }
}
