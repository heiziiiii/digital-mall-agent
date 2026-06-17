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
                SELECT
                    s.session_id,
                    s.rolling_summary,
                    (
                        SELECT m.content
                        FROM agent_memory_messages m
                        WHERE m.session_id = s.session_id AND m.role = 'user'
                        ORDER BY m.turn DESC, m.message_index DESC, m.id DESC
                        LIMIT 1
                    ) AS last_user_message,
                    (
                        SELECT m.content
                        FROM agent_memory_messages m
                        WHERE m.session_id = s.session_id AND m.role = 'assistant'
                        ORDER BY m.turn DESC, m.message_index DESC, m.id DESC
                        LIMIT 1
                    ) AS last_assistant_message,
                    s.updated_at
                FROM agent_memory_sessions s
                WHERE 1 = 0
                """);
        if (customerId != null) {
            sql.append(" OR s.customer_id = :customerId");
        }
        if (customerNo != null && !customerNo.isBlank()) {
            sql.append(" OR s.customer_no = :customerNo");
        }
        sql.append(" ORDER BY s.updated_at DESC LIMIT 100");

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
                        valueOrEmpty(row.get("last_user_message", String.class)),
                        valueOrEmpty(row.get("last_assistant_message", String.class)),
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

    /**
     * 删除当前客户的某条历史会话（会话状态 + 消息流水）。
     *
     * <p>先校验会话归属，避免越权删除他人会话。返回是否真正删除了记录。
     */
    public Mono<Boolean> deleteSessionByCustomer(String sessionId, Long customerId, String customerNo) {
        if (sessionId == null || sessionId.isBlank()) {
            return Mono.just(false);
        }
        return findSessionByCustomer(sessionId, customerId, customerNo)
                .flatMap(session -> databaseClient.sql(
                                "DELETE FROM agent_memory_messages WHERE session_id = :sessionId")
                        .bind("sessionId", sessionId)
                        .fetch()
                        .rowsUpdated()
                        .then(databaseClient.sql(
                                        "DELETE FROM agent_memory_sessions WHERE session_id = :sessionId")
                                .bind("sessionId", sessionId)
                                .fetch()
                                .rowsUpdated())
                        .thenReturn(true))
                .defaultIfEmpty(false);
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
