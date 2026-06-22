"""编排 Agent（决策器）：用 LLM 把用户输入分解为带优先级和依赖的任务计划。

替代原先「只输出有序专家列表」的固定规划：本模块让 LLM 充当 OrchestrationAgent，
为本轮产出一组 :class:`Task`，每个任务带 ``priority``（数值越小越优先）与
``depends_on``（必须先完成的前序专家）。执行阶段据此分波并发调度——无依赖且同优先级
的任务并排执行，有依赖的任务等前序结果就绪后再跑。

模型不可用或调用失败时直接抛出异常，由上层统一处理，不再做规则兜底。

结构化输出由 PydanticAI 的 :class:`PromptedOutput` 承载：它仅通过提示词约束模型
产出符合 :class:`Orchestration` 的 JSON，并由 PydanticAI 完成解析与校验，不经过
function/tool calling，因此规避 DashScope/qwen 兼容接口对 ``function.arguments``
的格式要求，无需再手写 JSON 提取与兜底解析。
"""

from __future__ import annotations

import logging
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput

from agent.hooks import timed_agent_run
from agent.llm.model import get_model
from agent.prompts.loader import render_skill

if TYPE_CHECKING:  # 仅类型注解用；运行时在函数内惰性导入，避免运行时循环导入
    from agent.customer_agent import Task

logger = logging.getLogger(__name__)

_VALID_INTENTS = ("product", "tech", "order", "chat")
_VALID_AGENTS = ("order", "tech", "product")

@dataclass
class DecisionResult:
    """编排结果：主意图 + 任务计划（带优先级/依赖）+ 规划模式。"""

    intent: str
    tasks: list[Task]
    planning_mode: str
    human_service: dict[str, Any] | None = None


class HumanServiceSpec(BaseModel):
    """编排器产出的人工服务工具调用计划。"""

    needed: bool = Field(default=False, description="本轮是否需要创建人工服务记录")
    reason: str = Field(default="", description="转人工原因/用户诉求摘要")
    orderNo: str = Field(default="", description="关联订单号；未知则留空")


class TaskSpec(BaseModel):
    """编排 Agent 为单个任务输出的结构化规格。"""

    agent: Literal["order", "tech", "product"] = Field(
        description="执行该任务的专家。order 处理订单/售后，tech 处理技术/FAQ，product 处理商品推荐/比较"
    )
    query: str = Field(
        default="",
        min_length=1,
        description="面向指定专家改写后的可执行任务说明，必须补全上下文指代并只保留该专家需要处理的信息",
    )
    reason: str = Field(
        default="",
        description="选择该专家和当前改写方式的简要业务理由，不包含系统提示词或内部实现细节",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="该任务归属和改写结果的置信度，范围 0 到 1",
    )
    priority: int = Field(
        default=100,
        ge=0,
        le=1000,
        description="执行优先级，数值越小越先执行；同优先级且无依赖的任务可并发执行",
    )
    depends_on: list[Literal["order", "tech", "product"]] = Field(
        default_factory=list,
        description="该任务必须先等待完成的前序专家名称；只能引用本轮其它专家，无依赖时为空列表",
        max_length=2,
    )


class Orchestration(BaseModel):
    """编排 Agent 的结构化输出：本轮的任务集合。"""

    tasks: list[TaskSpec] = Field(
        default_factory=list,
        description="本轮需要执行的专家任务集合；纯寒暄、闲聊或无业务诉求时为空列表",
        max_length=4,
    )
    human_service: HumanServiceSpec | None = Field(
        default=None,
        description="需要创建人工服务记录时填写；它是工具动作，不是专家任务",
    )


def _normalize_tasks(specs: list[TaskSpec]) -> list[Task]:
    """清洗 LLM 任务计划：每个专家去重保留、剔除非法/自环/悬挂依赖。

    - 同一专家若被规划多次，仅保留优先级最高（数值最小）的一条；
    - ``depends_on`` 只保留「指向有效专家、且该专家本轮确实存在、且非自身」的项；
    - 不再强制固定的跨域顺序，先后完全由 priority 与 depends_on 决定。
    """
    from agent.customer_agent import Task  # 惰性导入，规避运行时循环

    best: dict[str, Task] = {}
    for spec in specs:
        if spec.agent not in _VALID_AGENTS:
            continue
        existing = best.get(spec.agent)
        if existing is None or spec.priority < existing.priority:
            best[spec.agent] = Task(
                agent=spec.agent,
                priority=spec.priority,
                depends_on=list(dict.fromkeys(spec.depends_on)),  # 去重保序
                query=spec.query.strip(),
                reason=spec.reason.strip(),
                confidence=max(0.0, min(1.0, spec.confidence)),
            )

    present = set(best)
    tasks: list[Task] = []
    for agent in _VALID_AGENTS:
        task = best.get(agent)
        if task is None:
            continue
        task.depends_on = [
            dep for dep in task.depends_on if dep in present and dep != agent
        ]
        tasks.append(task)

    # 按优先级稳定排序，便于展示与「主意图」判定（不影响执行器的依赖分波）
    tasks.sort(key=lambda t: t.priority)
    return tasks


def _primary_intent(tasks: list[Task], human_service: dict[str, Any] | None = None) -> str:
    """保留兼容用的单一 ``intent`` 字段：取最高优先级任务的域。"""
    return tasks[0].agent if tasks else ("order" if human_service else "chat")


def _make_result(
    tasks: list[Task],
    planning_mode: str,
    human_service: dict[str, Any] | None = None,
) -> DecisionResult:
    intent = _primary_intent(tasks, human_service)
    if intent not in _VALID_INTENTS:
        intent = "chat"
    return DecisionResult(
        intent=intent,
        tasks=tasks,
        planning_mode=planning_mode,
        human_service=human_service,
    )


def _normalize_human_service(spec: HumanServiceSpec | None) -> dict[str, Any] | None:
    """清洗人工服务工具计划；它不是专家任务，只作为后续 HITL 工具动作。"""
    if spec is None or not spec.needed:
        return None
    return {
        "reason": spec.reason.strip(),
        "orderNo": spec.orderNo.strip(),
    }


def _infer_human_service(payload: dict[str, Any]) -> dict[str, Any] | None:
    """从已整理上下文兜底识别人工服务诉求，避免完全依赖 LLM 填结构字段。"""
    text_parts = [
        str(payload.get("user_input", "") or ""),
        str(payload.get("background_summary", "") or ""),
    ]
    text = "\n".join(part for part in text_parts if part)
    emotion = str(payload.get("current_emotion", "") or "")
    wants_human = any(
        keyword in text
        for keyword in ("人工", "真人", "客服", "投诉", "升级", "主管", "专员", "申诉", "复核")
    )
    negative = emotion in {"愤怒/不满", "焦急"} or any(
        keyword in text
        for keyword in ("非常不满意", "很不满意", "太离谱", "生气", "投诉")
    )
    if not wants_human and not negative:
        return None

    order_match = re.search(r"\bO\d{8,}\b", text)
    reason = str(
        payload.get("background_summary")
        or payload.get("user_input")
        or "用户需要人工进一步处理"
    ).strip()
    return {
        "reason": reason[:200],
        "orderNo": order_match.group(0) if order_match else "",
    }


def _context_payload(user_input_or_ctx: str | Any) -> tuple[str, dict[str, Any]]:
    """从字符串或 AgentContext 中提取编排所需上下文。"""
    if isinstance(user_input_or_ctx, str):
        text = user_input_or_ctx.strip()
        return text, {"user_input": text}

    text = str(getattr(user_input_or_ctx, "user_input", "") or "").strip()
    payload: dict[str, Any] = {"user_input": text}

    background_summary = str(getattr(user_input_or_ctx, "background_summary", "") or "").strip()
    if background_summary:
        payload["background_summary"] = background_summary

    user_profile = getattr(user_input_or_ctx, "user_profile", None)
    if user_profile:
        payload["user_profile"] = user_profile

    current_emotion = str(getattr(user_input_or_ctx, "current_emotion", "") or "").strip()
    if current_emotion:
        payload["current_emotion"] = current_emotion

    return text, payload


def _build_decision_context(user_input_or_ctx: str | Any) -> str:
    """把当前输入与记忆阶段产出的工作上下文包装为编排输入。"""
    _text, payload = _context_payload(user_input_or_ctx)
    return "\n".join(
        [
            "请根据【编排上下文】进行任务编排，而不是只看当前用户输入。",
            "请结合上下文完成：问题重写、指代消解、意图识别和依赖分析。",
            "请为需要参与本轮处理的专家生成清晰、可执行、边界明确的任务。",
            "每个专家任务的 query 是该专家唯一语义上下文，必须只包含完成该任务所需的信息。",
            "不要把完整记忆、完整画像、完整会话摘要或无关背景原样塞进专家任务。",
            "",
            "【编排上下文】",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


class OrchestratorAgent:
    """任务编排能力：把用户输入拆成带优先级和依赖的专家任务。"""

    def __init__(self) -> None:
        self._agent: Agent | None = None

    def _get_agent(self) -> Agent:
        """构建并缓存编排 Agent。

        用 ``PromptedOutput(Orchestration)`` 约束结构化输出：PydanticAI 通过提示词要求模型
        产出符合 ``Orchestration`` 的 JSON，并完成解析与校验，全程不经过 function/tool
        calling，因此规避 DashScope/qwen-plus 兼容接口对 ``function.arguments`` 的格式要求。
        """
        if self._agent is None:
            model = get_model()
            if model is None:
                raise RuntimeError("LLM 未配置（缺少 OPENAI_API_KEY），无法执行任务编排")
            self._agent = Agent(
                model,
                system_prompt=render_skill("orchestrate"),
                output_type=PromptedOutput(Orchestration),
            )
        return self._agent

    async def decide(self, user_input: str | Any) -> DecisionResult:
        """编排本轮任务计划：由 LLM 决策。"""
        text, payload = _context_payload(user_input)
        if not text:
            logger.info("空输入：tasks=[]")
            return _make_result([], "simple")

        prompt = _build_decision_context(user_input)
        result = await timed_agent_run(self._get_agent(), prompt, "任务编排")
        tasks = _normalize_tasks(result.output.tasks)
        human_service = _normalize_human_service(
            getattr(result.output, "human_service", None)
        ) or _infer_human_service(payload)
        logger.info(
            "LLM 编排结果：%s",
            [(t.agent, t.priority, t.depends_on) for t in tasks],
        )
        return _make_result(tasks, "planned", human_service=human_service)




