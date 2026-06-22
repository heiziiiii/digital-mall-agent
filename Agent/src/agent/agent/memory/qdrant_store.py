"""Qdrant 记忆层：会话快照、消息快照与长期语义召回。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from agent.config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncQdrantClient | None = None
KIND = "memory_kind"
KIND_SESSION = "session"
KIND_MESSAGE = "message"
KIND_LONG_TERM = "long_term"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _point_id(kind: str, *parts: object) -> str:
    raw = ":".join([kind, *(str(part) for part in parts)])
    return uuid.uuid5(uuid.NAMESPACE_URL, raw).hex


def _zero_vector() -> list[float]:
    return [0.0] * get_settings().embedding_dim


def _payload_value(payload: dict, key: str, default=None):
    value = payload.get(key, default)
    return default if value is None else value


def _embedding_client() -> AsyncOpenAI | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.openai_timeout,
        max_retries=settings.openai_max_retries,
    )


async def embed(text: str) -> list[float] | None:
    """文本转向量；无 Key 或失败时返回 None。"""
    client = _embedding_client()
    if client is None:
        return None
    settings = get_settings()
    try:
        resp = await client.embeddings.create(
            model=settings.embedding_model,
            input=text,
            dimensions=settings.embedding_dim,
        )
    except Exception as exc:  # noqa: BLE001 - embedding 失败不应中断主流程
        logger.warning("embedding 调用失败：%s", exc)
        return None
    return resp.data[0].embedding


async def startup() -> None:
    """建立连接、校验连通性并幂等创建记忆集合。"""
    global _client
    settings = get_settings()
    _client = AsyncQdrantClient(url=settings.qdrant_url)
    await _client.get_collections()
    if not await _client.collection_exists(settings.qdrant_collection):
        await _client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
        )
    logger.info("Qdrant 记忆层连接成功：%s（集合 %s）", settings.qdrant_url, settings.qdrant_collection)


async def shutdown() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def upsert_memory(
    session_id: str,
    role: str,
    text: str,
    turn: int,
    vector: list[float],
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> None:
    """把一条长期语义记忆向量写入集合。"""
    if _client is None:
        raise RuntimeError("Qdrant 客户端尚未启动")
    payload = {
        KIND: KIND_LONG_TERM,
        "session_id": session_id,
        "role": role,
        "text": text,
        "turn": turn,
        "created_at": _now(),
    }
    if customer_id is not None:
        payload["customer_id"] = customer_id
    if customer_no:
        payload["customer_no"] = customer_no
    await _client.upsert(
        collection_name=get_settings().qdrant_collection,
        points=[
            PointStruct(
                id=uuid.uuid4().hex,
                vector=vector,
                payload=payload,
            )
        ],
    )


async def delete_customer(
    customer_id: int | None = None,
    customer_no: str | None = None,
    session_ids: list[str] | None = None,
) -> None:
    """删除某客户的全部记忆点：会话快照、长期语义记忆与（按会话）消息快照。

    会话快照与长期语义记忆点带有 ``customer_id``/``customer_no`` 字段，可直接按身份删除；
    消息快照只带 ``session_id``，需由调用方传入该客户名下会话 id 列表一并清理。
    """
    if _client is None:
        raise RuntimeError("Qdrant 客户端尚未启动")
    collection = get_settings().qdrant_collection
    for field, value in (("customer_id", customer_id), ("customer_no", customer_no)):
        if value in (None, ""):
            continue
        await _client.delete(
            collection_name=collection,
            points_selector=FilterSelector(
                filter=Filter(must=[FieldCondition(key=field, match=MatchValue(value=value))])
            ),
        )
    if session_ids:
        await _client.delete(
            collection_name=collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="session_id", match=MatchAny(any=list(session_ids)))]
                )
            ),
        )


async def load_session(session_id: str) -> dict | None:
    """按 session_id 读取 Qdrant 会话快照。"""
    if _client is None:
        raise RuntimeError("Qdrant 客户端尚未启动")
    records, _ = await _client.scroll(
        collection_name=get_settings().qdrant_collection,
        scroll_filter=Filter(
            must=[
                FieldCondition(key=KIND, match=MatchValue(value=KIND_SESSION)),
                FieldCondition(key="session_id", match=MatchValue(value=session_id)),
            ]
        ),
        limit=1,
        with_payload=True,
        with_vectors=False,
    )
    if not records:
        return None
    payload = records[0].payload or {}
    return {
        "rolling_summary": _payload_value(payload, "rolling_summary", ""),
        "user_profile": _payload_value(payload, "user_profile", {}),
        "turns": int(_payload_value(payload, "turns", 0) or 0),
    }


async def load_latest_customer_session(
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> dict | None:
    """按客户身份读取最近一次 Qdrant 会话快照。"""
    if _client is None:
        raise RuntimeError("Qdrant 客户端尚未启动")
    if customer_id is None and not customer_no:
        return None

    sessions: list[dict] = []
    for field, value in (("customer_id", customer_id), ("customer_no", customer_no)):
        if value in (None, ""):
            continue
        records, _ = await _client.scroll(
            collection_name=get_settings().qdrant_collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key=KIND, match=MatchValue(value=KIND_SESSION)),
                    FieldCondition(key=field, match=MatchValue(value=value)),
                ]
            ),
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
        sessions.extend(record.payload or {} for record in records)

    if not sessions:
        return None
    sessions.sort(key=lambda payload: str(payload.get("updated_at") or ""), reverse=True)
    payload = sessions[0]
    return {
        "rolling_summary": _payload_value(payload, "rolling_summary", ""),
        "user_profile": _payload_value(payload, "user_profile", {}),
        "turns": int(_payload_value(payload, "turns", 0) or 0),
    }


async def recent_messages(session_id: str, limit: int) -> list[dict]:
    """按时间正序返回最近 limit 条 Qdrant 消息快照。"""
    if _client is None:
        raise RuntimeError("Qdrant 客户端尚未启动")
    records, _ = await _client.scroll(
        collection_name=get_settings().qdrant_collection,
        scroll_filter=Filter(
            must=[
                FieldCondition(key=KIND, match=MatchValue(value=KIND_MESSAGE)),
                FieldCondition(key="session_id", match=MatchValue(value=session_id)),
            ]
        ),
        limit=max(limit * 4, 32),
        with_payload=True,
        with_vectors=False,
    )
    payloads = [record.payload or {} for record in records]
    payloads.sort(
        key=lambda payload: (
            int(payload.get("turn") or 0),
            int(payload.get("message_index") or 0),
            str(payload.get("created_at") or ""),
        )
    )
    selected = payloads[-limit:] if limit > 0 else []
    return [
        {"role": str(payload.get("role") or ""), "content": str(payload.get("content") or "")}
        for payload in selected
    ]


async def save_messages(session_id: str, messages: list[dict], turn: int) -> None:
    """把本轮消息写入 Qdrant 快照。"""
    if _client is None:
        raise RuntimeError("Qdrant 客户端尚未启动")
    if not messages:
        return
    now = _now()
    points: list[PointStruct] = []
    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        points.append(
            PointStruct(
                id=_point_id(KIND_MESSAGE, session_id, turn, index, role),
                vector=_zero_vector(),
                payload={
                    KIND: KIND_MESSAGE,
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "turn": turn,
                    "message_index": index,
                    "created_at": now,
                },
            )
        )
    await _client.upsert(collection_name=get_settings().qdrant_collection, points=points)


async def upsert_session(
    session_id: str,
    rolling_summary: str,
    user_profile: dict,
    turns: int,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> None:
    """插入或更新 Qdrant 会话快照。"""
    if _client is None:
        raise RuntimeError("Qdrant 客户端尚未启动")
    payload = {
        KIND: KIND_SESSION,
        "session_id": session_id,
        "rolling_summary": rolling_summary,
        "user_profile": user_profile,
        "turns": turns,
        "updated_at": _now(),
    }
    if customer_id is not None:
        payload["customer_id"] = customer_id
    if customer_no:
        payload["customer_no"] = customer_no
    await _client.upsert(
        collection_name=get_settings().qdrant_collection,
        points=[
            PointStruct(
                id=_point_id(KIND_SESSION, session_id),
                vector=_zero_vector(),
                payload=payload,
            )
        ],
    )


async def _search_by_field(field: str, value: object, vector: list[float], top_k: int) -> list[dict]:
    if _client is None:
        raise RuntimeError("Qdrant 客户端尚未启动")
    filters = [
        Filter(
            must=[
                FieldCondition(key=KIND, match=MatchValue(value=KIND_LONG_TERM)),
                FieldCondition(key=field, match=MatchValue(value=value)),
            ]
        ),
        # 兼容旧版长期记忆点：历史数据没有 memory_kind 字段。
        Filter(must=[FieldCondition(key=field, match=MatchValue(value=value))]),
    ]
    hits = []
    for query_filter in filters:
        response = await _client.query_points(
            collection_name=get_settings().qdrant_collection,
            query=vector,
            query_filter=query_filter,
            limit=top_k,
        )
        hits.extend(response.points)
    return [
        {
            "text": hit.payload.get("text", ""),
            "role": hit.payload.get("role", ""),
            "turn": hit.payload.get("turn"),
            "session_id": hit.payload.get("session_id", ""),
            "customer_id": hit.payload.get("customer_id"),
            "customer_no": hit.payload.get("customer_no"),
            "score": hit.score,
            "created_at": hit.payload.get("created_at", ""),
        }
        for hit in hits
        if (hit.payload or {}).get(KIND) in (None, KIND_LONG_TERM)
        and (hit.payload or {}).get("text")
    ]


async def search(
    session_id: str,
    vector: list[float],
    top_k: int,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> list[dict]:
    """按客户身份优先跨会话检索，最后回退到当前 session_id。"""
    searches: list[tuple[str, object]] = []
    if customer_id is not None:
        searches.append(("customer_id", customer_id))
    if customer_no:
        searches.append(("customer_no", customer_no))
    searches.append(("session_id", session_id))

    merged: list[dict] = []
    seen: set[tuple[str, object, str]] = set()
    for field, value in searches:
        for item in await _search_by_field(field, value, vector, top_k):
            key = (
                str(item.get("session_id") or ""),
                item.get("turn"),
                str(item.get("text") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    merged.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return merged[:top_k]
