"""记忆提取节点：为本轮输入构建相关背景。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.tools import RunContext

from agent.hooks import timed_agent_run
from agent.llm.model import get_memory_model
from agent.prompts.loader import render_skill

RecallFn = Callable[[str, int | None], list[dict]]
Emotion = Literal["中性", "焦急", "困惑", "愤怒/不满", "满意/感谢"]


class LongTermMemory(BaseModel):
    """记忆提取节点选中的长期记忆条目。"""

    text: str = Field(default="", description="从长期记忆候选中原样选出的相关记忆文本")
    role: str = Field(default="", description="长期记忆来源角色或类别")
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    turn: int | None = Field(default=None, ge=0)
    created_at: str = Field(default="", description="长期记忆写入时间，ISO 格式")


class MemoryExtraction(BaseModel):
    """输入端提取结果：本轮背景摘要 + 当前情绪。"""

    background_summary: str = Field(default="")
    current_emotion: Emotion = Field(default="中性")
    full_profile_needed: bool = Field(
        default=False,
        description="仅当本轮必须依赖完整用户画像才能理解时为 true",
    )


@dataclass
class RecallDeps:
    """记忆提取依赖；长期召回由模型按需调用。"""

    recall: RecallFn | None = None


class MemoryExtractAgent:
    """输入端节点：提炼本轮背景摘要和当前情绪。"""

    def __init__(self) -> None:
        self._agent: Agent[RecallDeps, MemoryExtraction] | None = None

    @staticmethod
    def _require_model():
        model = get_memory_model()
        if model is None:
            raise RuntimeError("LLM 未配置（缺少 OPENAI_API_KEY），无法执行：记忆提取")
        return model

    def _get_agent(self) -> Agent[RecallDeps, MemoryExtraction]:
        if self._agent is None:
            agent: Agent[RecallDeps, MemoryExtraction] = Agent(
                self._require_model(),
                deps_type=RecallDeps,
                system_prompt=render_skill("memory"),
                output_type=MemoryExtraction,
            )

            @agent.tool
            async def recall_long_term_memory(
                ctx: RunContext[RecallDeps],
                query: str,
                top_k: int | None = None,
            ) -> list[LongTermMemory]:
                """按需检索跨会话长期记忆。

                仅当轻量画像和近期对话不足以理解本轮指代、历史偏好、未决事项或用户明确询问
                系统记住了什么时调用。返回结果已按后端最低相似度阈值过滤；每条包含记忆时间
                `created_at` 和相似度 `score`，低于阈值的记忆不会返回。
                """
                if ctx.deps.recall is None:
                    return []
                return [
                    LongTermMemory.model_validate(item)
                    for item in ctx.deps.recall(query, top_k)
                ]

            self._agent = agent
        return self._agent

    async def extract(
        self,
        payload: dict[str, Any],
        recall_tool: RecallFn | None = None,
    ) -> MemoryExtraction:
        """提炼本轮上下文，不更新任何持久记忆。"""
        result = await timed_agent_run(
            self._get_agent(),
            json.dumps(payload, ensure_ascii=False),
            "记忆提取",
            deps=RecallDeps(recall=recall_tool),
        )
        return result.output


__all__ = [
    "LongTermMemory",
    "MemoryExtractAgent",
    "MemoryExtraction",
]
