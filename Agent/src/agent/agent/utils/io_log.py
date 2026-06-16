"""统一打印每次访问/调用的输入和返回。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _to_jsonable(value: Any) -> Any:
    """尽量把 Pydantic/普通对象转换成可读 JSON，失败时退化为字符串。"""
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


def print_io(label: str, input_data: Any, output_data: Any) -> None:
    """按固定格式打印输入与返回，便于本地调试和接口联调。"""
    payload = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "input": _to_jsonable(input_data),
        "output": _to_jsonable(output_data),
    }
    print(
        "[访问输入返回] "
        + json.dumps(payload, ensure_ascii=False, default=str),
        flush=True,
    )
