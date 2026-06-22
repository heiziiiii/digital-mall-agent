"""多 Agent 运行时测试：决策→分波并发执行→总结→记忆保存（全程不触发 LLM/网络）。

通过 monkeypatch 替换运行链路内的 Agent 调用，使断言聚焦于编排/执行逻辑本身。
"""

from __future__ import annotations

from agent.agents import safety
from agent.agents.orchestrator import DecisionResult
from agent.customer_agent import AgentContext, CustomerAgent, Task


def _decision(tasks: list[Task], mode: str = "planned") -> DecisionResult:
    """构造一个编排结果：主意图取最高优先级任务的域。"""
    intent = tasks[0].agent if tasks else "chat"
    return DecisionResult(intent=intent, tasks=tasks, planning_mode=mode)


class _FakeOrchestrator:
    def __init__(self, decision: DecisionResult) -> None:
        self.decision = decision
        self.seen_input = None

    async def decide(self, user_input) -> DecisionResult:
        self.seen_input = user_input
        return self.decision


class _FakeSummarizeAgent:
    def __init__(self, answer: str = "草拟回答", payloads: list[str] | None = None) -> None:
        self.answer = answer
        self.payloads = payloads

    async def run(self, payload: str) -> str:
        if self.payloads is not None:
            self.payloads.append(payload)
        return self.answer


def _make_agent(
    decision: DecisionResult,
    specialist=None,
    summarize_agent: _FakeSummarizeAgent | None = None,
) -> CustomerAgent:
    agent = CustomerAgent(
        orchestrator=_FakeOrchestrator(decision),
        summarize_agent=summarize_agent or _FakeSummarizeAgent(),
        memory_loader=lambda ctx: None,
        memory_saver=lambda ctx: None,
    )

    async def default_specialist(name, _context, deps=None):
        return f"{name}-result"

    agent.run_specialist = specialist or default_specialist
    return agent


def _run(ctx: AgentContext, decision: DecisionResult):
    """以给定的编排结果驱动运行链路，返回产出的阶段名序列。"""
    return [event["stage"] for event in _make_agent(decision).iter_run(ctx)]


def test_dependent_tasks_run_in_dependency_order(monkeypatch) -> None:
    ctx = AgentContext(user_input="查订单再推荐", session_id="s1")
    decision = _decision(
        [
            Task(agent="order", priority=10),
            Task(agent="product", priority=50, depends_on=["order"]),
        ]
    )

    stages = _run(ctx, decision)

    assert stages == [
        "memory_load",
        "decide",
        "order_agent",
        "product_agent",
        "summarize",
        "memory_save",
    ]
    assert ctx.agent_results == {"order": "order-result", "product": "product-result"}


def test_independent_tasks_run_in_one_wave(monkeypatch) -> None:
    ctx = AgentContext(user_input="顺便问下技术和选购", session_id="s-par")
    decision = _decision(
        [Task(agent="tech", priority=10), Task(agent="product", priority=10)]
    )

    stages = _run(ctx, decision)

    # 同优先级且无依赖 → 同一波并发执行，但事件按波内顺序逐个产出
    assert stages == ["memory_load", "decide", "tech_agent", "product_agent", "summarize", "memory_save"]
    assert ctx.agent_results == {"tech": "tech-result", "product": "product-result"}


def test_specialist_contexts_are_isolated_by_agent() -> None:
    ctx = AgentContext(
        user_input="给我推荐类似的高端手机",
        session_id="customer-7",
        customer_no="7",
        customer_id=7,
        user_profile={"budget": "9000", "preference": "large screen"},
        history=[
            {"role": "user", "content": "我的订单号是 O100"},
            {"role": "assistant", "content": "已查询到订单。"},
        ],
    )
    ctx.rolling_summary = "用户曾咨询订单和手机推荐"
    ctx.agent_results = {"order": "订单里包含 iPhone 15 Pro", "tech": "技术结果"}

    agent = CustomerAgent()
    product_context = agent._build_specialist_context("product", ctx)
    order_context = agent._build_specialist_context("order", ctx)
    tech_context = agent._build_specialist_context("tech", ctx)

    # 未显式声明 tasks 时不再硬编码默认依赖，产品专家不注入任何前序结果
    assert "【选购偏好】" in product_context
    assert "【近期产品对话】" not in product_context
    assert "O100" not in product_context
    assert "【前序处理结果】" not in product_context
    assert "iPhone 15 Pro" not in product_context
    assert "customer-7" not in product_context
    assert "技术结果" not in product_context
    assert "【近期对话】" not in product_context

    assert "【当前认证客户编号】" not in order_context
    assert "【当前认证客户ID】" not in order_context
    assert "customer_no" not in order_context
    assert "customer_id" not in order_context
    assert "customer-7" not in order_context
    assert "【近期订单/售后对话】" not in order_context
    assert "O100" not in order_context
    assert "【选购偏好】" not in order_context
    assert "【前序处理结果】" not in order_context

    assert "【近期技术对话】" not in tech_context
    assert "O100" not in tech_context
    assert "customer-7" not in tech_context
    assert "【选购偏好】" not in tech_context
    assert "【前序处理结果】" not in tech_context


def test_dependency_results_follow_task_depends_on() -> None:
    """产品任务显式声明依赖 tech 时，前序结果应注入 tech（而非默认 order）。"""
    ctx = AgentContext(user_input="结合刚才的技术说明推荐")
    ctx.tasks = [Task(agent="product", priority=10, depends_on=["tech"])]
    ctx.agent_results = {"order": "订单结果", "tech": "技术结果A"}

    product_context = CustomerAgent()._build_specialist_context("product", ctx)

    assert "技术结果A" in product_context
    assert "订单结果" not in product_context


def test_rewritten_query_is_passed_to_specialist_context() -> None:
    """专家上下文应使用编排阶段面向专家改写后的 query。"""
    ctx = AgentContext(user_input="我最近买的那个手机和新款比哪个好")
    ctx.tasks = [
        Task(
            agent="product",
            priority=50,
            depends_on=["order"],
            query="基于订单专家输出的已购手机，与当前新款手机做选购比较。",
            reason="产品比较依赖订单中的已购商品。",
            confidence=0.86,
        )
    ]
    ctx.agent_results = {"order": "最近订单商品为 iPhone 15 Pro"}

    product_context = CustomerAgent()._build_specialist_context("product", ctx)

    assert "【任务上下文】基于订单专家输出的已购手机，与当前新款手机做选购比较。" in product_context
    assert "我最近买的那个手机和新款比哪个好" not in product_context
    assert "最近订单商品为 iPhone 15 Pro" in product_context


def test_dependency_results_are_available_to_tech_and_order() -> None:
    """显式依赖不只对产品专家生效，技术和订单专家也能收到前序结果。"""
    ctx = AgentContext(user_input="根据推荐结果说明参数，并帮我申请售后")
    ctx.tasks = [
        Task(agent="tech", priority=20, depends_on=["product"], query="基于产品结果解释关键参数。"),
        Task(agent="order", priority=30, depends_on=["tech"], query="基于技术判断办理售后。"),
    ]
    ctx.agent_results = {"product": "产品结果P", "tech": "技术判断T"}

    agent = CustomerAgent()
    tech_context = agent._build_specialist_context("tech", ctx)
    order_context = agent._build_specialist_context("order", ctx)

    assert "[product]\n产品结果P" in tech_context
    assert "[tech]\n技术判断T" in order_context


def test_runtime_passes_custom_context_to_each_specialist(monkeypatch) -> None:
    ctx = AgentContext(
        user_input="查订单再推荐类似产品",
        session_id="customer-8",
        customer_no="8",
        customer_id=8,
        user_profile={"budget": "9000"},
    )
    decision = _decision(
        [
            Task(agent="order", priority=10),
            Task(agent="product", priority=50, depends_on=["order"]),
        ]
    )
    seen_contexts: dict[str, str] = {}

    async def fake_specialist(name, context, deps=None):
        seen_contexts[name] = context
        if name == "order":
            assert deps is not None
            assert deps.customer_id == 8
            assert deps.session_id == "customer-8"
        else:
            assert deps is not None
            assert deps.customer_id == 8
            assert deps.session_id == "customer-8"
        return f"{name}-result"

    list(_make_agent(decision, specialist=fake_specialist).iter_run(ctx))

    assert "【当前认证客户编号】" not in seen_contexts["order"]
    assert "【当前认证客户ID】" not in seen_contexts["order"]
    assert "customer_no" not in seen_contexts["order"]
    assert "customer_id" not in seen_contexts["order"]
    assert "【选购偏好】" not in seen_contexts["order"]
    assert "【选购偏好】" in seen_contexts["product"]
    assert "[order]\norder-result" in seen_contexts["product"]
    assert "customer-8" not in seen_contexts["product"]


def test_decide_event_includes_rewrite_metadata(monkeypatch) -> None:
    ctx = AgentContext(user_input="查订单再推荐", session_id="s-meta")
    decision = _decision(
        [
            Task(
                agent="order",
                priority=10,
                query="查询最近订单。",
                reason="用户需要订单信息。",
                confidence=0.9,
            )
        ]
    )

    async def fake_specialist(_name, _context, deps=None):
        return "order-result"

    events = list(_make_agent(decision, specialist=fake_specialist).iter_run(ctx))
    decide_event = next(event for event in events if event["stage"] == "decide")
    task = decide_event["update"]["tasks"][0]

    assert task["query"] == "查询最近订单。"
    assert task["reason"] == "用户需要订单信息。"
    assert task["confidence"] == 0.9


def test_runtime_passes_full_context_to_orchestrator() -> None:
    ctx = AgentContext(
        user_input="小米",
        rolling_summary="正在确认退货订单，O202606060001 是小米14 Pro。",
        history=[{"role": "assistant", "content": "请问您要退哪一单？"}],
    )
    orchestrator = _FakeOrchestrator(_decision([], mode="simple"))
    agent = CustomerAgent(
        orchestrator=orchestrator,
        summarize_agent=_FakeSummarizeAgent(),
        memory_loader=lambda ctx: None,
        memory_saver=lambda ctx: None,
    )

    list(agent.iter_run(ctx))

    assert orchestrator.seen_input is ctx


def test_chat_skips_specialists(monkeypatch) -> None:
    ctx = AgentContext(user_input="你好", session_id="s2")
    decision = _decision([], mode="simple")

    stages = _run(ctx, decision)

    assert stages == ["memory_load", "decide", "summarize", "memory_save"]


def test_product_recommendation_always_uses_summarize(monkeypatch) -> None:
    ctx = AgentContext(user_input="我要苹果高端机型", session_id="s-product")
    ctx.current_emotion = "焦急"
    decision = _decision([Task(agent="product", priority=10)])
    seen_payloads: list[str] = []

    async def fake_specialist(_name, _context, deps=None):
        return (
            '{"reply_type":"product_recommendation","summary":"为你推荐这款苹果高端机型",'
            '"recommendations":[{"product_no":"P100","name":"苹果 iPhone 15 Pro",'
            '"price":"8999.0","stock_status":"现货","highlights":["A17 Pro","钛金属机身"],'
            '"match_score":92,"reason":"性能、屏幕和影像比较均衡。"}],"notes":"可继续告诉我预算。"}'
        )

    summarize_agent = _FakeSummarizeAgent("为你推荐苹果 iPhone 15 Pro，契合度 92%。", seen_payloads)
    stages = [
        event["stage"]
        for event in _make_agent(
            decision,
            specialist=fake_specialist,
            summarize_agent=summarize_agent,
        ).iter_run(ctx)
    ]

    assert stages == ["memory_load", "decide", "product_agent", "summarize", "memory_save"]
    assert seen_payloads
    assert '"current_emotion": "焦急"' in seen_payloads[0]
    assert '\\"match_score\\":92' in seen_payloads[0]
    assert "苹果 iPhone 15 Pro" in ctx.final_answer
    assert "契合度 92%" in ctx.final_answer


def test_empty_product_recommendation_uses_summarize(monkeypatch) -> None:
    ctx = AgentContext(
        user_input="这两款机器谁拍照更好？",
        session_id="s-product-empty",
        history=[
            {"role": "user", "content": "我要华为和苹果的高端机型"},
            {"role": "assistant", "content": "推荐了华为 Mate 60 Pro 和苹果 iPhone 15 Pro。"},
        ],
    )
    decision = _decision([Task(agent="product", priority=10)])
    seen_payloads: list[str] = []

    async def fake_specialist(_name, context, deps=None):
        assert "【近期产品对话】" not in context
        assert "华为 Mate 60 Pro" not in context
        assert "苹果 iPhone 15 Pro" not in context
        return '{"reply_type":"product_recommendation","summary":"暂未检索到可靠匹配的商品","recommendations":[],"notes":"没有找到符合条件且数据可靠的商品。"}'

    summarize_agent = _FakeSummarizeAgent(
        "我需要重新核实两款的影像参数后再给你准确比较。", seen_payloads
    )
    stages = [
        event["stage"]
        for event in _make_agent(
            decision,
            specialist=fake_specialist,
            summarize_agent=summarize_agent,
        ).iter_run(ctx)
    ]

    assert stages == ["memory_load", "decide", "product_agent", "summarize", "memory_save"]
    assert seen_payloads
    assert '"recent_dialogue"' not in seen_payloads[0]
    assert '"history_summary"' not in seen_payloads[0]
    assert ctx.final_answer == "我需要重新核实两款的影像参数后再给你准确比较。"


def test_runtime_skips_local_safety(monkeypatch) -> None:
    ctx = AgentContext(user_input="查一下我的资料", session_id="s3")
    decision = _decision([], mode="simple")

    summarize_agent = _FakeSummarizeAgent("你的手机号是 13812345678。")
    stages = [
        event["stage"]
        for event in _make_agent(decision, summarize_agent=summarize_agent).iter_run(ctx)
    ]

    assert stages == ["memory_load", "decide", "summarize", "memory_save"]
    assert ctx.safety_retry == 0
    assert ctx.safety_passed is True
    assert ctx.final_answer == "你的手机号是 13812345678。"
    assert ctx.safety_feedback == ""


def test_local_safety_allows_masked_customer_info() -> None:
    ctx = AgentContext(user_input="我的客户id为1，请查最近售后", final_answer="已查询到客户ID 1 的售后记录，手机号 138****5678。")

    passed, feedback = safety.audit(ctx)

    assert passed is True
    assert feedback == ""


def test_local_safety_blocks_unconfirmed_after_sale_success() -> None:
    ctx = AgentContext(user_input="我要退货", final_answer="退货退款售后申请已成功发起。")

    passed, feedback = safety.audit(ctx, evidence="")

    assert passed is False
    assert feedback == "回答包含未经工具结果确认的订单/售后写操作承诺。"


def test_local_safety_allows_confirmed_after_sale_success() -> None:
    ctx = AgentContext(user_input="我要退货", final_answer="退货退款售后申请已成功发起。")
    ctx.write_confirmed = True

    passed, feedback = safety.audit(ctx, evidence="")

    assert passed is True
    assert feedback == ""


def test_local_safety_allows_prefixed_business_numbers() -> None:
    ctx = AgentContext(
        user_input="我要退货",
        final_answer="售后单号 AS20260616230724747 已创建，关联订单 O202606030001。",
    )
    ctx.write_confirmed = True

    passed, feedback = safety.audit(ctx, evidence="")

    assert passed is True
    assert feedback == ""
