"""总结 Agent：把上下文与专家结果整理成面向用户的自然语言回复。"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agent.hooks import timed_agent_run
from agent.llm.model import get_model
from agent.prompts.loader import render_skill


class SummarizeOutput(BaseModel):
    """回答生成阶段标准输出结构。"""

    final_answer: str = Field(
        default="",
        min_length=1,
        description="面向用户的最终自然语言回复；只能整合上游上下文和专家结果，不得新增事实或泄露内部字段",
    )


class SummarizeAgent:
    """总结能力：把专家结果、历史摘要和用户问题整理成最终回复。"""

    def __init__(self) -> None:
        self._agent: Agent | None = None

    def _get_agent(self) -> Agent:
        """惰性构建并复用总结 Agent。"""
        if self._agent is None:
            model = get_model()
            if model is None:
                raise RuntimeError("LLM 未配置（缺少 OPENAI_API_KEY），无法生成回答")
            self._agent = Agent(
                model,
                system_prompt=render_skill("summarize"),
                output_type=SummarizeOutput,
            )
        return self._agent

    async def run(self, payload: str) -> str:
        """根据汇总后的输入生成最终回答。"""
        result = await timed_agent_run(self._get_agent(), payload, "回答生成")
        return result.output.final_answer.strip()
