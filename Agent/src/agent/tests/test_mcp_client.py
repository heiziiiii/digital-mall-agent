"""MCP 工具包装层测试：高风险写操作交由 PydanticAI 原生审批流程。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.approval_required import ApprovalRequiredToolset
from pydantic_ai.tools import ToolDefinition

from agent.tools.mcp_client import (
    TOOL_RETRY_TIMES,
    USER_ID_TOOLS,
    WRITE_APPROVAL_TOOLS,
    ContextCustomerToolset,
    SpecialistDeps,
    _MODEL_ARGS_VALIDATOR,
    _hide_user_id_param,
    toolset_for,
)


class _FakeInner:
    """伪造被包装的底层工具集，避免真连 MCP 服务端。"""

    def __init__(self, tools: dict[str, ToolsetTool], failures: int = 0) -> None:
        self._tools = tools
        self.failures = failures
        self.calls: list[dict[str, Any]] = []

    def filtered(self, predicate):
        return _FakeInner({name: tool for name, tool in self._tools.items() if predicate(None, tool.tool_def)})

    async def get_tools(self, ctx):
        return self._tools

    async def call_tool(self, name, tool_args, ctx, tool):
        self.calls.append({"name": name, "args": dict(tool_args)})
        if len(self.calls) <= self.failures:
            raise RuntimeError("远端 MCP 临时不可用")
        return {"ok": True, "name": name, "args": tool_args}


@dataclass
class _Ctx:
    deps: SpecialistDeps


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


def _schema_tool(name: str, schema: dict) -> ToolsetTool:
    tool_def = ToolDefinition(name=name, parameters_json_schema=schema)
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
        "createOrder",
        "queryAfterSale",
        "listOrderAfterSales",
        "listCustomerAfterSales",
        "createAfterSale",
        "createHumanService",
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
    assert "createOrder" in WRITE_APPROVAL_TOOLS
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
        {
            "createOrder": _tool("createOrder"),
            "createAfterSale": _tool("createAfterSale"),
            "queryOrder": _tool("queryOrder"),
        }
    )
    monkeypatch.setattr("agent.tools.mcp_client.get_mcp_server", lambda: inner)

    toolset = toolset_for("order")

    assert isinstance(toolset, ApprovalRequiredToolset)
    assert toolset.approval_required_func(None, ToolDefinition(name="createOrder"), {})
    assert toolset.approval_required_func(None, ToolDefinition(name="createAfterSale"), {})
    assert toolset_for("service").approval_required_func(None, ToolDefinition(name="createHumanService"), {})
    assert not toolset.approval_required_func(None, ToolDefinition(name="queryOrder"), {})


def test_tool_call_validates_args_before_remote_call() -> None:
    inner = _FakeInner(
        {
            "searchKnowledge": _schema_tool(
                "searchKnowledge",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        }
    )
    toolset = ContextCustomerToolset(inner, agent_name="tech")
    tool = inner._tools["searchKnowledge"]

    result = asyncio.run(
        toolset.call_tool("searchKnowledge", {}, _Ctx(SpecialistDeps()), tool)
    )

    assert result["tool_failed"] is True
    assert result["attempts"] == 0
    assert "工具参数校验失败" in result["message"]
    assert "缺少必填参数" in result["error"]
    assert inner.calls == []


def test_tool_call_retries_three_times_then_returns_agent_fallback() -> None:
    inner = _FakeInner({"searchKnowledge": _tool("searchKnowledge")}, failures=99)
    toolset = ContextCustomerToolset(inner, agent_name="tech")
    tool = inner._tools["searchKnowledge"]

    result = asyncio.run(
        toolset.call_tool("searchKnowledge", {"query": "蓝屏"}, _Ctx(SpecialistDeps()), tool)
    )

    assert len(inner.calls) == 1 + TOOL_RETRY_TIMES
    assert result["tool_failed"] is True
    assert result["attempts"] == 1 + TOOL_RETRY_TIMES
    assert "工具调用失败，错误信息是：远端 MCP 临时不可用" in result["message"]
    assert "通用安全排查步骤" in result["fallback"]


def test_user_id_tool_failure_return_mentions_order_fallback_without_remote_call() -> None:
    inner = _FakeInner({"queryOrder": _tool("queryOrder")})
    toolset = ContextCustomerToolset(inner, agent_name="order")
    tool = inner._tools["queryOrder"]

    result = asyncio.run(
        toolset.call_tool("queryOrder", {"orderNo": "O1"}, _Ctx(SpecialistDeps()), tool)
    )

    assert result["tool_failed"] is True
    assert result["attempts"] == 0
    assert "当前未获取到认证客户ID" in result["error"]
    assert "核对订单号、售后单号和当前登录身份" in result["fallback"]
    assert inner.calls == []


def test_tool_call_succeeds_after_retry() -> None:
    inner = _FakeInner({"searchProducts": _tool("searchProducts")}, failures=2)
    toolset = ContextCustomerToolset(inner, agent_name="product")
    tool = inner._tools["searchProducts"]

    result = asyncio.run(
        toolset.call_tool("searchProducts", {"query": "手机"}, _Ctx(SpecialistDeps()), tool)
    )

    assert len(inner.calls) == 3
    assert result["ok"] is True


def test_product_search_adds_target_query_for_rag_when_missing() -> None:
    inner = _FakeInner({"searchProducts": _tool("searchProducts")})
    toolset = ContextCustomerToolset(inner, agent_name="product")
    tool = inner._tools["searchProducts"]

    result = asyncio.run(
        toolset.call_tool(
            "searchProducts",
            {"brand": "三星", "category": "手机", "limit": 3, "sortBy": "relevance"},
            _Ctx(SpecialistDeps()),
            tool,
        )
    )

    assert result["ok"] is True
    assert inner.calls[0]["args"]["query"].startswith("三星手机")
    assert "选购画像" in inner.calls[0]["args"]["query"]
    assert "使用场景" in inner.calls[0]["args"]["query"]
    assert "用户想" not in inner.calls[0]["args"]["query"]


def test_tool_call_trace_includes_user_session_and_retry_stats(monkeypatch) -> None:
    records: list[dict[str, Any]] = []
    inner = _FakeInner({"searchProducts": _tool("searchProducts")}, failures=1)
    toolset = ContextCustomerToolset(inner, agent_name="product")
    tool = inner._tools["searchProducts"]
    monkeypatch.setattr(
        "agent.tools.mcp_client.log_tool_call",
        lambda **kwargs: records.append(kwargs),
    )

    result = asyncio.run(
        toolset.call_tool(
            "searchProducts",
            {"query": "手机"},
            _Ctx(SpecialistDeps(customer_id=7, session_id="s1")),
            tool,
        )
    )

    assert result["ok"] is True
    assert len(records) == 1
    assert records[0]["agent_name"] == "product"
    assert records[0]["tool_name"] == "searchProducts"
    assert records[0]["user_id"] == 7
    assert records[0]["session_id"] == "s1"
    assert records[0]["attempts"] == 2
    assert records[0]["retry_count"] == 1
    assert records[0]["duration_ms"] >= 0
    assert records[0]["started_at"]
