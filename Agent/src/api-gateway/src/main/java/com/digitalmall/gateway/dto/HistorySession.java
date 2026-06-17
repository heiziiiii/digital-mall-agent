package com.digitalmall.gateway.dto;

import java.time.LocalDateTime;

/**
 * 可恢复的历史客服会话摘要。
 *
 * @param sessionId      记忆会话 ID，前端继续对话时作为 session_id 回传
 * @param rollingSummary 会话滚动摘要，用于历史列表展示
 * @param lastUserMessage 最近一次用户提问
 * @param lastAssistantMessage 最近一次客服回答
 * @param updatedAt      最近更新时间
 */
public record HistorySession(
        String sessionId,
        String rollingSummary,
        String lastUserMessage,
        String lastAssistantMessage,
        LocalDateTime updatedAt
) {
}
