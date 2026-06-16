"""L1 本地缓存：进程内 LRU 会话热状态。"""

from __future__ import annotations

import threading
from collections import OrderedDict

from agent.config import get_settings

_lock = threading.Lock()
_cache: OrderedDict[str, dict] = OrderedDict()


def get(session_id: str) -> dict | None:
    """读取并把该键标记为最近使用；未命中返回 None。"""
    with _lock:
        if session_id not in _cache:
            return None
        _cache.move_to_end(session_id)
        return _cache[session_id]


def put(session_id: str, state: dict) -> None:
    """写入 / 刷新热状态，超容量时淘汰最久未用项。"""
    cap = get_settings().memory_local_cache_size
    with _lock:
        _cache[session_id] = state
        _cache.move_to_end(session_id)
        while len(_cache) > cap:
            _cache.popitem(last=False)


def clear() -> None:
    """清空缓存，主要用于测试。"""
    with _lock:
        _cache.clear()

