package com.digitalmall.gateway.dto;

import java.time.LocalDateTime;

/**
 * 历史客服会话中的单条消息。
 *
 * @param role      消息角色，通常为 user 或 assistant
 * @param content   消息内容
 * @param turn      对话轮次
 * @param createdAt 创建时间
 */
public record HistoryMessage(
        String role,
        String content,
        Integer turn,
        LocalDateTime createdAt
) {
}
