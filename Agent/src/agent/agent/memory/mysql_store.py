"""MySQL 最终记忆记录：会话状态与消息流水的持久真相源。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agent.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None


def _now() -> datetime:
    return datetime.now()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return default


async def startup() -> None:
    """建立连接并幂等创建最终记录表。"""
    global _engine
    settings = get_settings()
    _engine = create_async_engine(settings.mysql_dsn, pool_pre_ping=True)
    async with _engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS agent_memory_sessions (
                    session_id VARCHAR(64) PRIMARY KEY,
                    customer_id BIGINT NULL,
                    customer_no VARCHAR(64) NULL,
                    rolling_summary MEDIUMTEXT NULL,
                    user_profile JSON NULL,
                    turns INT NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    KEY idx_customer_id_updated (customer_id, updated_at),
                    KEY idx_customer_no_updated (customer_no, updated_at)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS agent_memory_messages (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL,
                    turn INT NOT NULL,
                    message_index INT NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    content MEDIUMTEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    UNIQUE KEY uk_session_turn_index_role (
                        session_id, turn, message_index, role
                    ),
                    KEY idx_session_turn (session_id, turn, message_index)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                """
            )
        )
    logger.info("MySQL 记忆最终记录连接成功：%s", settings.mysql_dsn)


async def shutdown() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def _require_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("MySQL 记忆客户端尚未启动")
    return _engine


async def load_session(session_id: str) -> dict | None:
    """按 session_id 读取会话级最终状态。"""
    engine = _require_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT rolling_summary, user_profile, turns
                FROM agent_memory_sessions
                WHERE session_id = :session_id
                LIMIT 1
                """
            ),
            {"session_id": session_id},
        )
        row = result.mappings().first()
    if row is None:
        return None
    return {
        "rolling_summary": row["rolling_summary"] or "",
        "user_profile": _json_loads(row["user_profile"], {}),
        "turns": int(row["turns"] or 0),
    }


async def load_latest_customer_session(
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> dict | None:
    """按客户身份读取最近一次会话状态，用于新会话继承画像。"""
    if customer_id is None and not customer_no:
        return None
    engine = _require_engine()
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if customer_id is not None:
        conditions.append("customer_id = :customer_id")
        params["customer_id"] = customer_id
    if customer_no:
        conditions.append("customer_no = :customer_no")
        params["customer_no"] = customer_no
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                f"""
                SELECT rolling_summary, user_profile, turns
                FROM agent_memory_sessions
                WHERE {" OR ".join(conditions)}
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            params,
        )
        row = result.mappings().first()
    if row is None:
        return None
    return {
        "rolling_summary": row["rolling_summary"] or "",
        "user_profile": _json_loads(row["user_profile"], {}),
        "turns": int(row["turns"] or 0),
    }


def _customer_conditions(
    customer_id: int | None, customer_no: str | None
) -> tuple[str, dict[str, Any]]:
    """构造按客户身份过滤的 SQL 条件；二者皆空返回恒假条件。"""
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if customer_id is not None:
        conditions.append("customer_id = :customer_id")
        params["customer_id"] = customer_id
    if customer_no:
        conditions.append("customer_no = :customer_no")
        params["customer_no"] = customer_no
    if not conditions:
        return "1 = 0", params
    return " OR ".join(conditions), params


async def list_customer_session_ids(
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> list[str]:
    """返回某客户名下全部会话 id，用于跨层清理。"""
    if customer_id is None and not customer_no:
        return []
    where, params = _customer_conditions(customer_id, customer_no)
    engine = _require_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                f"SELECT session_id FROM agent_memory_sessions WHERE {where}"
            ),
            params,
        )
        rows = result.mappings().all()
    return [str(row["session_id"]) for row in rows]


async def delete_customer(
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> dict[str, int]:
    """按客户身份删除会话状态与消息流水；返回各表删除行数。"""
    session_ids = await list_customer_session_ids(customer_id, customer_no)
    if not session_ids:
        return {"sessions": 0, "messages": 0}
    where, params = _customer_conditions(customer_id, customer_no)
    engine = _require_engine()
    async with engine.begin() as conn:
        messages_result = await conn.execute(
            text(
                "DELETE FROM agent_memory_messages WHERE session_id IN :session_ids"
            ).bindparams(bindparam("session_ids", expanding=True)),
            {"session_ids": session_ids},
        )
        sessions_result = await conn.execute(
            text(f"DELETE FROM agent_memory_sessions WHERE {where}"),
            params,
        )
    return {
        "sessions": int(sessions_result.rowcount or 0),
        "messages": int(messages_result.rowcount or 0),
    }


async def order_owner(order_no: str) -> int | None:
    """按订单号读取归属客户 id；订单不存在返回 None。"""
    normalized = (order_no or "").strip()
    if not normalized:
        return None
    engine = _require_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT customer_id
                FROM orders
                WHERE order_no = :order_no
                LIMIT 1
                """
            ),
            {"order_no": normalized},
        )
        row = result.mappings().first()
    if row is None:
        return None
    owner = row["customer_id"]
    return int(owner) if owner is not None else None


async def recent_messages(session_id: str, limit: int) -> list[dict]:
    """按时间正序返回最近 limit 条最终消息记录。"""
    engine = _require_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT role, content
                FROM (
                    SELECT role, content, turn, message_index, created_at
                    FROM agent_memory_messages
                    WHERE session_id = :session_id
                    ORDER BY turn DESC, message_index DESC, id DESC
                    LIMIT :limit
                ) AS recent
                ORDER BY turn ASC, message_index ASC, created_at ASC
                """
            ),
            {"session_id": session_id, "limit": max(0, int(limit))},
        )
        rows = result.mappings().all()
    return [
        {"role": str(row["role"] or ""), "content": str(row["content"] or "")}
        for row in rows
    ]


async def save_messages(session_id: str, messages: list[dict], turn: int) -> None:
    """把本轮消息流水写入最终记录。"""
    if not messages:
        return
    engine = _require_engine()
    now = _now()
    async with engine.begin() as conn:
        for index, message in enumerate(messages):
            await conn.execute(
                text(
                    """
                    INSERT INTO agent_memory_messages (
                        session_id, turn, message_index, role, content, created_at
                    ) VALUES (
                        :session_id, :turn, :message_index, :role, :content, :created_at
                    )
                    ON DUPLICATE KEY UPDATE
                        content = VALUES(content),
                        created_at = VALUES(created_at)
                    """
                ),
                {
                    "session_id": session_id,
                    "turn": turn,
                    "message_index": index,
                    "role": str(message.get("role") or ""),
                    "content": str(message.get("content") or ""),
                    "created_at": now,
                },
            )


async def upsert_session(
    session_id: str,
    rolling_summary: str,
    user_profile: dict,
    turns: int,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> None:
    """插入或更新会话级摘要、画像和轮次最终记录。"""
    engine = _require_engine()
    now = _now()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO agent_memory_sessions (
                    session_id, customer_id, customer_no, rolling_summary,
                    user_profile, turns, created_at, updated_at
                ) VALUES (
                    :session_id, :customer_id, :customer_no, :rolling_summary,
                    :user_profile, :turns, :created_at, :updated_at
                )
                ON DUPLICATE KEY UPDATE
                    customer_id = COALESCE(VALUES(customer_id), customer_id),
                    customer_no = COALESCE(VALUES(customer_no), customer_no),
                    rolling_summary = VALUES(rolling_summary),
                    user_profile = VALUES(user_profile),
                    turns = VALUES(turns),
                    updated_at = VALUES(updated_at)
                """
            ),
            {
                "session_id": session_id,
                "customer_id": customer_id,
                "customer_no": customer_no,
                "rolling_summary": rolling_summary,
                "user_profile": _json_dumps(user_profile),
                "turns": turns,
                "created_at": now,
                "updated_at": now,
            },
        )
