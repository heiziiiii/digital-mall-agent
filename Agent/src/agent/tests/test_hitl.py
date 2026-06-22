"""HITL（高风险写操作用户审核确认）主流程测试：挂起 → 注入决定 → 续跑落库。

通过伪造订单专家避免触发 LLM/MCP，断言聚焦于 CustomerAgent.iter_run 的中断/恢复编排。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agent.agents.hitl_guide import HitlGuideOutput
from pydantic_ai.messages import ToolReturnPart

from agent.agents.order import OrderAgent, OrderServiceOutput, PendingApproval, SpecialistRunResult
from agent.agents.orchestrator import DecisionResult
from agent.customer_agent import AgentContext, CustomerAgent, Task


class _FakeOrchestrator:
    def __init__(self, decision: DecisionResult) -> None:
        self.decision = decision

    async def decide(self, _user_input: str) -> DecisionResult:
        return self.decision


class _FakeSummarize:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def run(self, _payload: str) -> str:
        return self.answer


class _FakeHitlGuide:
    async def run(
        self,
        *,
        tool,
        user_input,
        args,
        required_fields,
        missing_fields,
        default_instruction,
        context=None,
    ) -> HitlGuideOutput:
        reason = str(args.get("reason") or "")
        if reason.startswith("用户"):
            reason = reason.replace("用户", "我", 1)
        elif reason and not reason.startswith("我"):
            reason = f"我想反馈：{reason}"
        if "reason" in missing_fields:
            reason = ""
        return HitlGuideOutput(
            reason=reason,
            guide_message=f"{tool} 表单引导",
            instruction=f"{tool} 表单说明",
        )


class _BadMissingReasonGuide:
    async def run(
        self,
        *,
        tool,
        user_input,
        args,
        required_fields,
        missing_fields,
        default_instruction,
        context=None,
    ) -> HitlGuideOutput:
        return HitlGuideOutput(
            reason="我想处理订单 O202606040002 的退货问题",
            guide_message="请补充退货原因",
            instruction=default_instruction,
        )


class _FakeOrder(OrderAgent):
    """首次 run 返回待审批写操作；resume 记录注入的决定并返回最终文本。"""

    def __init__(self, resumed_text: str) -> None:
        self._resumed_text = resumed_text
        self.resume_calls: list[dict] = []

    async def run(self, context, agent_deps=None) -> SpecialistRunResult:
        return SpecialistRunResult(
            pending=PendingApproval(
                tool="createAfterSale",
                call_id="call_1",
                args={"orderNo": "O1", "type": 1, "reason": "屏幕碎裂"},
            ),
            messages=["__history__"],
        )

    async def resume(
        self,
        *,
        messages,
        call_id,
        approved,
        args=None,
        message="",
        regenerate=False,
        agent_deps=None,
    ) -> str:
        self.resume_calls.append(
            {
                "messages": messages,
                "call_id": call_id,
                "approved": approved,
                "args": args,
                "message": message,
                "regenerate": regenerate,
            }
        )
        return self._resumed_text


class _RegeneratingOrder(_FakeOrder):
    """第一次 resume 按用户意见重新生成待确认调用，第二次确认后完成。"""

    async def resume(
        self,
        *,
        messages,
        call_id,
        approved,
        args=None,
        message="",
        regenerate=False,
        agent_deps=None,
    ) -> str | SpecialistRunResult:
        self.resume_calls.append(
            {
                "messages": messages,
                "call_id": call_id,
                "approved": approved,
                "args": args,
                "message": message,
                "regenerate": regenerate,
            }
        )
        if regenerate:
            return SpecialistRunResult(
                pending=PendingApproval(
                    tool="createAfterSale",
                    call_id="call_2",
                    args={
                        "orderNo": "O1",
                        "type": 3,
                        "reason": "买错了",
                    },
                ),
                messages=["__history_2__"],
            )
        return self._resumed_text


def _build_agent(order: _FakeOrder, answer: str = "最终回答") -> CustomerAgent:
    decision = DecisionResult(
        intent="order", tasks=[Task(agent="order", priority=10)], planning_mode="planned"
    )
    return CustomerAgent(
        orchestrator=_FakeOrchestrator(decision),
        order_agent=order,
        summarize_agent=_FakeSummarize(answer),
        hitl_guide_agent=_FakeHitlGuide(),
        memory_loader=lambda ctx: None,
        memory_saver=lambda ctx: None,
    )


def _drive_to_review(gen):
    """推进生成器直到 awaiting_review 事件并返回它。"""
    event = next(gen)
    while event["stage"] != "awaiting_review":
        event = next(gen)
    return event


def test_after_sale_suspends_with_pending_action() -> None:
    order = _FakeOrder("售后单 A123 已创建")
    ctx = AgentContext(user_input="我要退货", session_id="s1", customer_id=7)

    gen = _build_agent(order).iter_run(ctx)
    review = _drive_to_review(gen)

    pending = review["update"]["pending_action"]
    assert pending["tool"] == "createAfterSale"
    assert pending["call_id"] == "call_1"
    assert pending["kind"] == "tool_approval"
    assert pending["state"] == "awaiting_review"
    assert pending["args"]["orderNo"] == "O1"
    assert pending["args"]["reason"] == "我想反馈：屏幕碎裂"
    assert pending["known_fields"]["orderNo"] == "O1"
    assert pending["known_fields"]["reason"] == "我想反馈：屏幕碎裂"
    assert pending["required_fields"] == ["orderNo", "type", "reason"]
    assert pending["guide_message"] == "createAfterSale 表单引导"
    # 挂起期间尚未续跑、尚未生成最终答复
    assert order.resume_calls == []
    assert ctx.pending_review is not None


def test_missing_reason_stays_empty_even_if_guide_generates_placeholder() -> None:
    decision = DecisionResult(
        intent="order", tasks=[], planning_mode="planned"
    )
    agent = CustomerAgent(
        orchestrator=_FakeOrchestrator(decision),
        summarize_agent=_FakeSummarize("最终回答"),
        hitl_guide_agent=_BadMissingReasonGuide(),
        memory_loader=lambda ctx: None,
        memory_saver=lambda ctx: None,
    )
    ctx = AgentContext(user_input="我要退最近那一笔订单苹果", session_id="s1", customer_id=7)
    output = SpecialistRunResult(
        pending=PendingApproval(
            tool="createAfterSale",
            call_id="call_missing_reason",
            args={"orderNo": "O202606040002", "type": 3, "reason": ""},
        ),
        messages=["__history__"],
    )

    pending = asyncio.run(agent._pending_action("order", output, ctx))

    assert pending["args"]["reason"] == ""
    assert "reason" in pending["missing_fields"]
    assert "reason" not in pending["known_fields"]
    assert pending["guide_message"] == "请补充退货原因"


def test_human_service_suspends_with_pending_action() -> None:
    decision = DecisionResult(
        intent="order",
        tasks=[],
        planning_mode="planned",
        human_service={"orderNo": "O1", "reason": "用户要求人工处理"},
    )
    agent = CustomerAgent(
        orchestrator=_FakeOrchestrator(decision),
        summarize_agent=_FakeSummarize("最终回答"),
        hitl_guide_agent=_FakeHitlGuide(),
        memory_loader=lambda ctx: None,
        memory_saver=lambda ctx: None,
    )

    async def fake_start(ctx, plan):
        return SpecialistRunResult(
            pending=PendingApproval(
                tool="createHumanService",
                call_id="call_human",
                args=plan,
            ),
            messages=["__human_history__"],
        )

    agent._start_human_service_action = fake_start
    ctx = AgentContext(user_input="我要人工客服", session_id="s1", customer_id=7)

    gen = agent.iter_run(ctx)
    review = _drive_to_review(gen)

    pending = review["update"]["pending_action"]
    assert pending["tool"] == "createHumanService"
    assert pending["call_id"] == "call_human"
    assert pending["required_fields"] == ["reason"]
    assert pending["editable_fields"] == ["orderNo", "reason"]
    assert pending["known_fields"]["reason"] == "我要求人工处理"
    assert pending["guide_message"] == "createHumanService 表单引导"
    assert pending["instruction"] == "createHumanService 表单说明"


def test_human_request_directly_invokes_human_service_action() -> None:
    """编排判定需要人工服务（无专家任务）时，主流程直接走 createHumanService 待确认。

    这里不替换 ``_start_human_service_action``，验证「规划 → 直接发起人工服务工具调用」
    这条真实链路：不绕任何专家任务，直接构造 createHumanService 的待确认动作。
    """
    decision = DecisionResult(
        intent="order",
        tasks=[],
        planning_mode="planned",
        human_service={
            "reason": "用户要求转人工处理退款",
            "orderNo": "O1",
        },
    )
    agent = CustomerAgent(
        orchestrator=_FakeOrchestrator(decision),
        summarize_agent=_FakeSummarize("已为你转接人工客服"),
        hitl_guide_agent=_FakeHitlGuide(),
        memory_loader=lambda ctx: None,
        memory_saver=lambda ctx: None,
    )
    ctx = AgentContext(user_input="我要转人工", session_id="s1", customer_id=7)

    gen = agent.iter_run(ctx)
    review = _drive_to_review(gen)

    pending = review["update"]["pending_action"]
    assert pending["tool"] == "createHumanService"
    assert pending["agent"] == "tool"
    assert pending["state"] == "awaiting_review"
    assert pending["args"]["reason"] == "我要求转人工处理退款"
    assert pending["args"]["orderNo"] == "O1"
    assert pending["required_fields"] == ["reason"]
    assert pending["editable_fields"] == ["orderNo", "reason"]
    assert pending["guide_message"] == "createHumanService 表单引导"
    # 直达人工服务动作：挂起待确认，且未跑任何专家任务
    assert ctx.pending_review is not None
    assert ctx.agent_results == {}


def test_human_service_uses_order_context_for_recent_order_complaint() -> None:
    decision = DecisionResult(
        intent="order",
        tasks=[],
        planning_mode="planned",
        human_service={
            "reason": "用户明确要求投诉，需人工介入处理投诉升级流程。",
            "orderNo": "",
        },
    )
    agent = CustomerAgent(
        orchestrator=_FakeOrchestrator(decision),
        summarize_agent=_FakeSummarize("最终回答"),
        hitl_guide_agent=_FakeHitlGuide(),
        memory_loader=lambda ctx: None,
        memory_saver=lambda ctx: None,
    )
    ctx = AgentContext(user_input="我要投诉最近那笔订单", session_id="s1", customer_id=7)
    ctx.agent_results["order"] = (
        "您最近一笔订单信息如下：\n"
        "订单号：O202606040002，下单时间：2026-06-18 08:30\n"
        "商品：iPhone 14 Plus（512GB）、iPhone 13 Pro（512GB），"
        "订单状态：已支付，物流状态：运输中（中通快递 ZTO202606040002）。\n"
        "当前存在1条售后：AS202606040001（维修），状态为「已收件」。"
    )

    output = asyncio.run(agent._start_human_service_action(ctx, decision.human_service))
    pending = asyncio.run(agent._pending_action("tool", output, ctx))

    assert pending["args"]["orderNo"] == "O202606040002"
    assert pending["known_fields"]["orderNo"] == "O202606040002"
    assert "我想投诉订单O202606040002的问题" in pending["args"]["reason"]
    assert "订单状态：已支付" in pending["args"]["reason"]
    assert "物流状态：运输中" in pending["args"]["reason"]


def test_human_service_reason_for_return_uses_business_problem_not_emotion() -> None:
    decision = DecisionResult(
        intent="order",
        tasks=[],
        planning_mode="planned",
        human_service={
            "reason": "用户情绪为愤怒/不满，且此前已就同一订单发起投诉，需人工介入协同处理退货与历史投诉。",
            "orderNo": "O202606040002",
        },
    )
    agent = CustomerAgent(
        orchestrator=_FakeOrchestrator(decision),
        summarize_agent=_FakeSummarize("最终回答"),
        hitl_guide_agent=_FakeHitlGuide(),
        memory_loader=lambda ctx: None,
        memory_saver=lambda ctx: None,
    )
    ctx = AgentContext(
        user_input="我要退货",
        session_id="s1",
        customer_id=7,
        current_emotion="愤怒/不满",
    )
    ctx.agent_results["order"] = (
        "订单O202606040002当前状态为已支付、运输中，含iPhone 14 Plus和iPhone 13 Pro各1台；"
        "物流显示快件运输中，尚未签收。根据平台规则，商品未签收前不支持退货，仅可申请‘仅退款’（类型3）。"
    )

    output = asyncio.run(agent._start_human_service_action(ctx, decision.human_service))
    pending = asyncio.run(agent._pending_action("tool", output, ctx))
    reason = pending["args"]["reason"]

    assert "我想处理订单O202606040002的退货/仅退款问题" in reason
    assert "当前状态为已支付、运输中" in reason
    assert "情绪" not in reason
    assert "此前" not in reason
    assert "历史投诉" not in reason
    assert "协同" not in reason


def test_confirm_with_edited_args_resumes_and_persists() -> None:
    order = _FakeOrder("售后单 A123 已创建")
    ctx = AgentContext(user_input="我要退货", session_id="s1", customer_id=7)

    gen = _build_agent(order, answer="已为你提交售后单 A123").iter_run(ctx)
    _drive_to_review(gen)

    # 用户修改售后原因后确认 → 注入 approved + 改后参数续跑
    order_event = gen.send({"approved": True, "args": {"orderNo": "O1", "type": 1, "reason": "屏幕碎裂，要求退货"}})

    assert order_event["stage"] == "order_agent"
    assert order_event["update"]["status"] == "done"
    assert ctx.agent_results["order"] == "售后单 A123 已创建"
    assert order.resume_calls[0]["approved"] is True
    assert order.resume_calls[0]["args"]["reason"] == "屏幕碎裂，要求退货"
    assert order.resume_calls[0]["call_id"] == "call_1"
    assert order.resume_calls[0]["messages"] == ["__history__"]

    # 续跑后中断态被清理，流程继续到最终回答
    assert ctx.pending_review is None
    assert ctx.write_confirmed is True
    for _ in gen:
        pass
    assert ctx.final_answer == "已为你提交售后单 A123"


def test_order_wrap_uses_created_after_sale_tool_result_over_model_draft_text() -> None:
    result = SimpleNamespace(
        output=OrderServiceOutput(
            answer=(
                "当前已为您生成退货申请草稿，单号：AS20260622225745766。"
                "核对无误后，点击确认即可提交。"
            )
        ),
        all_messages=lambda: [
            SimpleNamespace(
                parts=[
                    ToolReturnPart(
                        tool_name="createAfterSale",
                        content={
                            "authorized": True,
                            "created": True,
                            "afterSale": {
                                "afterSaleNo": "AS20260622225745766",
                                "orderNo": "O202606040002",
                                "type": 1,
                                "status": 0,
                                "reason": "不喜欢",
                            },
                        },
                    )
                ]
            )
        ],
    )

    wrapped = OrderAgent._wrap(result)

    assert "售后申请已提交" in wrapped.text
    assert "售后单号：AS20260622225745766" in wrapped.text
    assert "关联订单：O202606040002" in wrapped.text
    assert "状态：待审核" in wrapped.text
    assert "草稿" not in wrapped.text
    assert "点击确认" not in wrapped.text


def test_cancel_resumes_with_denial() -> None:
    # 取消后订单专家答复保持明确，避免误导用户以为已提交写操作
    order = _FakeOrder("已取消该售后申请，未提交到业务系统")
    ctx = AgentContext(user_input="算了不退了", session_id="s1", customer_id=7)

    gen = _build_agent(order, answer="已取消，未提交售后").iter_run(ctx)
    _drive_to_review(gen)

    gen.send({"approved": False, "message": "用户放弃"})

    assert order.resume_calls[0]["approved"] is False
    assert order.resume_calls[0]["message"] == "用户放弃"
    assert ctx.write_confirmed is False
    for _ in gen:
        pass
    assert ctx.final_answer == "已取消，未提交售后"


def test_one_shot_run_stops_at_review_without_auto_denial() -> None:
    order = _FakeOrder("不应自动续跑")
    agent = _build_agent(order)

    ctx = agent.run("我要退货", session_id="s1", customer_id=7)

    assert ctx.pending_review is not None
    assert ctx.pending_review["tool"] == "createAfterSale"
    assert order.resume_calls == []
    assert ctx.final_answer == ""


def test_reject_with_feedback_can_regenerate_pending_action() -> None:
    order = _RegeneratingOrder("售后单 A123 已创建")
    ctx = AgentContext(user_input="我要退款", session_id="s1", customer_id=7)

    gen = _build_agent(order, answer="已为你提交售后单 A123").iter_run(ctx)
    _drive_to_review(gen)

    review = gen.send({"approved": False, "regenerate": True, "message": "改成仅退款，原因是买错了"})

    assert review["stage"] == "awaiting_review"
    pending = review["update"]["pending_action"]
    assert pending["call_id"] == "call_2"
    assert pending["args"]["type"] == 3
    assert order.resume_calls[0]["regenerate"] is True
    assert order.resume_calls[0]["message"] == "改成仅退款，原因是买错了"

    order_event = gen.send({"approved": True, "args": pending["args"]})

    assert order_event["stage"] == "order_agent"
    assert order_event["update"]["status"] == "done"
    assert ctx.agent_results["order"] == "售后单 A123 已创建"
