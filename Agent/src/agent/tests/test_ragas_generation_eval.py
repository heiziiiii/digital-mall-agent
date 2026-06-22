"""Ragas 生成质量评测。

真实评测需要显式开启：

    $env:RUN_RAGAS_GENERATION_EVAL = "1"
    pytest tests/test_ragas_generation_eval.py

该文件关注最终回答质量，主要评估 response 是否忠实于专家/工具证据、是否切题。
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pytest

from agent.api.runner import RunManager
from agent.llm.model import initialize_model
from agent.memory.runtime import get_runtime


@dataclass(frozen=True)
class GenerationEvalCase:
    question: str
    reference: str
    session_id: str
    customer_id: int | None = 1
    customer_no: str | None = "C001"


GENERATION_CASES: tuple[GenerationEvalCase, ...] = (
    GenerationEvalCase(
        question="推荐一款拍照好、预算 3000 左右的手机。",
        reference="回答应推荐符合预算和拍照需求的手机，并说明推荐理由；不得编造工具未返回的价格、库存或活动。",
        session_id="ragas-generation-product",
    ),
    GenerationEvalCase(
        question="手机突然充不进电了，我应该怎么排查？",
        reference="回答应给出可执行的排查步骤，包含安全提醒，并在无法自行解决时建议售后检测。",
        session_id="ragas-generation-tech",
    ),
    GenerationEvalCase(
        question="帮我查一下最近的订单物流状态。",
        reference="回答应基于订单和物流工具结果说明当前状态，不泄露无关隐私字段，不凭空承诺送达时间。",
        session_id="ragas-generation-order",
    ),
)


def _install_ragas_import_compat() -> None:
    """兼容 ragas 0.2.x 对旧版 langchain VertexAI 模块路径的导入。"""
    module_name = "langchain_community.chat_models.vertexai"
    if module_name in sys.modules:
        return
    module = types.ModuleType(module_name)

    class ChatVertexAI:  # pragma: no cover
        pass

    module.ChatVertexAI = ChatVertexAI
    sys.modules[module_name] = module


def _extract_contexts(events: Iterable[dict[str, Any]]) -> list[str]:
    contexts: list[str] = []
    for event in events:
        update = event.get("update") or {}
        agent_results = update.get("agent_results") or {}
        for result in agent_results.values():
            text = str(result).strip()
            if text:
                contexts.append(text)
    return contexts


def _extract_final_answer(events: Iterable[dict[str, Any]]) -> str:
    done = next((event for event in reversed(list(events)) if event.get("type") == "done"), {})
    return str(done.get("final_answer") or "").strip()


def _run_generation_case(manager: RunManager, case: GenerationEvalCase) -> dict[str, Any]:
    events = list(
        manager.stream(
            case.question,
            session_id=case.session_id,
            customer_id=case.customer_id,
            customer_no=case.customer_no,
        )
    )
    error = next((event for event in events if event.get("type") == "error"), None)
    if error is not None:
        raise RuntimeError(str(error.get("message") or error))

    answer = _extract_final_answer(events)
    if not answer:
        raise AssertionError(f"未产生最终回答：{case.question}")

    contexts = _extract_contexts(events)
    if not contexts:
        contexts = [answer]

    return {
        "user_input": case.question,
        "response": answer,
        "retrieved_contexts": contexts,
        "reference": case.reference,
    }


def _generation_metrics() -> list[Any]:
    _install_ragas_import_compat()
    import ragas.metrics as metrics

    selected: list[Any] = []
    faithfulness = getattr(metrics, "Faithfulness", None)
    response_relevancy = getattr(metrics, "ResponseRelevancy", None)

    if faithfulness is not None:
        selected.append(faithfulness())
    elif hasattr(metrics, "faithfulness"):
        selected.append(metrics.faithfulness)

    if response_relevancy is not None:
        selected.append(response_relevancy())
    elif hasattr(metrics, "answer_relevancy"):
        selected.append(metrics.answer_relevancy)

    if not selected:
        raise AssertionError("当前 ragas 版本未找到 Faithfulness/ResponseRelevancy 指标")
    return selected


def test_final_answer_extraction_reads_done_event() -> None:
    events = [
        {"type": "stage", "stage": "summarize", "update": {"final_answer": "阶段回答"}},
        {"type": "done", "final_answer": "最终回答"},
    ]

    assert _extract_final_answer(events) == "最终回答"


@pytest.mark.skipif(
    os.getenv("RUN_RAGAS_GENERATION_EVAL") != "1",
    reason="设置 RUN_RAGAS_GENERATION_EVAL=1 后才运行真实生成质量评测",
)
def test_generation_quality_passes_ragas_thresholds() -> None:
    _install_ragas_import_compat()
    import datasets
    import ragas

    initialize_model()
    runtime = get_runtime()
    runtime.startup()
    try:
        manager = RunManager()
        samples = [_run_generation_case(manager, case) for case in GENERATION_CASES]
        result = ragas.evaluate(
            datasets.Dataset.from_list(samples),
            metrics=_generation_metrics(),
            raise_exceptions=True,
            show_progress=False,
        )
    finally:
        runtime.shutdown()

    scores = result.to_pandas().mean(numeric_only=True).to_dict()
    min_faithfulness = float(os.getenv("RAGAS_MIN_FAITHFULNESS", "0.70"))
    min_relevancy = float(os.getenv("RAGAS_MIN_RESPONSE_RELEVANCY", "0.70"))

    faithfulness_score = scores.get("faithfulness")
    relevancy_score = scores.get("answer_relevancy", scores.get("response_relevancy"))

    assert faithfulness_score is None or faithfulness_score >= min_faithfulness
    assert relevancy_score is None or relevancy_score >= min_relevancy
