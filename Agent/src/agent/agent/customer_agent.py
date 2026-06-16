"""客服主 Agent：初始化子 Agent，并负责编排与执行完整客服流程。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.usage import UsageLimits

from agent.hooks import timed_agent_run
from agent.llm.model import get_model
from agent.agents.order import OrderAgent, SpecialistRunResult
from agent.agents.orchestrator import OrchestratorAgent
from agent.agents.product import ProductAgent
from agent.agents.safety import apply as apply_safety
from agent.agents.summarize import SummarizeAgent
from agent.agents.tech import TechAgent
from agent.tools.mcp_client import SpecialistDeps, toolset_for

Intent = Literal["product", "tech", "order", "chat"]
AgentName = Literal["product", "tech", "order"]
TaskStatus = Literal["pending", "running", "done", "failed", "awaiting_review"]


@dataclass
class Task:
    """编排 Agent 产出的单个专家任务。"""

    agent: AgentName
    priority: int = 100
    depends_on: list[AgentName] = field(default_factory=list)
    query: str = ""
    reason: str = ""
    confidence: float = 0.0
    status: TaskStatus = "pending"
    result: str = ""


@dataclass
class AgentContext:
    """一次用户请求从输入到最终回答的完整运行态。"""

    session_id: str = "default"
    user_input: str = ""
    customer_no: str | None = None
    customer_id: int | None = None

    history: list[dict] = field(default_factory=list)
    # 持久滚动摘要：跨轮稳定的历史压缩，仅由窗口压缩维护，逐轮落库
    rolling_summary: str = ""
    # 本轮工作记忆：记忆 Agent 按本轮问题相关性提炼，逐轮丢弃、不落库
    turn_focus: str = ""
    # 本轮背景摘要：记忆 Agent 整合筛选后强相关记忆得到的简洁背景，辅助生成回答
    background_summary: str = ""
    user_profile: dict = field(default_factory=dict)
    recalled_memories: list[dict] = field(default_factory=list)
    current_emotion: str = "中性"

    intent: Intent = "chat"
    tasks: list[Task] = field(default_factory=list)
    planning_mode: Literal["simple", "planned"] = "simple"

    agent_results: dict[str, str] = field(default_factory=dict)

    final_answer: str = ""
    safety_passed: bool = True
    safety_retry: int = 0
    safety_feedback: str = ""

    # HITL：模型发起的高风险写操作待用户审核确认/修改（交前端展示），
    # pending_messages 保存待恢复的 PydanticAI 消息历史（进程内存储）。
    pending_review: dict | None = None
    pending_messages: Any = None
    write_confirmed: bool = False


STAGE_LABELS: dict[str, str] = {
    "memory_load": "记忆提取",
    "decide": "任务编排",
    "product_agent": "产品咨询",
    "tech_agent": "技术支持",
    "order_agent": "订单售后",
    "human_service": "人工服务",
    "awaiting_review": "待用户确认",
    "summarize": "生成回答",
    "safety": "安全审核",
    "memory_save": "记忆保存",
}

_TOOL_ACTION_LIMIT = 4
_HUMAN_SERVICE_TOOL_PROMPT = (
    "你是智能客服系统的工具执行器，只负责把已规划的人工服务记录请求转成 "
    "createHumanService 待确认工具调用。不要处理订单、售后或技术问题；不要输出普通话术。"
)


class ToolActionOutput(BaseModel):
    """工具动作执行后的文本输出。"""

    answer: str = Field(default="", min_length=1)


def _default_load_memory(ctx: AgentContext) -> None:
    """惰性导入记忆模块，避免只使用调度能力时加载存储后端依赖。"""
    from agent.memory import load_memory

    load_memory(ctx)


def _default_save_memory(ctx: AgentContext) -> None:
    """惰性导入记忆模块，避免只使用调度能力时加载存储后端依赖。"""
    from agent.memory import save_memory

    save_memory(ctx)


class CustomerAgent:
    """面向用户的一体化客服 Agent，负责编排、调度和汇总子 Agent 能力。"""

    def __init__(
        self,
        orchestrator: OrchestratorAgent | None = None,
        product_agent: ProductAgent | None = None,
        tech_agent: TechAgent | None = None,
        order_agent: OrderAgent | None = None,
        summarize_agent: SummarizeAgent | None = None,
        memory_loader: Callable[[AgentContext], None] | None = None,
        memory_saver: Callable[[AgentContext], None] | None = None,
    ) -> None:
        self.orchestrator = orchestrator or OrchestratorAgent()
        self.specialists = {
            "product": product_agent or ProductAgent(),
            "tech": tech_agent or TechAgent(),
            "order": order_agent or OrderAgent(),
        }
        self.summarize_agent = summarize_agent or SummarizeAgent()
        self.memory_loader = memory_loader or _default_load_memory
        self.memory_saver = memory_saver or _default_save_memory

    @staticmethod
    def plan_waves(tasks: list[Task]) -> list[list[Task]]:
        """按依赖与优先级把任务切分为可逐波执行的列表。"""
        remaining = list(tasks)
        done: set[str] = set()
        waves: list[list[Task]] = []

        while remaining:
            ready = [task for task in remaining if all(dep in done for dep in task.depends_on)]
            if not ready:
                raise ValueError(
                    f"任务依赖无法满足（环形或悬挂依赖）：{[task.agent for task in remaining]}"
                )

            top_priority = min(task.priority for task in ready)
            wave = [task for task in ready if task.priority == top_priority]

            waves.append(wave)
            done.update(task.agent for task in wave)
            wave_ids = {id(task) for task in wave}
            remaining = [task for task in remaining if id(task) not in wave_ids]

        return waves

    @staticmethod
    async def run_wave(
        wave: list[Task],
        runner: Callable[[Task], Awaitable[str]],
    ) -> None:
        """并发执行一波任务，把结果与状态就地写回 Task。"""

        async def _one(task: Task) -> None:
            task.status = "running"
            task.result = await runner(task)
            task.status = "done"

        await asyncio.gather(*(_one(task) for task in wave))

    @staticmethod
    def _event(stage: str, update: dict[str, Any]) -> dict[str, Any]:
        """构造阶段级进度事件。"""
        return {
            "type": "stage",
            "stage": stage,
            "label": STAGE_LABELS.get(stage, stage),
            "update": update,
        }

    @staticmethod
    def _pending_action(agent_name: str, output: SpecialistRunResult) -> dict[str, Any]:
        """把模型发起的待审批工具调用转成前端可编辑的 HITL JSON。"""
        if output.pending is None:
            raise ValueError("缺少待审批工具调用")
        args = output.pending.args
        field_config = {
            "createAfterSale": {
                "required": ["orderNo", "type", "reason"],
                "editable": ["orderNo", "type", "reason"],
                "instruction": "请核对售后申请信息；如有缺失请补全，确认后才会真正提交。",
            },
            "createHumanService": {
                "required": ["reason"],
                "editable": ["orderNo", "afterSaleNo", "reason"],
                "instruction": "请核对人工服务申请信息；确认后才会真正创建人工服务单。",
            },
        }
        config = field_config.get(
            output.pending.tool,
            {
                "required": [],
                "editable": list(args.keys()),
                "instruction": "请核对待执行操作，确认后才会真正执行。",
            },
        )
        required_fields = config["required"]
        missing_fields = [
            field_name
            for field_name in required_fields
            if args.get(field_name) is None
            or (isinstance(args.get(field_name), str) and not args.get(field_name).strip())
        ]
        return {
            "state": "awaiting_review",
            "kind": "tool_approval",
            "agent": agent_name,
            "tool": output.pending.tool,
            "call_id": output.pending.call_id,
            "args": args,
            "known_fields": {
                name: value
                for name, value in args.items()
                if value is not None and not (isinstance(value, str) and not value.strip())
            },
            "missing_fields": missing_fields,
            "required_fields": required_fields,
            "editable_fields": config["editable"],
            "instruction": config["instruction"],
        }

    @staticmethod
    def _recent_dialogue(ctx: AgentContext) -> str:
        """取最近几轮原始对话，供需要上下文续接的专家使用。"""
        if not ctx.history:
            return ""
        return "\n".join(
            f"{message.get('role', '')}: {message.get('content', '')}"
            for message in ctx.history[-4:]
        )

    @staticmethod
    def _previous_agent_results(ctx: AgentContext, allowed_agents: set[str]) -> str:
        """只暴露当前专家确实依赖的前序专家结果。"""
        return "\n".join(
            f"[{name}]\n{result}"
            for name, result in ctx.agent_results.items()
            if name in allowed_agents and result
        )

    @staticmethod
    def _task_for(ctx: AgentContext, agent_name: AgentName) -> Task | None:
        """查找当前专家对应的任务规格。"""
        return next((item for item in ctx.tasks if item.agent == agent_name), None)

    @classmethod
    def _task_query(cls, task: Task | None, ctx: AgentContext) -> str:
        """专家任务优先使用编排阶段改写后的问题，缺省回退原始输入。"""
        return (task.query if task and task.query else ctx.user_input).strip()

    @classmethod
    def _dependency_results(cls, ctx: AgentContext, agent_name: AgentName) -> str:
        """仅按任务声明的 depends_on 暴露前序结果，无声明则不注入任何依赖。"""
        task = cls._task_for(ctx, agent_name)
        deps = set(task.depends_on) if task and task.depends_on else set()
        return cls._previous_agent_results(ctx, deps)

    def _build_specialist_context(self, agent_name: AgentName, ctx: AgentContext) -> str:
        """由主 Agent 统一构造隔离上下文，再交给子 Agent 执行。"""
        specialist = self.specialists[agent_name]
        task = self._task_for(ctx, agent_name)
        return specialist.build_context(
            ctx,
            query=self._task_query(task, ctx),
            recent_dialogue=self._recent_dialogue(ctx),
            previous_results=self._dependency_results(ctx, agent_name),
        )

    def _specialist_deps(self, agent_name: AgentName, ctx: AgentContext) -> SpecialistDeps | None:
        """只有订单/售后专家接收服务端认证身份。"""
        if agent_name != "order":
            return None
        return self.specialists["order"].deps(ctx)

    async def run_specialist(
        self,
        name: AgentName,
        context: str,
        deps: SpecialistDeps | None = None,
    ) -> str | SpecialistRunResult:
        """按专家名称调用对应子 Agent 能力。

        订单专家返回 SpecialistRunResult（可能待用户审核确认），其余专家返回纯文本。
        """
        if name == "order":
            return await self.specialists[name].run(context, agent_deps=deps)
        return await self.specialists[name].run(context, deps=deps)

    @staticmethod
    def _format_agent_results(ctx: AgentContext) -> str:
        """把一个或多个子 Agent 结果整理为文本。"""
        if not ctx.agent_results:
            return ""
        return "\n".join(
            f"[{name}]\n{result}" for name, result in ctx.agent_results.items() if result
        )

    def _build_summarize_payload(self, ctx: AgentContext) -> str:
        """汇总历史摘要、画像、Agent 结果与当前问题，序列化为 JSON 供总结 Agent 使用。"""
        payload: dict[str, Any] = {}
        if ctx.turn_focus:
            payload["turn_focus"] = ctx.turn_focus
        if ctx.background_summary:
            payload["background_summary"] = ctx.background_summary
        if ctx.rolling_summary:
            payload["history_summary"] = ctx.rolling_summary
        if ctx.user_profile:
            payload["user_profile"] = ctx.user_profile
        if ctx.current_emotion:
            payload["current_emotion"] = ctx.current_emotion
        recalled = [
            memory["text"]
            for memory in ctx.recalled_memories
            if memory.get("text")
        ]
        if recalled:
            payload["recalled_memories"] = recalled
        recent = [
            {"role": message.get("role", ""), "content": message.get("content", "")}
            for message in ctx.history[-4:]
        ]
        if recent:
            payload["recent_dialogue"] = recent
        agent_results = {
            name: result for name, result in ctx.agent_results.items() if result
        }
        if agent_results:
            payload["agent_results"] = agent_results
        payload["user_input"] = ctx.user_input
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def iter_run(self, ctx: AgentContext) -> Iterator[dict[str, Any]]:
        """逐阶段执行客服主流程，每个阶段产出一条进度事件。"""
        self.memory_loader(ctx)
        yield self._event(
            "memory_load",
            {
                "turn_focus": ctx.turn_focus,
                "background_summary": ctx.background_summary,
                "rolling_summary": ctx.rolling_summary,
                "current_emotion": ctx.current_emotion,
            },
        )

        plan = asyncio.run(self.orchestrator.decide(ctx))
        ctx.intent = plan.intent
        ctx.tasks = plan.tasks
        ctx.planning_mode = plan.planning_mode
        yield self._event(
            "decide",
            {
                "intent": ctx.intent,
                "tasks": [
                    {
                        "agent": task.agent,
                        "priority": task.priority,
                        "depends_on": task.depends_on,
                        "query": task.query,
                        "reason": task.reason,
                        "confidence": task.confidence,
                    }
                    for task in ctx.tasks
                ],
                "human_service": plan.human_service,
            },
        )

        for wave in self.plan_waves(ctx.tasks):
            asyncio.run(self.run_wave(wave, lambda task: self._run_task(task, ctx)))
            for task in wave:
                # 命中高风险写操作：挂起本流程，把待确认信息交前端，
                # 经 .send({approved, args, message}) 注入用户决定后续跑落库。
                if ctx.pending_review and ctx.pending_review["agent"] == task.agent:
                    task.status = "awaiting_review"
                    while ctx.pending_review and ctx.pending_review["agent"] == task.agent:
                        user_decision = yield self._event(
                            "awaiting_review", {"pending_action": ctx.pending_review}
                        )
                        output = asyncio.run(self._resume_task(task, ctx, user_decision or {}))
                        if isinstance(output, SpecialistRunResult) and output.awaiting_review:
                            ctx.pending_review = self._pending_action(task.agent, output)
                            ctx.pending_messages = output.messages
                            continue
                        task.result = output.text if isinstance(output, SpecialistRunResult) else output
                        if bool((user_decision or {}).get("approved")):
                            ctx.write_confirmed = True
                        ctx.pending_review = None
                        ctx.pending_messages = None
                    task.status = "done"

                ctx.agent_results[task.agent] = task.result
                yield self._event(
                    f"{task.agent}_agent",
                    {"agent_results": {task.agent: task.result}, "status": task.status},
                )

        if plan.human_service:
            output = asyncio.run(self._start_human_service_action(ctx, plan.human_service))
            if isinstance(output, SpecialistRunResult) and output.awaiting_review:
                ctx.pending_review = self._pending_action("tool", output)
                ctx.pending_messages = output.messages
                while ctx.pending_review and ctx.pending_review["agent"] == "tool":
                    user_decision = yield self._event(
                        "awaiting_review", {"pending_action": ctx.pending_review}
                    )
                    output = asyncio.run(
                        self._resume_tool_action(ctx, user_decision or {})
                    )
                    if isinstance(output, SpecialistRunResult) and output.awaiting_review:
                        ctx.pending_review = self._pending_action("tool", output)
                        ctx.pending_messages = output.messages
                        continue
                    result_text = output.text if isinstance(output, SpecialistRunResult) else output
                    if bool((user_decision or {}).get("approved")):
                        ctx.write_confirmed = True
                    ctx.pending_review = None
                    ctx.pending_messages = None
                    ctx.agent_results["human_service"] = result_text
                    yield self._event(
                        "human_service",
                        {"agent_results": {"human_service": result_text}, "status": "done"},
                    )
            else:
                result_text = output.text if isinstance(output, SpecialistRunResult) else str(output)
                ctx.agent_results["human_service"] = result_text
                yield self._event(
                    "human_service",
                    {"agent_results": {"human_service": result_text}, "status": "done"},
                )

        ctx.final_answer = asyncio.run(
            self.summarize_agent.run(self._build_summarize_payload(ctx))
        )
        yield self._event("summarize", {"final_answer": ctx.final_answer})

        apply_safety(ctx, evidence=self._format_agent_results(ctx))
        yield self._event(
            "safety",
            {"safety_passed": ctx.safety_passed, "safety_retry": ctx.safety_retry},
        )

        self.memory_saver(ctx)
        yield self._event("memory_save", {})

    async def _run_task(self, task: Task, ctx: AgentContext) -> str:
        """单个任务执行：构造隔离上下文并调用对应子 Agent。

        订单专家可能返回待用户审核确认的写操作（SpecialistRunResult.awaiting_review），
        此时把待确认信息与消息历史落到 ctx，返回空串占位，由 iter_run 在波结束后挂起。
        """
        output = await self.run_specialist(
            task.agent,
            self._build_specialist_context(task.agent, ctx),
            deps=self._specialist_deps(task.agent, ctx),
        )
        if isinstance(output, SpecialistRunResult):
            if output.awaiting_review and output.pending is not None:
                ctx.pending_review = {
                    **self._pending_action(task.agent, output),
                }
                ctx.pending_messages = output.messages
                return ""
            return output.text
        return output

    async def _resume_task(self, task: Task, ctx: AgentContext, decision: dict) -> str | SpecialistRunResult:
        """用户审核确认/修改后续跑：把审批决定注入对应专家，得到最终答复文本。"""
        specialist = self.specialists[task.agent]
        return await specialist.resume(
            messages=ctx.pending_messages,
            call_id=ctx.pending_review["call_id"],
            approved=bool(decision.get("approved")),
            args=decision.get("args"),
            message=decision.get("message", ""),
            regenerate=bool(decision.get("regenerate")),
            agent_deps=self._specialist_deps(task.agent, ctx),
        )

    def _build_tool_action_agent(self) -> Agent:
        """构造通用工具动作执行器；当前仅用于 createHumanService。"""
        model = get_model()
        if model is None:
            raise RuntimeError("LLM 未配置（缺少 OPENAI_API_KEY），无法执行人工服务工具")
        return Agent(
            model,
            output_type=[ToolActionOutput, DeferredToolRequests],
            deps_type=SpecialistDeps,
            system_prompt=_HUMAN_SERVICE_TOOL_PROMPT,
            toolsets=[toolset_for("service")],
        )

    async def _start_human_service_action(
        self, ctx: AgentContext, plan: dict[str, Any]
    ) -> SpecialistRunResult:
        """根据编排器的人工服务计划，生成 createHumanService 待确认工具调用。"""
        payload = {
            "reason": str(plan.get("reason", "") or "").strip(),
            "orderNo": str(plan.get("orderNo", "") or "").strip(),
            "afterSaleNo": str(plan.get("afterSaleNo", "") or "").strip(),
        }
        prompt = (
            "请发起 createHumanService 待确认工具调用，参数必须严格使用以下 JSON；"
            "缺失字段保留为空字符串，由用户在确认表单中补全：\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
        agent = self._build_tool_action_agent()
        async with agent:
            result = await timed_agent_run(
                agent,
                prompt,
                "人工服务工具",
                deps=SpecialistDeps(customer_id=ctx.customer_id),
                usage_limits=UsageLimits(request_limit=_TOOL_ACTION_LIMIT),
            )
        return self._wrap_tool_action(result)

    async def _resume_tool_action(
        self, ctx: AgentContext, decision: dict
    ) -> SpecialistRunResult:
        """用户确认/修改人工服务工具参数后续跑落库。"""
        approved = bool(decision.get("approved"))
        if approved:
            tool_decision = ToolApproved(override_args=decision.get("args") or None)
        elif bool(decision.get("regenerate")):
            feedback = decision.get("message", "") or "用户要求重新填写人工服务申请。"
            tool_decision = ToolDenied(
                message=f"用户要求按以下意见重新生成人工服务申请：{feedback}。请重新发起 createHumanService。"
            )
        else:
            tool_decision = ToolDenied(message=decision.get("message", "") or "用户取消了人工服务申请。")

        agent = self._build_tool_action_agent()
        async with agent:
            result = await agent.run(
                message_history=ctx.pending_messages,
                deferred_tool_results=DeferredToolResults(
                    approvals={ctx.pending_review["call_id"]: tool_decision}
                ),
                deps=SpecialistDeps(customer_id=ctx.customer_id),
                usage_limits=UsageLimits(request_limit=_TOOL_ACTION_LIMIT),
            )
        return self._wrap_tool_action(result)

    @staticmethod
    def _wrap_tool_action(result: Any) -> SpecialistRunResult:
        """把通用工具执行器结果归一为 SpecialistRunResult。"""
        output = result.output
        if isinstance(output, DeferredToolRequests) and output.approvals:
            call = output.approvals[0]
            from agent.agents.order import PendingApproval

            return SpecialistRunResult(
                pending=PendingApproval(
                    tool=call.tool_name,
                    call_id=call.tool_call_id,
                    args=call.args_as_dict(),
                ),
                messages=result.all_messages(),
            )
        if isinstance(output, ToolActionOutput):
            return SpecialistRunResult(text=output.answer.strip())
        return SpecialistRunResult(text=str(output))

    def run(
        self,
        user_input: str,
        session_id: str = "default",
        customer_no: str | None = None,
        customer_id: int | None = None,
    ) -> AgentContext:
        """一次性执行完整客服流程并返回最终上下文。"""
        ctx = AgentContext(
            user_input=user_input,
            session_id=session_id,
            customer_no=customer_no,
            customer_id=customer_id,
        )
        for event_item in self.iter_run(ctx):
            if event_item.get("stage") == "awaiting_review":
                break
        return ctx
