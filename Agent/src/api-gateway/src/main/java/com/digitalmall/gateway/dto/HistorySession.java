package com.digitalmall.gateway.dto;

import java.time.LocalDateTime;

/**
 * 可恢复的历史客服会话摘要。
 *
 * @param sessionId      记忆会话 ID，前端继续对话时作为 session_id 回传
 * @param rollingSummary 会话滚动摘要，用于历史列表展示
 * @param updatedAt      最近更新时间
 */
public record HistorySession(
        String sessionId,
        String rollingSummary,
        LocalDateTime updatedAt
) {
}
