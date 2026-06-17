"""MCP 客户端：直接使用 MCP 工具集，仅做专家隔离与认证身份注入。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai.mcp import MCPServerSSE
from pydantic_ai.toolsets import AbstractToolset, WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.tools import RunContext, ToolDefinition

from agent.config import get_settings
from agent.utils.observability import elapsed_ms, log_tool_call, now_ms

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


@dataclass(frozen=True)
class SpecialistDeps:
    """专家 Agent 运行上下文。"""

    customer_id: int | None = None


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
        start = now_ms()
        # 写操作经框架审批通过后才会回调到此真正落库，记录的即最终（含用户修改后）参数。
        if name in USER_ID_TOOLS:
            customer_id = ctx.deps.customer_id
            if customer_id is None:
                exc = ValueError("当前未获取到认证客户ID，无法调用当前用户相关工具。")
                log_tool_call(
                    agent_name=self.agent_name,
                    tool_name=name,
                    args=tool_args,
                    status="error",
                    duration_ms=elapsed_ms(start),
                    error=exc,
                )
                raise exc
            tool_args = {**tool_args, "userId": customer_id}
        try:
            result = await super().call_tool(name, tool_args, ctx, tool)
        except Exception as exc:
            log_tool_call(
                agent_name=self.agent_name,
                tool_name=name,
                args=tool_args,
                status="error",
                duration_ms=elapsed_ms(start),
                error=exc,
            )
            raise
        log_tool_call(
            agent_name=self.agent_name,
            tool_name=name,
            args=tool_args,
            output=result,
            duration_ms=elapsed_ms(start),
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
