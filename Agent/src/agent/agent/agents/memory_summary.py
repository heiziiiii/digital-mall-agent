"""记忆总结节点：统一维护长期语义记忆、用户画像与实体关系。"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agent.hooks import timed_agent_run
from agent.llm.model import get_model
from agent.prompts.loader import render_skill


class UserProfile(BaseModel):
    """长期用户画像：无新变化的维度保持原值。"""

    brand_preferences: list[str] = Field(
        default_factory=list,
        description="品牌偏好：用户明确表达过偏好或倾向的品牌名称列表；无则留空",
    )
    price_range: str = Field(
        default="",
        description="价位偏好：用户可接受的价格区间或消费层级，如『3000-5000 中端』『高端旗舰』；无则留空",
    )
    historical_issues: list[str] = Field(
        default_factory=list,
        description="历史问题：用户过去遇到的具体问题、痛点或故障记录，需具体化；无则留空",
    )
    tone_preference: str = Field(
        default="",
        description="语气偏好：用户偏好的回答风格；无则留空",
    )
    entities: list[str] = Field(
        default_factory=list,
        description="与用户长期服务相关的实体，如商品、订单、售后单、品牌或场景",
    )
    user_relations: list[str] = Field(
        default_factory=list,
        description="用户与实体之间的稳定关系，如已购买、正在售后、偏好、排斥",
    )
    attitudes: list[str] = Field(
        default_factory=list,
        description="用户对实体、服务或流程的稳定态度，不保存临时情绪",
    )

    def merged_with(self, update: "ProfileUpdate") -> "UserProfile":
        """按维度合并更新：``update`` 中为 ``None`` 的维度保持原值。"""
        return UserProfile(
            brand_preferences=(
                update.brand_preferences
                if update.brand_preferences is not None
                else self.brand_preferences
            ),
            price_range=(
                update.price_range if update.price_range is not None else self.price_range
            ),
            historical_issues=(
                update.historical_issues
                if update.historical_issues is not None
                else self.historical_issues
            ),
            tone_preference=(
                update.tone_preference
                if update.tone_preference is not None
                else self.tone_preference
            ),
            entities=update.entities if update.entities is not None else self.entities,
            user_relations=(
                update.user_relations
                if update.user_relations is not None
                else self.user_relations
            ),
            attitudes=update.attitudes if update.attitudes is not None else self.attitudes,
        )


class ProfileUpdate(BaseModel):
    """输出端画像更新决策。"""

    has_update: bool = Field(
        default=False,
        description="本轮是否产生值得长期保存、对后续服务有参考价值的画像新信息",
    )
    brand_preferences: list[str] | None = Field(default=None)
    price_range: str | None = Field(default=None)
    historical_issues: list[str] | None = Field(default=None)
    tone_preference: str | None = Field(default=None)
    entities: list[str] | None = Field(default=None)
    user_relations: list[str] | None = Field(default=None)
    attitudes: list[str] | None = Field(default=None)


class LongTermMemoryDraft(BaseModel):
    """输出端：从本轮对话提取的、可长期保存的语义记忆草稿。"""

    worth_saving: bool = Field(default=False)
    memory_text: str = Field(default="")


class ExtractedEntity(BaseModel):
    """本轮提取出的关键实体。"""

    name: str = Field(default="", description="实体名称，需来自本轮对话")
    type: str = Field(
        default="其他",
        description="实体类型，如 用户、商品、品牌、订单、售后单、服务、问题、偏好",
    )
    attributes: list[str] = Field(
        default_factory=list,
        description="实体的关键属性，必须来自本轮对话",
    )


class UserEntityRelation(BaseModel):
    """用户与实体之间的关系。"""

    entity: str = Field(default="", description="关系指向的实体名称")
    relation: str = Field(
        default="",
        description="用户与实体的关系，如 已购买、想退货、偏好、排斥、正在处理售后",
    )
    evidence: str = Field(default="", description="支撑该关系的简短证据")


class UserAttitude(BaseModel):
    """用户对实体、服务或流程的态度。"""

    target: str = Field(default="", description="态度对象")
    attitude: str = Field(
        default="",
        description="态度描述，如 喜欢、担忧、不满、认可、排斥、关注",
    )
    evidence: str = Field(default="", description="支撑该态度的简短证据")


class MemorySummary(BaseModel):
    """输出端统一记忆总结。"""

    long_term_memory: LongTermMemoryDraft = Field(default_factory=LongTermMemoryDraft)
    profile_update: ProfileUpdate = Field(default_factory=ProfileUpdate)
    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=8)
    user_relations: list[UserEntityRelation] = Field(default_factory=list, max_length=8)
    attitudes: list[UserAttitude] = Field(default_factory=list, max_length=8)


class TextGenerationOutput(BaseModel):
    """轻量文本生成阶段的统一结构化输出。"""

    text: str = Field(default="", description="本次轻量 LLM 任务生成的最终文本内容")


class MemorySummaryAgent:
    """输出端节点：滚动摘要压缩、长期语义记忆、画像、实体关系总结。"""

    def __init__(self) -> None:
        self._summary_agent: Agent[None, MemorySummary] | None = None

    @staticmethod
    def _require_model(purpose: str):
        model = get_model()
        if model is None:
            raise RuntimeError(f"LLM 未配置（缺少 OPENAI_API_KEY），无法执行：{purpose}")
        return model

    def _get_summary_agent(self) -> Agent[None, MemorySummary]:
        if self._summary_agent is None:
            self._summary_agent = Agent(
                self._require_model("记忆总结"),
                system_prompt=render_skill("memory_summary"),
                output_type=MemorySummary,
            )
        return self._summary_agent

    async def simple_chat(self, system_prompt: str, user_prompt: str, purpose: str) -> str:
        """一次性轻量文本生成，当前用于滚动摘要压缩。"""
        agent = Agent(
            self._require_model(purpose),
            system_prompt=system_prompt,
            output_type=TextGenerationOutput,
        )
        result = await timed_agent_run(agent, user_prompt, purpose)
        return result.output.text.strip()

    async def summarize_turn(
        self,
        current_profile: UserProfile,
        user_input: str,
        final_answer: str,
    ) -> MemorySummary:
        """一次性总结本轮长期记忆、画像更新、实体关系与态度。"""
        payload = {
            "current_profile": current_profile.model_dump(),
            "user_input": user_input,
            "assistant_answer": final_answer,
        }
        result = await timed_agent_run(
            self._get_summary_agent(),
            json.dumps(payload, ensure_ascii=False),
            "记忆总结",
        )
        return result.output

    async def update_profile(
        self,
        current_profile: UserProfile,
        user_input: str,
        final_answer: str,
    ) -> ProfileUpdate:
        """兼容旧调用：从统一记忆总结中取画像更新部分。"""
        summary = await self.summarize_turn(current_profile, user_input, final_answer)
        return summary.profile_update

    async def extract_long_term_memory(
        self,
        user_input: str,
        final_answer: str,
    ) -> LongTermMemoryDraft:
        """兼容旧调用：从统一记忆总结中取长期记忆部分。"""
        summary = await self.summarize_turn(UserProfile(), user_input, final_answer)
        return summary.long_term_memory
