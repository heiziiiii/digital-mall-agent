"""各 skill Agent 的 Pydantic 输出结构测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.agents.orchestrator import TaskSpec
from agent.agents.order import OrderServiceOutput
from agent.agents.summarize import SummarizeOutput
from agent.agents.tech import TechSupportOutput
from agent.prompts.loader import render_skill


def test_text_agents_have_pydantic_output_models() -> None:
    tech = TechSupportOutput(answer="请先重启设备。")
    order = OrderServiceOutput(answer="已查询到订单。")
    summarize = SummarizeOutput(final_answer="这是最终回答。")

    assert tech.reply_type == "tech_support"
    assert tech.answer == "请先重启设备。"
    assert order.reply_type == "order_service"
    assert order.answer == "已查询到订单。"
    assert summarize.final_answer == "这是最终回答。"


def test_pydantic_schemas_have_descriptions_and_type_bounds() -> None:
    tech_answer = TechSupportOutput.model_fields["answer"]
    order_answer = OrderServiceOutput.model_fields["answer"]
    final_answer = SummarizeOutput.model_fields["final_answer"]
    confidence = TaskSpec.model_fields["confidence"]

    assert tech_answer.description
    assert order_answer.description
    assert final_answer.description
    assert confidence.description
    with pytest.raises(ValidationError):
        TaskSpec(agent="product", query="推荐手机", confidence=1.2)


def test_skill_prompts_do_not_expose_output_schema_details() -> None:
    tech_prompt = render_skill("tech")
    order_prompt = render_skill("order")
    summarize_prompt = render_skill("summarize")

    assert "由 Pydantic 解析" not in tech_prompt
    assert "reply_type" not in tech_prompt
    assert "answer" not in tech_prompt
    assert "由 Pydantic 解析" not in order_prompt
    assert "reply_type" not in order_prompt
    assert "answer" not in order_prompt
    assert "按工具调用流程发起对应写操作" in order_prompt
    assert "由 Pydantic 解析" not in summarize_prompt
    assert "final_answer" not in summarize_prompt
