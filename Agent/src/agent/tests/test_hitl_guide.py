"""HITL 表单引导 Agent 测试：只基于已有事实整理原因，不编造。"""

from __future__ import annotations

import asyncio

from agent.agents.hitl_guide import HitlGuideAgent


def _agent_without_llm() -> HitlGuideAgent:
    agent = HitlGuideAgent()
    agent._get_agent = lambda: None
    return agent


def test_hitl_guide_rewrites_reason_to_user_perspective() -> None:
    agent = _agent_without_llm()

    output = asyncio.run(
        agent.run(
            tool="createHumanService",
            user_input="我要转人工",
            args={"orderNo": "O1", "reason": "用户要求人工处理退款进度"},
            required_fields=["reason"],
            missing_fields=[],
            default_instruction="默认说明",
        )
    )

    assert output.reason == "我要求人工处理退款进度"
    assert "人工服务表" in output.guide_message
    assert "人工服务表" in output.instruction


def test_hitl_guide_keeps_missing_reason_empty() -> None:
    agent = _agent_without_llm()

    output = asyncio.run(
        agent.run(
            tool="createAfterSale",
            user_input="我要申请售后",
            args={"orderNo": "O1", "type": 1, "reason": ""},
            required_fields=["orderNo", "type", "reason"],
            missing_fields=["reason"],
            default_instruction="默认说明",
        )
    )

    assert output.reason == ""
    assert "售后申请表" in output.guide_message
    assert "提交售后申请" in output.instruction
