"""MCP 客户端：直接使用 MCP 工具集，仅做专家隔离与认证身份注入。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai.mcp import MCPServerSSE
from pydantic_ai.toolsets import AbstractToolset, WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.tools import RunContext, ToolDefinition

from agent.config import get_settings
from agent.utils.observability import elapsed_ms, log_tool_call, now_ms

TOOL_RETRY_TIMES = 3
_RETRY_BACKOFF_SECONDS = (0.05, 0.1, 0.2)

USER_ID_TOOLS = frozenset(
    {
        "queryOrder",
        "trackLogistics",
        "listCustomerOrders",
        "createOrder",
        "queryAfterSale",
        "listOrderAfterSales",
        "listCustomerAfterSales",
        "createAfterSale",
        "createHumanService",
    }
)
# 高风险写操作：交由 PydanticAI 原生 approval_required + DeferredToolRequests 流程。
# 模型发起调用时不直接执行，而是挂起等待用户审核确认/修改后再落库。新增写工具登记到此即可。
WRITE_APPROVAL_TOOLS = frozenset({"createOrder", "createAfterSale", "createHumanService"})
_MODEL_ARGS_VALIDATOR = TypeAdapter(dict[str, Any]).validator

_AGENT_TOOLS = {
    "product": {"searchProducts", "getProductDetail"},
    "order": {
        "queryOrder",
        "trackLogistics",
        "listCustomerOrders",
        "createOrder",
        "queryAfterSale",
        "listOrderAfterSales",
        "listCustomerAfterSales",
        "createAfterSale",
    },
    "tech": {"searchKnowledge"},
    "service": {"createHumanService"},
}

_AGENT_FALLBACKS = {
    "product": "放宽或修正商品检索条件后再次调用；如果仍失败，请基于已知需求向用户补充询问预算、品类、品牌或核心用途。",
    "order": "核对订单号、售后单号和当前登录身份后再次调用；如果仍失败，请改用订单/售后列表工具定位记录，或提示用户稍后重试并避免承诺已执行写操作。",
    "tech": "换用更明确的故障现象、设备型号或关键词再次检索知识库；如果仍失败，请给出通用安全排查步骤并建议联系人工客服。",
    "service": "核对人工服务申请原因及关联订单号后再次调用；如果仍失败，请提示用户稍后重试或通过人工入口提交。",
    "unknown": "修正参数后再次调用；如果仍失败，请向用户说明当前工具暂不可用并请求补充关键信息。",
}

def _normalize_product_search_args(tool_args: dict[str, Any]) -> dict[str, Any]:
    """确保商品检索总带有面向 RAG 的目标产品短语。"""
    normalized = dict(tool_args)
    query = tool_args.get("query")
    if isinstance(query, str) and query.strip():
        return normalized

    terms: list[str] = []
    brand = tool_args.get("brand")
    category = tool_args.get("category")
    min_price = tool_args.get("minPrice")
    max_price = tool_args.get("maxPrice")

    if isinstance(brand, str) and brand.strip():
        terms.append(brand.strip())
    if min_price is not None and max_price is None:
        terms.append("高端")
    if max_price is not None and min_price is None:
        terms.append("高性价比")
    if isinstance(category, str) and category.strip():
        terms.append(category.strip())

    fallback_query = "".join(terms).strip()
    if not fallback_query:
        fallback_query = "数码商品"
    normalized["query"] = (
        f"{fallback_query}，请按用户选购画像召回候选商品，综合考虑价格档位、核心卖点、"
        "使用场景、库存和用户不重视的配置，返回可供后续筛选比较的商品。"
    )
    return _normalize_product_search_args(normalized)


@dataclass(frozen=True)
class SpecialistDeps:
    """专家 Agent 运行上下文。"""

    customer_id: int | None = None
    session_id: str | None = None


@lru_cache(maxsize=1)
def get_mcp_server() -> MCPServerSSE:
    """构建并缓存 MCP 服务器工具集（SSE 传输）。"""
    settings = get_settings()
    return MCPServerSSE(url=settings.mcp_server_url)


def _hide_user_id_param(tool_def: ToolDefinition) -> ToolDefinition:
    """当前用户类工具的 userId 只允许由运行上下文注入。"""
    if tool_def.name not in USER_ID_TOOLS:
        return tool_def

    schema = deepcopy(tool_def.parameters_json_schema)
    properties = schema.get("properties")
    if isinstance(properties, dict):
        properties.pop("userId", None)

    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [item for item in required if item != "userId"]

    return replace(tool_def, parameters_json_schema=schema)


def _json_type_matches(value: Any, expected: str) -> bool:
    """覆盖常见 JSON schema 类型，避免在调用远端前提交明显错误参数。"""
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _validate_tool_args(tool_def: ToolDefinition, tool_args: dict[str, Any]) -> None:
    """按工具 JSON schema 做轻量参数校验：必填、类型、枚举。"""
    schema = tool_def.parameters_json_schema or {}
    required = schema.get("required")
    if isinstance(required, list):
        missing = [
            name
            for name in required
            if name not in tool_args
            or tool_args[name] is None
            or (isinstance(tool_args[name], str) and not tool_args[name].strip())
        ]
        if missing:
            raise ValueError(f"缺少必填参数：{', '.join(map(str, missing))}")

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return

    errors: list[str] = []
    for name, spec in properties.items():
        if name not in tool_args or not isinstance(spec, dict):
            continue
        value = tool_args[name]
        expected = spec.get("type")
        expected_types = expected if isinstance(expected, list) else [expected]
        expected_types = [item for item in expected_types if isinstance(item, str)]
        if expected_types and not any(_json_type_matches(value, item) for item in expected_types):
            errors.append(f"{name} 类型应为 {'/'.join(expected_types)}")
            continue
        enum_values = spec.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            errors.append(f"{name} 应为 {enum_values} 之一")
    if errors:
        raise ValueError("；".join(errors))


def _tool_failure_result(
    *,
    agent_name: str,
    tool_name: str,
    error: Exception,
    attempts: int,
    validation_failed: bool = False,
) -> dict[str, Any]:
    """返回给模型的标准失败结果，让 Agent 可继续修参、补问或降级答复。"""
    prefix = "工具参数校验失败" if validation_failed else "工具调用失败"
    fallback = _AGENT_FALLBACKS.get(agent_name, _AGENT_FALLBACKS["unknown"])
    message = (
        f"{prefix}，错误信息是：{error}。"
        f"请分析原因，修正参数后再次调用，或者{fallback}"
    )
    return {
        "ok": False,
        "tool_failed": True,
        "tool": tool_name,
        "agent": agent_name,
        "attempts": attempts,
        "error": str(error),
        "message": message,
        "fallback": fallback,
    }


@dataclass
class ContextCustomerToolset(WrapperToolset[SpecialistDeps]):
    """MCP 工具集薄包装：隐藏并注入 userId，不重写 MCP 工具本体。"""

    agent_name: str = "unknown"

    async def get_tools(self, ctx: RunContext[SpecialistDeps]) -> dict[str, ToolsetTool[SpecialistDeps]]:
        tools = await super().get_tools(ctx)
        prepared: dict[str, ToolsetTool[SpecialistDeps]] = {}
        for name, tool in tools.items():
            if name in USER_ID_TOOLS:
                tool = replace(
                    tool,
                    tool_def=_hide_user_id_param(tool.tool_def),
                    args_validator=_MODEL_ARGS_VALIDATOR,
                    args_validator_func=None,
                )
            prepared[name] = tool
        return prepared

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[SpecialistDeps],
        tool: ToolsetTool[SpecialistDeps],
    ) -> Any:
        deps = getattr(ctx, "deps", None)
        if self.agent_name == "product" and name == "searchProducts":
            tool_args = _normalize_product_search_args(tool_args)

        start = now_ms()
        started_at = datetime.now().isoformat(timespec="seconds")
        customer_id = getattr(deps, "customer_id", None)
        session_id = getattr(deps, "session_id", None)
        try:
            _validate_tool_args(tool.tool_def, tool_args)
        except Exception as exc:
            log_tool_call(
                agent_name=self.agent_name,
                tool_name=name,
                args=tool_args,
                status="error",
                duration_ms=elapsed_ms(start),
                user_id=customer_id,
                session_id=session_id,
                attempts=0,
                retry_count=0,
                started_at=started_at,
                error=exc,
            )
            return _tool_failure_result(
                agent_name=self.agent_name,
                tool_name=name,
                error=exc,
                attempts=0,
                validation_failed=True,
            )

        # 写操作经框架审批通过后才会回调到此真正落库，记录的即最终（含用户修改后）参数。
        if name in USER_ID_TOOLS:
            if customer_id is None:
                exc = ValueError("当前未获取到认证客户ID，无法调用当前用户相关工具。")
                log_tool_call(
                    agent_name=self.agent_name,
                    tool_name=name,
                    args=tool_args,
                    status="error",
                    duration_ms=elapsed_ms(start),
                    user_id=customer_id,
                    session_id=session_id,
                    attempts=0,
                    retry_count=0,
                    started_at=started_at,
                    error=exc,
                )
                return _tool_failure_result(
                    agent_name=self.agent_name,
                    tool_name=name,
                    error=exc,
                    attempts=0,
                    validation_failed=True,
                )
            tool_args = {**tool_args, "userId": customer_id}

        result: Any = None
        last_error: Exception | None = None
        total_attempts = 1 + TOOL_RETRY_TIMES
        for attempt in range(1, total_attempts + 1):
            try:
                result = await super().call_tool(name, tool_args, ctx, tool)
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 - 工具层统一重试并返回可恢复失败
                last_error = exc
                if attempt <= TOOL_RETRY_TIMES:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
        if last_error is not None:
            log_tool_call(
                agent_name=self.agent_name,
                tool_name=name,
                args=tool_args,
                status="error",
                duration_ms=elapsed_ms(start),
                user_id=customer_id,
                session_id=session_id,
                attempts=total_attempts,
                retry_count=TOOL_RETRY_TIMES,
                started_at=started_at,
                error=last_error,
            )
            return _tool_failure_result(
                agent_name=self.agent_name,
                tool_name=name,
                error=last_error,
                attempts=total_attempts,
            )

        log_tool_call(
            agent_name=self.agent_name,
            tool_name=name,
            args=tool_args,
            output=result,
            duration_ms=elapsed_ms(start),
            user_id=customer_id,
            session_id=session_id,
            attempts=attempt,
            retry_count=max(0, attempt - 1),
            started_at=started_at,
        )
        return result


def toolset_for(agent: str) -> AbstractToolset[SpecialistDeps]:
    """按专家名称返回 MCP 原生工具集的过滤视图。"""
    allowed = _AGENT_TOOLS[agent]
    toolset = ContextCustomerToolset(
        get_mcp_server().filtered(lambda ctx, tool_def: tool_def.name in allowed),
        agent_name=agent,
    )
    return toolset.approval_required(
        lambda _ctx, tool_def, _tool_args: tool_def.name in WRITE_APPROVAL_TOOLS
    )
