package com.digitalcs.mcp.tools;

import com.digitalcs.mcp.service.KnowledgeService;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.Map;

@Component
@RequiredArgsConstructor
public class KnowledgeTools {

    private final KnowledgeService knowledgeService;

    @Tool(description = "检索通用客服知识，用于回答产品使用、故障排查、保养建议、售后政策和流程说明。适合不依赖具体订单、库存或个人售后状态的问题；如果客户转为查询个人订单、物流、售后或提交申请，应切换到对应业务工具。")
    public Map<String, Object> searchKnowledge(
            @ToolParam(description = "客户问题或检索关键词，如 '充电发热怎么办' '如何申请退货'") String query,
            @ToolParam(description = "返回数量上限，默认 5", required = false) Integer topK) {
        return knowledgeService.search(query, topK == null ? 5 : topK);
    }
}
