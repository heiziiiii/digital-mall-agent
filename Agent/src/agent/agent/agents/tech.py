"""技术专家：FAQ、参数解释与故障排查知识库检索。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from agent.hooks import timed_agent_run
from agent.llm.model import get_expert_model as get_model
from agent.prompts.loader import render_skill
from agent.tools.mcp_client import SpecialistDeps, toolset_for

if TYPE_CHECKING:
    from agent.customer_agent import AgentContext

_REQUEST_LIMIT = 8
NAME = "tech"
LABEL = "技术支持"


class TechSupportOutput(BaseModel):
    """技术专家标准输出结构。"""

    reply_type: Literal["tech_support"] = "tech_support"
    answer: str = Field(
        default="",
        min_length=1,
        description="面向用户的技术支持答复；必须基于知识库或工具证据，危险场景需包含安全提醒",
    )


class TechAgent:
    """技术专家能力：构造知识库上下文并执行 FAQ/故障排查。"""

    name = NAME
    label = LABEL

    def __init__(self) -> None:
        self._agent: Agent | None = None

    def _get_agent(self) -> Agent:
        """惰性构建并复用技术专家 Agent。"""
        if self._agent is None:
            model = get_model()
            if model is None:
                raise RuntimeError(f"LLM 未配置（缺少 OPENAI_API_KEY），无法执行：{LABEL}")
            self._agent = Agent(
                model,
                output_type=TechSupportOutput,
                deps_type=SpecialistDeps,
                system_prompt=(
                    f"{render_skill('tech')}\n\n"
                    "## 输出压缩要求\n"
                    "- answer 只给结论和必要步骤，避免复述检索过程、知识库原文和重复提醒。\n"
                    "- 普通问题控制在 120 字左右；危险场景可适当增加安全提醒。"
                ),
                toolsets=[toolset_for("tech")],
            )
        return self._agent

    def build_context(
        self,
        ctx: AgentContext,
        query: str = "",
        previous_results: str = "",
    ) -> str:
        """构造技术专家上下文，只接收规划任务和依赖结果。"""
        lines: list[str] = []
        if previous_results:
            lines.append(f"【前序处理结果】\n{previous_results}")
        lines.append(f"【任务上下文】{query or ctx.user_input}")
        return "\n".join(lines)

    async def run(self, context: str, deps: SpecialistDeps | None = None) -> str:
        """运行技术专家。"""
        agent = self._get_agent()
        async with agent:
            result = await timed_agent_run(
                agent,
                context,
                LABEL,
                deps=deps or SpecialistDeps(),
                usage_limits=UsageLimits(request_limit=_REQUEST_LIMIT),
            )
        return result.output.answer.strip()
