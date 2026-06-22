"""Ragas 检索质量评测。

真实评测需要显式开启：

    $env:RUN_RAGAS_RETRIEVAL_EVAL = "1"
    pytest tests/test_ragas_retrieval_eval.py

该文件关注 Agent 专家阶段/工具阶段产出的证据质量，主要评估 retrieved_contexts
是否能覆盖用户问题与参考答案。
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
class RetrievalEvalCase:
    question: str
    reference: str
    session_id: str
    customer_id: int | None = 1
    customer_no: str | None = "C001"


RETRIEVAL_CASES: tuple[RetrievalEvalCase, ...] = (
    RetrievalEvalCase(
        question="推荐一款拍照好、预算 3000 左右的手机。",
        reference="应检索到预算约 3000 元、拍照能力较好的手机商品证据。",
        session_id="ragas-retrieval-product",
    ),
    RetrievalEvalCase(
        question="手机突然充不进电了，我应该怎么排查？",
        reference="应检索到充电故障排查、安全提醒、充电器或接口检查相关知识。",
        session_id="ragas-retrieval-tech",
    ),
    RetrievalEvalCase(
        question="帮我查一下最近的订单物流状态。",
        reference="应检索到当前客户最近订单及物流状态相关证据。",
        session_id="ragas-retrieval-order",
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


def _extract_retrieved_contexts(events: Iterable[dict[str, Any]]) -> list[str]:
    """从专家阶段事件中提取检索/工具证据。"""
    contexts: list[str] = []
    for event in events:
        update = event.get("update") or {}
        agent_results = update.get("agent_results") or {}
        for agent_name, result in agent_results.items():
            text = str(result).strip()
            if text:
                contexts.append(f"[{agent_name}]\n{text}")
    return contexts


def _run_retrieval_case(manager: RunManager, case: RetrievalEvalCase) -> dict[str, Any]:
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

    contexts = _extract_retrieved_contexts(events)
    if not contexts:
        raise AssertionError(f"未产生检索上下文：{case.question}")

    return {
        "user_input": case.question,
        "retrieved_contexts": contexts,
        "reference": case.reference,
    }


def _retrieval_metrics() -> list[Any]:
    _install_ragas_import_compat()
    import ragas.metrics as metrics

    selected: list[Any] = []
    context_recall = getattr(metrics, "ContextRecall", None)
    context_precision = getattr(metrics, "ContextPrecision", None)

    if context_recall is not None:
        selected.append(context_recall())
    elif hasattr(metrics, "context_recall"):
        selected.append(metrics.context_recall)

    if context_precision is not None:
        selected.append(context_precision())
    elif hasattr(metrics, "context_precision"):
        selected.append(metrics.context_precision)

    if not selected:
        raise AssertionError("当前 ragas 版本未找到 ContextRecall/ContextPrecision 指标")
    return selected


def test_retrieval_context_extraction_keeps_agent_names() -> None:
    events = [
        {
            "type": "stage",
            "stage": "tech_agent",
            "update": {"agent_results": {"tech": "检查充电器、线缆和充电口。"}},
        }
    ]

    assert _extract_retrieved_contexts(events) == ["[tech]\n检查充电器、线缆和充电口。"]


@pytest.mark.skipif(
    os.getenv("RUN_RAGAS_RETRIEVAL_EVAL") != "1",
    reason="设置 RUN_RAGAS_RETRIEVAL_EVAL=1 后才运行真实检索质量评测",
)
def test_retrieval_quality_passes_ragas_thresholds() -> None:
    _install_ragas_import_compat()
    import datasets
    import ragas

    initialize_model()
    runtime = get_runtime()
    runtime.startup()
    try:
        manager = RunManager()
        samples = [_run_retrieval_case(manager, case) for case in RETRIEVAL_CASES]
        result = ragas.evaluate(
            datasets.Dataset.from_list(samples),
            metrics=_retrieval_metrics(),
            raise_exceptions=True,
            show_progress=False,
        )
    finally:
        runtime.shutdown()

    scores = result.to_pandas().mean(numeric_only=True).to_dict()
    min_context_recall = float(os.getenv("RAGAS_MIN_CONTEXT_RECALL", "0.70"))
    min_context_precision = float(os.getenv("RAGAS_MIN_CONTEXT_PRECISION", "0.60"))

    recall_score = scores.get("context_recall")
    precision_score = scores.get("context_precision")

    assert recall_score is None or recall_score >= min_context_recall
    assert precision_score is None or precision_score >= min_context_precision
