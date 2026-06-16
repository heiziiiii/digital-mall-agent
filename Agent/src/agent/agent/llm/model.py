"""PydanticAI 模型工厂：基于 OpenAI 兼容接口构建对话模型。

通过自定义 ``AsyncOpenAI`` 客户端承载 base_url / timeout / max_retries，
再交给 PydanticAI 的 ``OpenAIChatModel`` 使用。未配置 API Key 时返回 None，
上层据此走占位 / 兜底逻辑。
"""

from __future__ import annotations

import logging
from functools import lru_cache

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from agent.config import get_settings

logger = logging.getLogger(__name__)


def _mask_key(key: str) -> str:
    """脱敏 API Key，仅保留首尾，避免日志泄露完整密钥。"""
    if len(key) <= 8:
        return "****"
    return f"{key[:6]}...{key[-4:]}"


@lru_cache(maxsize=1)
def get_model() -> OpenAIChatModel | None:
    """构建并缓存对话模型；未配置 OPENAI_API_KEY 时返回 None。"""
    settings = get_settings()
    if not settings.openai_api_key:
        logger.warning("未配置 OPENAI_API_KEY，LLM 不可用，相关步骤将走占位/兜底逻辑。")
        return None

    # 打印关键配置，便于核对实际命中的模型与接口（不打印完整 key）
    logger.info(
        "初始化 LLM：model=%s base_url=%s timeout=%ss max_retries=%d key=%s",
        settings.openai_model,
        settings.openai_base_url,
        settings.openai_timeout,
        settings.openai_max_retries,
        _mask_key(settings.openai_api_key),
    )

    # 用自定义客户端承载超时与重试，再交给 PydanticAI Provider
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.openai_timeout,
        max_retries=settings.openai_max_retries,
    )
    return OpenAIChatModel(settings.openai_model, provider=OpenAIProvider(openai_client=client))


def initialize_model() -> OpenAIChatModel | None:
    """在服务启动或 CLI 运行前显式初始化模型，避免首轮 Agent 执行时才懒加载。"""
    model = get_model()
    if model is None:
        logger.warning("LLM 预初始化未完成：模型不可用，将使用占位/兜底逻辑。")
    else:
        logger.info("LLM 预初始化完成。")
    return model
