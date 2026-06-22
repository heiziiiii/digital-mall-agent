"""HITL 引导 Agent：为待用户确认的写操作生成表单引导与原因摘要。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agent.hooks import timed_agent_run
from agent.llm.model import get_expert_model as get_model
from agent.prompts.loader import render_skill

logger = logging.getLogger(__name__)


class HitlGuideOutput(BaseModel):
    """HITL 引导阶段标准输出。"""

    reason: str = Field(
        default="",
        description="只基于用户原话和已知参数整理出的第一人称原因；证据不足时留空",
    )
    guide_message: str = Field(
        default="",
        min_length=1,
        description="展示给用户的表单引导语，说明需要核对或补全哪些信息",
    )
    instruction: str = Field(
        default="",
        min_length=1,
        description="展示在表单标题下方的确认说明",
    )


class HitlGuideAgent:
    """专门处理 HITL 表单文案与原因整理的小 Agent。"""

    def __init__(self) -> None:
        self._agent: Agent | None = None

    def _get_agent(self) -> Agent | None:
        if self._agent is None:
            model = get_model()
            if model is None:
                return None
            self._agent = Agent(
                model,
                system_prompt=render_skill("hitl_guide"),
                output_type=HitlGuideOutput,
            )
        return self._agent

    async def run(
        self,
        *,
        tool: str,
        user_input: str,
        args: dict[str, Any],
        required_fields: list[str],
        missing_fields: list[str],
        default_instruction: str,
        context: dict[str, Any] | None = None,
    ) -> HitlGuideOutput:
        """生成 HITL 表单引导；LLM 不可用时使用保守规则兜底。"""
        fallback = self._fallback(
            tool=tool,
            user_input=user_input,
            args=args,
            missing_fields=missing_fields,
            default_instruction=default_instruction,
        )
        agent = self._get_agent()
        if agent is None:
            return fallback

        payload = {
            "tool": tool,
            "user_input": user_input,
            "args": args,
            "required_fields": required_fields,
            "missing_fields": missing_fields,
            "default_instruction": default_instruction,
        }
        if context:
            payload["context"] = context
        try:
            result = await timed_agent_run(
                agent,
                json.dumps(payload, ensure_ascii=False, indent=2),
                "HITL 表单引导",
            )
        except Exception as exc:  # noqa: BLE001 - HITL 引导失败不能阻断核心业务确认
            logger.warning("HITL 引导 Agent 失败，使用兜底文案：%s", exc)
            return fallback

        output = self._merge_with_fallback(result.output, fallback)
        if "reason" in missing_fields:
            output.reason = ""
        return output

    @classmethod
    def _merge_with_fallback(
        cls,
        output: HitlGuideOutput,
        fallback: HitlGuideOutput,
    ) -> HitlGuideOutput:
        # reason 是即将落业务单的用户诉求摘要。若上游已给出结构化原因，
        # 这里只允许做第一人称转换，避免 LLM 借上下文扩写情绪、心理或历史纠纷。
        reason = fallback.reason or (cls._first_person_reason(output.reason) if output.reason else "")
        return HitlGuideOutput(
            reason=reason,
            guide_message=output.guide_message.strip() or fallback.guide_message,
            instruction=output.instruction.strip() or fallback.instruction,
        )

    @classmethod
    def _fallback(
        cls,
        *,
        tool: str,
        user_input: str,
        args: dict[str, Any],
        missing_fields: list[str],
        default_instruction: str,
    ) -> HitlGuideOutput:
        reason = cls._first_person_reason(str(args.get("reason") or ""))
        if not reason:
            reason = cls._first_person_reason(cls._extract_reason_from_user_input(user_input))

        if tool == "createAfterSale":
            guide = (
                "可以，我先把售后申请表整理好了。请补充或核对下面的信息，"
                "尤其是“我的诉求/原因”，确认后我再帮你提交。"
            )
            instruction = "请填写并核对售后申请表，确认后才会提交售后申请。"
        elif tool == "createHumanService":
            guide = (
                "可以，我先把人工服务表整理好了。请补充或核对具体问题，"
                "确认后我再帮你创建人工服务单。"
            )
            instruction = "请填写并核对人工服务表，确认后才会创建人工服务单。"
        elif tool == "createOrder":
            guide = "可以，我先把订单确认表整理好了。请核对信息，确认后我再帮你创建订单。"
            instruction = default_instruction
        else:
            guide = "这一步需要你确认表单信息，确认后我再继续处理。"
            instruction = default_instruction

        if "reason" in missing_fields:
            reason = ""
            guide = guide.replace("补充或核对", "补充")

        return HitlGuideOutput(reason=reason, guide_message=guide, instruction=instruction)

    @staticmethod
    def _extract_reason_from_user_input(user_input: str) -> str:
        text = user_input.strip()
        for marker in ("原因是", "因为", "由于"):
            if marker in text:
                return text.split(marker, 1)[1].strip(" ，。；;")
        return text

    @staticmethod
    def _first_person_reason(raw_reason: str) -> str:
        reason = str(raw_reason or "").strip(" ，。；;")
        if not reason:
            return ""
        replacements: tuple[tuple[str, str], ...] = (
            ("用户希望", "我希望"),
            ("客户希望", "我希望"),
            ("用户想要", "我想要"),
            ("客户想要", "我想要"),
            ("用户需要", "我需要"),
            ("客户需要", "我需要"),
            ("用户要求", "我要求"),
            ("客户要求", "我要求"),
            ("用户反馈", "我反馈"),
            ("客户反馈", "我反馈"),
            ("用户投诉", "我投诉"),
            ("客户投诉", "我投诉"),
        )
        for old, new in replacements:
            reason = reason.replace(old, new)
        if reason.startswith(("需要", "希望", "想要", "要求", "投诉", "申诉", "反馈")):
            reason = f"我{reason}"
        if "用户" in reason or "客户" in reason:
            reason = reason.replace("用户", "我").replace("客户", "我")
        if not re.search(r"(^|[，。；：\s])我", reason):
            reason = f"我想反馈：{reason}"
        return reason[:200]
