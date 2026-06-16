package com.digitalmall.gateway.dto;

import java.util.List;

/**
 * 历史客服会话详情。
 *
 * @param session  会话摘要
 * @param messages 完整消息流水
 */
public record HistoryConversation(
        HistorySession session,
        List<HistoryMessage> messages
) {
}
