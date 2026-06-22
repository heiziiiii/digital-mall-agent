package com.digitalmall.gateway.dto;

import java.util.List;

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
