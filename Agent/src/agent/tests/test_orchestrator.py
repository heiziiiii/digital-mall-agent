"""编排（决策）逻辑测试：任务计划由 LLM 产出，模型不可用或失败时直接抛出。

通过 monkeypatch 替换编排 Agent，使断言聚焦于任务清洗与优先级/依赖归一化逻辑。
"""

import asyncio
from types import SimpleNamespace

import pytest

import agent.agents.orchestrator as orchestrator_module
from agent.agents.orchestrator import HumanServiceSpec, OrchestratorAgent, TaskSpec
from agent.customer_agent import AgentContext
from agent.prompts.loader import render_skill


class FakeOrchestratorAgent:
    """伪编排 Agent：直接吐回预设的 TaskSpec 列表。"""

    def __init__(self, tasks: list[TaskSpec]) -> None:
        self.tasks = tasks
        self.prompts: list[str] = []

    async def run(self, prompt: str, **_kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(output=SimpleNamespace(tasks=self.tasks))


class FakeHumanServiceOrchestratorAgent(FakeOrchestratorAgent):
    """伪编排 Agent：在任务之外额外吐回 LLM 标注的人工服务结构。"""

    def __init__(
        self, tasks: list[TaskSpec], human_service: HumanServiceSpec | None
    ) -> None:
        super().__init__(tasks)
        self.human_service = human_service

    async def run(self, prompt: str, **_kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(
            output=SimpleNamespace(tasks=self.tasks, human_service=self.human_service)
        )


@pytest.fixture(autouse=True)
def _simple_timed_agent_run(monkeypatch):
    """单测只验证编排逻辑，LLM 运行钩子用轻量 run() 替代。"""

    async def _run(agent, prompt: str, _purpose: str):
        return await agent.run(prompt)

    monkeypatch.setattr(orchestrator_module, "timed_agent_run", _run)


def test_single_product_task(monkeypatch) -> None:
    fake = FakeOrchestratorAgent(
        [
                TaskSpec(
                    agent="product",
                    query="推荐一款拍照表现好的手机。",
                    reason="用户有手机选购和拍照偏好。",
                    confidence=1.0,
                    priority=10,
                )
        ]
    )
    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: fake)

    result = asyncio.run(agent.decide("推荐一款拍照好的手机"))

    assert result.intent == "product"
    assert [(t.agent, t.priority, t.depends_on) for t in result.tasks] == [("product", 10, [])]
    assert result.tasks[0].query == "推荐一款拍照表现好的手机。"
    assert result.tasks[0].reason == "用户有手机选购和拍照偏好。"
    assert result.tasks[0].confidence == 1.0
    assert result.planning_mode == "planned"
    assert "【编排上下文】" in fake.prompts[0]
    assert "推荐一款拍照好的手机" in fake.prompts[0]
    assert "请根据【编排上下文】进行任务编排" in fake.prompts[0]
    assert "priority 只表示调度先后" not in fake.prompts[0]


def test_decide_prompt_includes_memory_context(monkeypatch) -> None:
    fake = FakeOrchestratorAgent(
        [
            TaskSpec(
                agent="order",
                query="用户选择小米14 Pro 对应的订单 O202606060001 办理退货。",
                reason="上下文显示正在等待用户选择退货订单。",
                confidence=0.95,
                priority=10,
            )
        ]
    )
    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: fake)
    ctx = AgentContext(
        user_input="小米",
        background_summary=(
            "王先生提出退货需求，当前对话聚焦于确认退货订单；"
            "O202606060001含小米14 Pro。"
        ),
        user_profile={"summary": "昵称：王先生；会员等级：3级。"},
        history=[
            {"role": "user", "content": "我要退货"},
            {"role": "assistant", "content": "请问您要为哪一单办理退货？"},
        ],
    )

    result = asyncio.run(agent.decide(ctx))

    prompt = fake.prompts[0]
    assert result.intent == "order"
    assert result.tasks[0].query == "用户选择小米14 Pro 对应的订单 O202606060001 办理退货。"
    assert '"user_input": "小米"' in prompt
    assert "当前对话聚焦于确认退货订单" in prompt
    assert "请问您要为哪一单办理退货" not in prompt
    assert "用户关注退货流程效率" not in prompt
    assert "rolling_summary" not in prompt
    assert "recalled_memories" not in prompt
    assert "recent_history" not in prompt
    assert "完整原始记忆" not in prompt
    assert "完整历史" not in prompt
    assert "不要重新抽取原始对话记忆" not in prompt


def test_after_sale_hitl_constraints_are_in_skills() -> None:
    orchestrate_prompt = render_skill("orchestrate")
    order_prompt = render_skill("order")
    summarize_prompt = render_skill("summarize")
    memory_prompt = render_skill("memory")

    assert "退货、退款、换货、维修、申请售后等办理意图必须交给 `order`" in orchestrate_prompt
    assert "目标订单不明确时，让订单专家列候选订单" in orchestrate_prompt
    assert "目标明确时，推进售后办理和待用户确认" in orchestrate_prompt
    assert "不直接创建售后单或人工服务记录" in orchestrate_prompt
    assert "你只做规划" in orchestrate_prompt
    assert "原因缺失时留给用户补齐" in orchestrate_prompt
    assert "问题改写规则" in orchestrate_prompt
    assert "`order` 改写方向" in orchestrate_prompt
    assert "`product` 改写方向" in orchestrate_prompt
    assert "`tech` 改写方向" in orchestrate_prompt
    assert "避免重复完整追问" in orchestrate_prompt
    assert "本轮 `query` 应明确" in orchestrate_prompt
    assert "应先规划 `order` 查询最近购买订单以消解商品名称/型号" in orchestrate_prompt
    assert "`tech` 依赖订单方向" in orchestrate_prompt
    assert "人工服务不是专家任务" in orchestrate_prompt
    assert "human_service" not in orchestrate_prompt
    assert "工具动作" not in orchestrate_prompt
    assert "每个专家任务都要写成可直接执行的完整请求" in orchestrate_prompt
    assert "完整原始记忆" not in orchestrate_prompt
    assert "完整历史" not in orchestrate_prompt
    assert '"tasks"' not in orchestrate_prompt
    assert "输出结构" not in orchestrate_prompt
    assert "不要只停留在“可申请/是否需要我办理”" in order_prompt
    assert "必须发起 `createAfterSale`" in order_prompt
    assert "不得自行选取最近订单并发起 `createAfterSale`" in order_prompt
    assert "不要改为自然语言追问后结束本轮" in order_prompt
    assert "前端表单补全" in order_prompt
    assert "不要再追问“是否确认”" in order_prompt
    assert "不要使用“人工审核”“人工确认”“进入人工审核流程”" in order_prompt
    assert "工具没有对应能力的写操作" in order_prompt
    assert "需要人工进一步核实" in order_prompt
    assert "human_service" not in order_prompt
    assert "人工服务单" not in order_prompt
    assert "缺少必填信息" in summarize_prompt
    assert "不要在最终回答结尾追加“是否需要我帮您提交/办理”" in summarize_prompt
    assert "创建售后单的待确认步骤是交给用户本人审核确认" in summarize_prompt
    assert "建议人工客服进一步核实" in summarize_prompt
    assert "已创建服务记录" in summarize_prompt
    assert "不要编造售后审核、退款到账、物流拦截等时效" in summarize_prompt
    assert "不要在结尾新增专家未提出的查询、匹配、转办、检测、创建记录等服务承诺或反问" in summarize_prompt
    assert "若 `background_summary` 显示此前已经追问过同一批缺失信息" in summarize_prompt
    assert "禁止自行追加“需要我帮您查/匹配/提交/转接吗”等能力暗示" in summarize_prompt
    assert "背景摘要生成" in memory_prompt
    assert "省略表达" in memory_prompt
    assert "回答上一轮未决问题" in memory_prompt
    # 双节点新增能力：背景补充与情绪提炼
    assert "background_summary" in memory_prompt
    assert "current_emotion" in memory_prompt


def test_multi_task_keeps_priority_and_dependency(monkeypatch) -> None:
    fake = FakeOrchestratorAgent(
        [
            TaskSpec(agent="product", priority=50, depends_on=["order"]),
            TaskSpec(agent="order", priority=10),
        ]
    )
    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: fake)

    result = asyncio.run(agent.decide("找出我最近的订单，并退货，最后推荐类似产品"))

    # 按优先级排序：order(10) 在 product(50) 之前；主意图取最高优先级任务的域
    assert result.intent == "order"
    assert [(t.agent, t.priority, t.depends_on) for t in result.tasks] == [
        ("order", 10, []),
        ("product", 50, ["order"]),
    ]


def test_recent_purchase_tech_issue_inserts_order_lookup(monkeypatch) -> None:
    """“最近买的手机发烫”应先查最近订单消解机型，再把订单结果交给技术专家。"""
    fake = FakeOrchestratorAgent(
        [
            TaskSpec(
                agent="tech",
                query="排查用户最近买的手机发烫问题。",
                reason="用户反馈技术故障。",
                confidence=0.9,
                priority=10,
            )
        ]
    )
    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: fake)
    ctx = AgentContext(user_input="我最近买的手机发烫", customer_id=5)

    result = asyncio.run(agent.decide(ctx))

    assert result.intent == "order"
    assert [(task.agent, task.depends_on) for task in result.tasks] == [
        ("order", []),
        ("tech", ["order"]),
    ]
    assert "最近购买的手机订单" in result.tasks[0].query
    assert "基于订单专家返回" in result.tasks[1].query


def test_human_service_is_inferred_from_complaint_context(monkeypatch) -> None:
    fake = FakeOrchestratorAgent(
        [
            TaskSpec(
                agent="order",
                query="查询售后单 AS202606030001 并说明处理结果。",
                priority=10,
            )
        ]
    )
    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: fake)
    ctx = AgentContext(
        user_input="我非常不满意，换货取消不了太离谱了，我要投诉并转人工处理，关联售后单 AS202606030001",
        background_summary="用户强烈不满，明确要求投诉并转人工处理。",
        current_emotion="愤怒/不满",
    )

    result = asyncio.run(agent.decide(ctx))

    assert result.human_service is not None
    assert result.human_service["afterSaleNo"] == "AS202606030001"
    assert "转人工" in result.human_service["reason"]


def test_explicit_human_request_plans_human_service(monkeypatch) -> None:
    """用户直接要求转人工：即便 LLM 未填 human_service 结构，也应从上下文兜底规划为人工服务动作。"""
    fake = FakeOrchestratorAgent([])  # 无专家任务
    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: fake)

    result = asyncio.run(agent.decide("我不想自助了，直接帮我转人工客服处理"))

    # 规划直接把诉求识别为人工服务动作，而不是丢给某个专家任务
    assert result.human_service is not None
    assert result.tasks == []
    assert "人工" in result.human_service["reason"]
    # 无专家任务但有人工服务时，主意图归到 order 域（人工服务由订单域承载）
    assert result.intent == "order"


def test_llm_marked_human_service_is_planned(monkeypatch) -> None:
    """LLM 已显式标注 human_service.needed=True 时，规划应原样产出该人工服务计划。"""
    fake = FakeHumanServiceOrchestratorAgent(
        tasks=[],
        human_service=HumanServiceSpec(
            needed=True,
            reason="用户要求人工核实退款进度",
            orderNo="O202606060001",
        ),
    )
    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: fake)

    result = asyncio.run(agent.decide("帮我查下退款，顺便转人工"))

    assert result.human_service == {
        "reason": "用户要求人工核实退款进度",
        "orderNo": "O202606060001",
        "afterSaleNo": "",
    }
    assert result.intent == "order"


def test_dedup_keeps_highest_priority_and_drops_invalid_deps(monkeypatch) -> None:
    fake = FakeOrchestratorAgent(
        [
            TaskSpec(agent="product", priority=80, depends_on=["product", "order"]),
            TaskSpec(agent="product", priority=20),  # 同专家重复，应保留优先级更高（20）的
        ]
    )
    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: fake)

    result = asyncio.run(agent.decide("推荐手机"))

    # 仅保留一个 product 任务，优先级取 20；自环 product 依赖被剔除，
    # 悬挂依赖 order（本轮不存在）也被剔除。
    assert len(result.tasks) == 1
    task = result.tasks[0]
    assert task.agent == "product"
    assert task.priority == 20
    assert task.depends_on == []


def test_normalization_does_not_invent_dependencies(monkeypatch) -> None:
    """依赖由编排 Agent 输出决定，本地归一化只清洗非法依赖，不硬编码补依赖。"""
    fake = FakeOrchestratorAgent(
        [
            TaskSpec(agent="order", priority=10),
            TaskSpec(agent="tech", priority=20),
            TaskSpec(agent="product", priority=60, depends_on=["order"]),
        ]
    )
    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: fake)

    result = asyncio.run(agent.decide("我买的手机电池发热，想退货，再推荐一款电池容量大的旗舰手机"))

    assert [(t.agent, t.depends_on) for t in result.tasks] == [
        ("order", []),
        ("tech", []),
        ("product", ["order"]),
    ]


def test_empty_input_skips_llm() -> None:
    result = asyncio.run(OrchestratorAgent().decide("   "))

    assert result.intent == "chat"
    assert result.tasks == []
    assert result.planning_mode == "simple"


def test_raises_when_llm_unavailable(monkeypatch) -> None:
    # 模型不可用时编排 Agent 构建即抛出，decide 不再静默退化为闲聊
    def _raise() -> None:
        raise RuntimeError("LLM 未配置")

    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", _raise)

    with pytest.raises(RuntimeError):
        asyncio.run(agent.decide("我想看苹果高端机型"))


def test_propagates_when_llm_fails(monkeypatch) -> None:
    # LLM 调用失败时直接向上抛出，不再用规则兜底拼任务
    class FailingAgent:
        async def run(self, prompt: str, **_kwargs):
            raise RuntimeError("boom")

    agent = OrchestratorAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: FailingAgent())

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(agent.decide("我最近的订单和该品牌最先进的产品比，哪个更好"))
