"""LLM 调用 hook：统一处理调用、耗时统计与日志记录。"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimitExceeded, UsageLimits

from agent.utils.io_log import print_io
from agent.utils.observability import elapsed_ms, log_agent_call, now_ms

logger = logging.getLogger(__name__)

# 触发调用上限后，留给「强制收尾」的额外请求预算：仅用于让模型基于已知信息直接产出结论。
_FINALIZE_REQUEST_LIMIT = 2
_FINALIZE_INSTRUCTION = (
    "本次允许的工具调用次数已用尽，禁止再调用任何工具。"
    "请立即基于上面已经获取到的信息直接给出最终结论；"
    "若信息不完整，也要在结论中说明已知部分与缺失部分，不要因为信息不足而拒绝作答。"
)


async def timed_agent_run(agent: Agent, prompt: str, purpose: str, **kwargs: Any):
    """执行一次 Agent 调用，并统一记录输入、输出、耗时与异常。

    当本次运行超过 ``usage_limits`` 的请求上限时，不直接抛错中断整条链路，而是用已收集
    到的消息历史发起一次「无工具强制收尾」调用，迫使模型基于已知信息给出结论后正常返回。
    """
    start = now_ms()
    try:
        result = await _run_with_forced_finalize(agent, prompt, purpose, **kwargs)
        print_io(f"{purpose} LLM 调用", {"prompt": prompt}, str(result.output))
        duration_ms = elapsed_ms(start)
        log_agent_call(
            agent_name=purpose,
            label=f"{purpose} LLM 调用",
            prompt={"prompt": prompt},
            output=str(result.output),
            duration_ms=duration_ms,
        )
        logger.info("[%s] LLM 调用成功，耗时 %.2fs", purpose, duration_ms / 1000)
        return result
    except Exception as exc:
        duration_ms = elapsed_ms(start)
        print_io(
            f"{purpose} LLM 调用异常",
            {"prompt": prompt},
            {"error_type": type(exc).__name__, "error": str(exc)},
        )
        log_agent_call(
            agent_name=purpose,
            label=f"{purpose} LLM 调用",
            prompt={"prompt": prompt},
            status="error",
            duration_ms=duration_ms,
            error=exc,
        )
        logger.warning("[%s] LLM 调用失败：%s", purpose, exc)
        raise


async def _run_with_forced_finalize(agent: Agent, prompt: str, purpose: str, **kwargs: Any):
    """驱动一次 agent 运行；命中请求上限时改为基于已收集消息强制收尾。"""
    async with agent.iter(prompt, **kwargs) as run:
        try:
            async for _ in run:
                pass
        except UsageLimitExceeded as exc:
            messages = run.all_messages()
            logger.warning(
                "[%s] 触发请求上限（%s），改为基于已收集信息强制收尾", purpose, exc
            )
            return await _force_finalize(agent, messages, kwargs)
        return run.result


async def _force_finalize(agent: Agent, messages: Any, kwargs: dict[str, Any]):
    """基于已收集的消息历史发起一次无工具收尾调用，迫使模型给出最终结论。"""
    finalize_kwargs = dict(kwargs)
    finalize_kwargs["toolsets"] = []
    finalize_kwargs["usage_limits"] = UsageLimits(request_limit=_FINALIZE_REQUEST_LIMIT)
    return await agent.run(
        _FINALIZE_INSTRUCTION,
        message_history=messages,
        **finalize_kwargs,
    )
