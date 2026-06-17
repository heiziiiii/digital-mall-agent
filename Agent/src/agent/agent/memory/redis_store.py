"""L2 Redis 工作状态缓存。"""

from __future__ import annotations

import json
import logging

from redis.asyncio import Redis

from agent.config import get_settings

logger = logging.getLogger(__name__)

_client: Redis | None = None


async def startup() -> None:
    """建立连接并 ping 校验。"""
    global _client
    settings = get_settings()
    _client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        protocol=settings.redis_protocol,
    )
    await _client.ping()
    logger.info("Redis 连接成功：%s", settings.redis_url)


async def shutdown() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _key(session_id: str) -> str:
    return f"mem:{session_id}:state"


def _task_key(thread_id: str) -> str:
    return f"run:{thread_id}:state"


async def get_state(session_id: str) -> dict | None:
    """读取会话状态；未命中返回 None。"""
    raw = await _client.get(_key(session_id))
    return json.loads(raw) if raw else None


async def set_state(session_id: str, state: dict) -> None:
    """写入会话状态并刷新 TTL。"""
    ttl = get_settings().memory_redis_ttl_seconds
    await _client.set(_key(session_id), json.dumps(state, ensure_ascii=False), ex=ttl)


async def delete_state(session_id: str) -> None:
    """删除会话状态缓存；未启动或未命中时静默忽略。"""
    if _client is None:
        return
    await _client.delete(_key(session_id))


async def get_task_state(thread_id: str) -> dict | None:
    """读取当前任务运行状态快照；未命中返回 None。"""
    if _client is None:
        return None
    raw = await _client.get(_task_key(thread_id))
    return json.loads(raw) if raw else None


async def set_task_state(thread_id: str, state: dict) -> None:
    """写入当前任务运行状态快照并刷新 TTL。"""
    if _client is None:
        return
    ttl = get_settings().memory_redis_ttl_seconds
    await _client.set(_task_key(thread_id), json.dumps(state, ensure_ascii=False), ex=ttl)
