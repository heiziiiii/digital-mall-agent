"""MCP 工具包装层测试：高风险写操作交由 PydanticAI 原生审批流程。"""

from __future__ import annotations

import asyncio

from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.approval_required import ApprovalRequiredToolset
from pydantic_ai.tools import ToolDefinition

from agent.tools.mcp_client import (
    USER_ID_TOOLS,
    WRITE_APPROVAL_TOOLS,
    ContextCustomerToolset,
    _MODEL_ARGS_VALIDATOR,
    _hide_user_id_param,
    toolset_for,
)


class _FakeInner:
    """伪造被包装的底层工具集，避免真连 MCP 服务端。"""

    def __init__(self, tools: dict[str, ToolsetTool]) -> None:
        self._tools = tools

    def filtered(self, predicate):
        return _FakeInner({name: tool for name, tool in self._tools.items() if predicate(None, tool.tool_def)})

    async def get_tools(self, ctx):
        return self._tools


def _tool(name: str) -> ToolsetTool:
    tool_def = ToolDefinition(
        name=name, parameters_json_schema={"type": "object", "properties": {}}
    )
    return ToolsetTool(
        toolset=None,
        tool_def=tool_def,
        max_retries=1,
        args_validator=_MODEL_ARGS_VALIDATOR,
        args_validator_func=None,
    )


def test_user_id_tools_cover_private_mcp_tools() -> None:
    assert {
        "queryOrder",
        "trackLogistics",
        "listCustomerOrders",
        "queryAfterSale",
        "listOrderAfterSales",
        "listCustomerAfterSales",
        "createAfterSale",
        "createHumanService",
        "getCustomerById",
    }.issubset(USER_ID_TOOLS)


def test_user_id_param_is_hidden_from_model_schema() -> None:
    tool_def = ToolDefinition(
        name="queryOrder",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "userId": {"type": "integer"},
                "orderNo": {"type": "string"},
            },
            "required": ["userId", "orderNo"],
        },
    )

    hidden = _hide_user_id_param(tool_def)

    assert "userId" not in hidden.parameters_json_schema["properties"]
    assert hidden.parameters_json_schema["required"] == ["orderNo"]


def test_create_after_sale_is_registered_as_write_approval_tool() -> None:
    assert "createAfterSale" in WRITE_APPROVAL_TOOLS
    assert "createHumanService" in WRITE_APPROVAL_TOOLS


def test_context_toolset_no_longer_marks_write_tool_manually_unapproved() -> None:
    inner = _FakeInner(
        {
            "createAfterSale": _tool("createAfterSale"),
            "createHumanService": _tool("createHumanService"),
            "queryOrder": _tool("queryOrder"),
        }
    )
    toolset = ContextCustomerToolset(inner, agent_name="order")

    tools = asyncio.run(toolset.get_tools(None))

    # 审批由 toolset.approval_required(...) 在调用阶段触发，不再手动改 ToolDefinition.kind。
    assert tools["createAfterSale"].tool_def.kind == "function"
    assert tools["queryOrder"].tool_def.kind == "function"


def test_toolset_for_wraps_with_pydantic_ai_approval_required(monkeypatch) -> None:
    inner = _FakeInner(
        {"createAfterSale": _tool("createAfterSale"), "queryOrder": _tool("queryOrder")}
    )
    monkeypatch.setattr("agent.tools.mcp_client.get_mcp_server", lambda: inner)

    toolset = toolset_for("order")

    assert isinstance(toolset, ApprovalRequiredToolset)
    assert toolset.approval_required_func(None, ToolDefinition(name="createAfterSale"), {})
    assert toolset_for("service").approval_required_func(None, ToolDefinition(name="createHumanService"), {})
    assert not toolset.approval_required_func(None, ToolDefinition(name="queryOrder"), {})
