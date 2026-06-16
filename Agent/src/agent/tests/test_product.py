"""产品专家输出结构测试。"""

from __future__ import annotations

import asyncio
import json

import pytest

from agent.agents import product
from agent.agents.product import ProductAgent, ProductRecommendationOutput, _product_json


def test_product_output_model_serializes_to_json() -> None:
    output = ProductRecommendationOutput(
        summary="推荐一款续航更好的手机",
        recommendations=[
            {
                "product_no": "P100",
                "name": "示例手机",
                "price": "4999",
                "stock_status": "现货",
                "highlights": ["大电池"],
                "match_score": 88,
                "reason": "符合续航诉求。",
            }
        ],
        notes="",
    )

    payload = json.loads(_product_json(output))

    assert payload["reply_type"] == "product_recommendation"
    assert payload["recommendations"][0]["product_no"] == "P100"
    assert payload["recommendations"][0]["match_score"] == 88


def test_product_grounding_returns_json_when_no_tool_evidence() -> None:
    output = ProductRecommendationOutput(
        summary="推荐商品",
        recommendations=[
            {
                "product_no": "P404",
                "name": "不存在的商品",
                "match_score": 90,
            }
        ],
    )

    grounded = product.ground_product_result(output, tool_outputs=[])

    assert grounded.reply_type == "product_recommendation"
    assert grounded.recommendations == []
    assert "暂未检索到" in grounded.summary


def test_product_run_raises_when_model_unavailable(monkeypatch) -> None:
    # 模型不可用时不再返回占位 JSON，而是直接抛出
    monkeypatch.setattr(product, "get_model", lambda: None)

    with pytest.raises(RuntimeError):
        asyncio.run(ProductAgent().run("推荐一款手机"))


def test_product_request_limit_allows_multi_step_recommendation() -> None:
    assert product._REQUEST_LIMIT >= 16
