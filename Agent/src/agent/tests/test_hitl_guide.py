"""HITL 表单引导 Agent 测试：只基于已有事实整理原因，不编造。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import agent.agents.hitl_guide as hitl_guide_module
from agent.agents.hitl_guide import HitlGuideAgent, HitlGuideOutput


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


def test_hitl_guide_drops_llm_reason_when_reason_is_missing(monkeypatch) -> None:
    agent = HitlGuideAgent()
    agent._get_agent = lambda: object()

    async def fake_run(_agent, _prompt, _purpose):
        return SimpleNamespace(
            output=HitlGuideOutput(
                reason="我想处理订单 O202606040002 的退货问题",
                guide_message="请补充退货原因",
                instruction="确认后才会提交售后申请。",
            )
        )

    monkeypatch.setattr(hitl_guide_module, "timed_agent_run", fake_run)

    output = asyncio.run(
        agent.run(
            tool="createAfterSale",
            user_input="我要退最近那一笔订单苹果",
            args={"orderNo": "O202606040002", "type": 3, "reason": ""},
            required_fields=["orderNo", "type", "reason"],
            missing_fields=["reason"],
            default_instruction="默认说明",
        )
    )

    assert output.reason == ""
    assert output.guide_message == "请补充退货原因"
