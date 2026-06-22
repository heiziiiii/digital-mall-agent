"""Agent 与 Tool 调用日志 hook。"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import Any

from agent.config import AGENT_ROOT

LOG_DIR = AGENT_ROOT / "logs"
AGENT_LOG_FILE = LOG_DIR / "agent_calls.jsonl"
TOOL_LOG_FILE = LOG_DIR / "tool_calls.jsonl"


def _to_jsonable(value: Any) -> Any:
    """尽量把常见对象转换成 JSON 友好结构，失败时退化为字符串。"""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def _jsonl_logger(name: str, path: Path) -> Logger:
    """按需创建独立 JSONL 文件 logger，避免与控制台日志混杂。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _write_jsonl(logger_name: str, path: Path, payload: dict[str, Any]) -> None:
    logger = _jsonl_logger(logger_name, path)
    logger.info(json.dumps(payload, ensure_ascii=False, default=str))


def now_ms() -> float:
    """返回单调时钟时间，用于跨平台计算耗时。"""
    return time.perf_counter()


def elapsed_ms(start: float) -> float:
    """把单调时钟差值转成毫秒，保留两位小数。"""
    return round((time.perf_counter() - start) * 1000, 2)


def log_agent_call(
    *,
    agent_name: str,
    label: str,
    prompt: Any,
    output: Any = None,
    status: str = "success",
    duration_ms: float | None = None,
    error: BaseException | None = None,
) -> None:
    """记录一次 Agent/LLM 调用，写入独立 agent_calls.jsonl。"""
    payload = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "agent": agent_name,
        "label": label,
        "status": status,
        "duration_ms": duration_ms,
        "input": _to_jsonable(prompt),
        "output": _to_jsonable(output),
    }
    if error is not None:
        payload["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    _write_jsonl("agent.call", AGENT_LOG_FILE, payload)


def log_tool_call(
    *,
    agent_name: str,
    tool_name: str,
    args: Any,
    output: Any = None,
    status: str = "success",
    duration_ms: float | None = None,
    user_id: int | str | None = None,
    session_id: str | None = None,
    attempts: int | None = None,
    retry_count: int | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    error: BaseException | None = None,
) -> None:
    """记录一次 MCP Tool 调用，写入独立 tool_calls.jsonl。"""
    finished_at = finished_at or datetime.now().isoformat(timespec="seconds")
    payload = {
        "time": finished_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "agent": agent_name,
        "tool": tool_name,
        "user_id": user_id,
        "session_id": session_id,
        "status": status,
        "attempts": attempts,
        "retry_count": retry_count,
        "duration_ms": duration_ms,
        "input": _to_jsonable(args),
        "output": _to_jsonable(output),
    }
    if error is not None:
        payload["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    _write_jsonl("tool.call", TOOL_LOG_FILE, payload)
