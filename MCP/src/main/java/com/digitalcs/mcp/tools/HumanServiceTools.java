package com.digitalcs.mcp.tools;

import com.digitalcs.mcp.service.HumanServiceService;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 人工服务域 MCP 工具：创建需要人工客服介入的服务单。
 */
@Component
@RequiredArgsConstructor
public class HumanServiceTools {

    private final HumanServiceService humanServiceService;

    @Tool(description = "创建人工服务单。仅当用户明确要求人工客服、投诉升级、情绪明显不满，或问题经客服/工具处理后仍难以解决时使用。写入操作：需先让用户核对原因，可关联订单号；售后单号由售后创建流程在后端生成，不由用户或模型填写。")
    public Map<String, Object> createHumanService(
            @ToolParam(description = "当前会话客户ID") Long userId,
            @ToolParam(description = "转人工原因/用户诉求摘要") String reason,
            @ToolParam(description = "关联订单号(order_no)，没有则留空", required = false) String orderNo) {
        return humanServiceService.create(userId, reason, orderNo, null);
    }
}
