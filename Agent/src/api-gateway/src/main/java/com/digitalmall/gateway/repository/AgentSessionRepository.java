package com.digitalmall.gateway.repository;

import com.digitalmall.gateway.dto.HistoryMessage;
import com.digitalmall.gateway.dto.HistorySession;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.stereotype.Repository;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.LocalDateTime;

/**
 * 客服 Agent 记忆会话查询。
 *
 * <p>记忆最终记录在 MySQL：
 * {@code agent_memory_sessions} 保存会话摘要/画像，
 * {@code agent_memory_messages} 保存消息流水。
 */
@Repository
public class AgentSessionRepository {

    private final DatabaseClient databaseClient;

    public AgentSessionRepository(DatabaseClient databaseClient) {
        this.databaseClient = databaseClient;
    }

    public Flux<String> findSessionIdsByCustomer(Long customerId, String customerNo) {
        return findSessionsByCustomer(customerId, customerNo).map(HistorySession::sessionId);
    }

    public Flux<HistorySession> findSessionsByCustomer(Long customerId, String customerNo) {
        if (customerId == null && (customerNo == null || customerNo.isBlank())) {
            return Flux.empty();
        }
        StringBuilder sql = new StringBuilder("""
                SELECT session_id, rolling_summary, updated_at
                FROM agent_memory_sessions
                WHERE 1 = 0
                """);
        if (customerId != null) {
            sql.append(" OR customer_id = :customerId");
        }
        if (customerNo != null && !customerNo.isBlank()) {
            sql.append(" OR customer_no = :customerNo");
        }
        sql.append(" ORDER BY updated_at DESC LIMIT 100");

        DatabaseClient.GenericExecuteSpec spec = databaseClient.sql(sql.toString());
        if (customerId != null) {
            spec = spec.bind("customerId", customerId);
        }
        if (customerNo != null && !customerNo.isBlank()) {
            spec = spec.bind("customerNo", customerNo);
        }
        return spec.map((row, meta) -> new HistorySession(
                        row.get("session_id", String.class),
                        valueOrEmpty(row.get("rolling_summary", String.class)),
                        row.get("updated_at", LocalDateTime.class)))
                .all()
                .filter(session -> session.sessionId() != null && !session.sessionId().isBlank());
    }

    public Mono<HistorySession> findSessionByCustomer(String sessionId, Long customerId, String customerNo) {
        if (sessionId == null || sessionId.isBlank()) {
            return Mono.empty();
        }
        return findSessionsByCustomer(customerId, customerNo)
                .filter(session -> session.sessionId().equals(sessionId))
                .next();
    }

    public Flux<HistoryMessage> findMessagesBySession(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) {
            return Flux.empty();
        }
        return databaseClient.sql("""
                        SELECT role, content, turn, created_at
                        FROM agent_memory_messages
                        WHERE session_id = :sessionId
                        ORDER BY turn ASC, message_index ASC, id ASC
                        """)
                .bind("sessionId", sessionId)
                .map((row, meta) -> new HistoryMessage(
                        valueOrEmpty(row.get("role", String.class)),
                        valueOrEmpty(row.get("content", String.class)),
                        row.get("turn", Integer.class),
                        row.get("created_at", LocalDateTime.class)))
                .all();
    }

    private static String valueOrEmpty(String value) {
        return value == null ? "" : value;
    }
}
