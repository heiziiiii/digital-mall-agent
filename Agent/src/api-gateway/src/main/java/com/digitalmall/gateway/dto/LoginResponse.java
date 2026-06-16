package com.digitalmall.gateway.dto;

import java.util.List;

/**
 * 登录成功返回体。
 *
 * @param token             会话凭证，后续请求放入 {@code Authorization: Bearer <token>}
 * @param expiresIn         token 有效期（秒）
 * @param customerId        客户数据库主键 ID
 * @param customerNo        客户编号
 * @param nickname          昵称
 * @param memberLevel       会员等级（0普通 1银 2金 3铂金）
 * @param historySessionIds 该客户历史客服记忆会话 ID，前端可作为后续请求的 {@code session_id}
 * @param historySessions   该客户历史客服记忆会话摘要，前端用于展示历史对话标题/预览
 */
public record LoginResponse(
        String token,
        long expiresIn,
        Long customerId,
        String customerNo,
        String nickname,
        Integer memberLevel,
        List<String> historySessionIds,
        List<HistorySession> historySessions
) {
}
