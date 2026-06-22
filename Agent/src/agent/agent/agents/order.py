"""订单售后专家：订单、物流、售后查询与售后创建。

订单/物流/售后查询为只读操作；创建售后单是高风险写操作，已交由 PydanticAI 原生
deferred 审批流程（见 ``agent.tools.mcp_client.WRITE_APPROVAL_TOOLS``）：模型发起
``createAfterSale`` 时本次 run 不执行该工具，而是返回 ``DeferredToolRequests``，
由主流程挂起、交用户审核确认/修改后再 :meth:`OrderAgent.resume` 续跑落库。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.usage import UsageLimits

from agent.hooks import timed_agent_run
from agent.llm.model import get_expert_model as get_model
from agent.prompts.loader import render_skill
from agent.tools.mcp_client import SpecialistDeps, toolset_for

if TYPE_CHECKING:
    from agent.customer_agent import AgentContext

_REQUEST_LIMIT = 8
NAME = "order"
LABEL = "订单售后"


class OrderServiceOutput(BaseModel):
    """订单售后专家标准输出结构。"""

    reply_type: Literal["order_service"] = "order_service"
    answer: str = Field(
        default="",
        min_length=1,
        description="面向用户的订单、物流或售后答复；必须基于工具结果，不得承诺未经确认的写操作结果",
    )


@dataclass
class PendingApproval:
    """模型发起、等待用户审核确认的高风险写操作。"""

    tool: str
    call_id: str
    args: dict[str, Any]


@dataclass
class SpecialistRunResult:
    """专家一次运行的结果：要么是最终文本，要么是待用户审核确认的写操作。"""

    text: str = ""
    pending: PendingApproval | None = None
    # 待审批时保存 PydanticAI 消息历史，供 resume 续跑（进程内存储）。
    messages: Any = None

    @property
    def awaiting_review(self) -> bool:
        return self.pending is not None


class OrderAgent:
    """订单售后专家能力：构造认证上下文并执行订单/售后工具调用。"""

    name = NAME
    label = LABEL

    def __init__(self) -> None:
        self._agent: Agent | None = None

    def build_context(
        self,
        ctx: AgentContext,
        query: str = "",
        previous_results: str = "",
    ) -> str:
        """构造订单专家上下文，只接收规划任务和依赖结果；认证身份通过 deps 传给工具。"""
        lines: list[str] = []
        if previous_results:
            lines.append(f"【前序处理结果】\n{previous_results}")
        lines.append(f"【任务上下文】{query or ctx.user_input}")
        return "\n".join(lines)

    def deps(self, ctx: AgentContext) -> SpecialistDeps:
        """订单工具需要服务端认证身份。"""
        return SpecialistDeps(customer_id=ctx.customer_id, session_id=ctx.session_id)

    def _build_agent(self) -> Agent:
        """构造并复用订单专家 Agent；output_type 含 DeferredToolRequests 以允许返回待审批写操作。"""
        if self._agent is None:
            model = get_model()
            if model is None:
                raise RuntimeError(f"LLM 未配置（缺少 OPENAI_API_KEY），无法执行：{LABEL}")
            self._agent = Agent(
                model,
                output_type=[OrderServiceOutput, DeferredToolRequests],
                deps_type=SpecialistDeps,
                system_prompt=(
                    f"{render_skill('order')}\n\n"
                    "## 输出压缩要求\n"
                    "- answer 只说明已核实事实、当前状态和下一步动作，避免重复订单字段和内部流程。\n"
                    "- 查询类答复控制在 120 字左右；候选列表只列必要识别信息。"
                ),
                toolsets=[toolset_for("order")],
            )
        return self._agent

    async def run(
        self, context: str, agent_deps: SpecialistDeps | None = None
    ) -> SpecialistRunResult:
        """运行订单售后专家。返回最终文本，或待用户审核确认的写操作。"""
        agent = self._build_agent()
        async with agent:
            result = await timed_agent_run(
                agent,
                context,
                LABEL,
                deps=agent_deps or SpecialistDeps(),
                usage_limits=UsageLimits(request_limit=_REQUEST_LIMIT),
            )
        return self._wrap(result)

    async def resume(
        self,
        *,
        messages: Any,
        call_id: str,
        approved: bool,
        args: dict[str, Any] | None = None,
        message: str = "",
        regenerate: bool = False,
        agent_deps: SpecialistDeps | None = None,
    ) -> SpecialistRunResult:
        """用户审核确认/修改后续跑：注入审批结果，让模型基于真实工具结果生成最终答复。

        - ``approved=True``：用 ``ToolApproved(override_args=args)`` 落库（args 为用户修改后的
          参数，为空则沿用模型原参数）。
        - ``approved=False, regenerate=False``：用 ``ToolDenied`` 取消，模型据此续写"已取消"。
        - ``approved=False, regenerate=True``：把用户意见作为 denied message 注入，要求模型
          根据意见重新生成待确认方案；如仍需创建售后，可再次返回 DeferredToolRequests。
        """
        if approved:
            decision = ToolApproved(override_args=args or None)
        elif regenerate:
            feedback = message or "用户未批准当前售后方案，请重新判断并生成新的待确认方案。"
            decision = ToolDenied(
                message=(
                    "用户未批准当前售后方案，要求按以下意见重新生成："
                    f"{feedback}。请不要直接结束流程；若仍需创建售后单，请重新发起创建售后申请。"
                )
            )
        else:
            decision = ToolDenied(message=message or "用户取消了该售后操作。")

        agent = self._build_agent()
        async with agent:
            result = await agent.run(
                message_history=messages,
                deferred_tool_results=DeferredToolResults(approvals={call_id: decision}),
                deps=agent_deps or SpecialistDeps(),
                usage_limits=UsageLimits(request_limit=_REQUEST_LIMIT),
            )
        return self._wrap(result)

    @staticmethod
    def _wrap(result: Any) -> SpecialistRunResult:
        """把 PydanticAI 运行结果归一为 SpecialistRunResult。"""
        output = result.output
        if isinstance(output, DeferredToolRequests) and output.approvals:
            call = output.approvals[0]
            return SpecialistRunResult(
                pending=PendingApproval(
                    tool=call.tool_name,
                    call_id=call.tool_call_id,
                    args=call.args_as_dict(),
                ),
                messages=result.all_messages(),
            )
        if isinstance(output, OrderServiceOutput):
            return SpecialistRunResult(text=output.answer.strip())
        return SpecialistRunResult(text=str(output))
