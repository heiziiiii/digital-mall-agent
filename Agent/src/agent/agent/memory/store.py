"""多层记忆编排门面：实现回源读取链 + 写穿/异步落库。

由执行器在工作流首尾直接调用。职责分工：
- 读（``load_memory``）：L1 本地热缓存 → L2 Redis 温数据 → Qdrant 记忆快照 → MySQL 最终记录逐层回源；
- 长期召回（``recall_cross_session_memory``）：封装为 Memory Agent 工具，由模型按需调用 Qdrant；
- 写（``save_memory``）：先写 L1/L2 缓存，再异步写 Qdrant 快照/长期语义记忆和 MySQL 最终记录。

事件循环约定：Redis / MySQL / Qdrant / embedding 走记忆运行时的后台 loop（``get_runtime().run``）；
LLM（摘要压缩、画像更新）沿用 Agent 运行链路的 ``asyncio.run`` 临时 loop，避免对话模型客户端
被绑定到记忆 loop。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from agent.agents.memory_extract import MemoryExtractAgent
from agent.agents.memory_summary import (
    LongTermMemoryDraft,
    MemorySummary,
    MemorySummaryAgent,
    ProfileUpdate,
    UserProfile,
)
from agent.config import get_settings
from agent.memory import local_cache, mysql_store, qdrant_store, redis_store
from agent.memory.runtime import get_runtime

if TYPE_CHECKING:
    # 仅用于类型注解；运行时不导入，避免与运行时包初始化形成循环依赖
    from agent.customer_agent import AgentContext

logger = logging.getLogger(__name__)
_memory_extract_agent = MemoryExtractAgent()
_memory_summary_agent = MemorySummaryAgent()
# 兼容旧测试/旧扩展点；新代码使用上面两个独立节点。
_memory_agent = None

# 滑动窗口保留的最近消息条数：最近 3 轮（user/assistant 各算一条，共 6 条）
_WINDOW_MESSAGES = 6
# 触发压缩的历史字符阈值（token 的粗略代理）
_SUMMARY_CHAR_THRESHOLD = 1200


def _default_state() -> dict:
    return {
        "history": [],
        "rolling_summary": "",
        "user_profile": UserProfile().model_dump(),
        "turns": 0,
    }


def _memory_recent_history(rolling_summary: str, history: list[dict]) -> list[dict]:
    """把压缩早期会话记忆放在近期对话窗口前，仅供记忆提取使用。"""
    recent = list(history)
    if not rolling_summary:
        return recent
    return [
        {
            "role": "summary",
            "content": f"压缩早期会话记忆：{rolling_summary}",
        },
        *recent,
    ]


def _coerce_profile(raw: object) -> UserProfile:
    """把持久化的画像（dict 或旧自由文本格式）规整为四维 ``UserProfile``。"""
    if isinstance(raw, UserProfile):
        return raw
    if isinstance(raw, dict):
        # 旧版自由文本画像（如 {"summary": ...}）的多余键会被忽略，退化为空画像。
        return UserProfile.model_validate(raw)
    return UserProfile()


def _is_memory_inspection_query(text: str) -> bool:
    """识别用户在询问系统已记住什么；这类元问题不应沉淀为画像。"""
    normalized = text.strip().lower()
    if not normalized:
        return False
    memory_words = ("记忆", "记住", "画像", "偏好", "memory", "profile")
    ask_words = ("什么", "哪些", "查看", "看看", "有啥", "有什么", "知道", "记得")
    return any(word in normalized for word in memory_words) and any(
        word in normalized for word in ask_words
    )


def _memory_recall_query(user_input: str, rolling_summary: str, user_profile: dict) -> str:
    """构造 Qdrant 语义召回 query；记忆查询类问题使用更贴近长期记忆内容的查询。"""
    if not _is_memory_inspection_query(user_input):
        return user_input

    profile_text = ""
    if isinstance(user_profile, dict):
        profile_text = "；".join(f"{key}: {value}" for key, value in user_profile.items())

    hints = "\n".join(
        item
        for item in (
            "用户长期记忆、历史偏好、关注品类、预算、历史问题、售后/订单上下文、反复关注点",
            f"已知画像：{profile_text}" if profile_text else "",
            f"历史摘要：{rolling_summary}" if rolling_summary else "",
        )
        if item
    )
    return hints or user_input


def _mask_name(value: str) -> str:
    """脱敏姓名/昵称类字段，只保留首尾必要辨识信息。"""
    text = value.strip()
    if len(text) <= 1:
        return "*"
    if len(text) == 2:
        return f"{text[0]}*"
    return f"{text[0]}*{text[-1]}"


def _sanitize_customer(raw: dict | None) -> dict:
    """筛选可进入画像的认证客户资料，避免泄露手机号、地址、证件号等敏感信息。"""
    if not isinstance(raw, dict):
        return {}

    source = raw.get("customer") if isinstance(raw.get("customer"), dict) else raw
    safe: dict = {}
    field_map = {
        "nickname": "nickname",
        "nickName": "nickname",
        "userName": "nickname",
        "name": "display_name",
        "realName": "display_name",
        "memberLevel": "member_level",
        "level": "member_level",
        "vipLevel": "member_level",
        "gender": "gender",
        "status": "status",
    }
    for raw_key, safe_key in field_map.items():
        value = source.get(raw_key)
        if value in (None, ""):
            continue
        if safe_key == "display_name":
            safe[safe_key] = _mask_name(str(value))
        else:
            safe[safe_key] = str(value)
    return safe


def _lightweight_profile(authenticated_customer: dict, full_profile: dict) -> dict:
    """记忆输入端首轮只暴露基础身份和画像概况，避免完整画像过早进入上下文。"""
    profile = {
        "authenticated_customer": authenticated_customer,
        "has_stored_profile": any(
            value not in (None, "", [])
            for value in (full_profile or {}).values()
        ),
    }
    return profile


async def _load_authenticated_customer(customer_id: int | None) -> dict:
    """用户资料工具已禁用，记忆链路不再主动查询或注入客户信息。"""
    return {}


async def _compress(rolling_summary: str, overflow: list[dict]) -> str:
    """把溢出的旧消息压缩进滚动摘要；无模型时退化为朴素拼接截断。"""
    overflow_text = "\n".join(f"{m.get('role', '')}: {m.get('content', '')}" for m in overflow)
    prompt = (
        "请把【已有摘要】与【新增对话】合并压缩为一段简洁的中文对话摘要，"
        "保留关键事实、用户诉求与未决事项，去除寒暄与冗余。\n\n"
        f"【已有摘要】\n{rolling_summary or '（空）'}\n\n【新增对话】\n{overflow_text}"
    )
    try:
        agent = _memory_agent or _memory_summary_agent
        compressed = await agent.simple_chat(
            "你是对话摘要助手，只输出压缩后的摘要文本。", prompt, "滚动摘要压缩"
        )
    except Exception as exc:  # noqa: BLE001 - 压缩失败不应中断主流程
        logger.warning("滚动摘要压缩失败，退化为拼接：%s", exc)
        compressed = None
    if compressed is None:
        return f"{rolling_summary}\n{overflow_text}".strip()[-_SUMMARY_CHAR_THRESHOLD:]
    return compressed


# —— 删：按客户清理长期记忆 ——


async def _purge_customer_async(
    customer_id: int | None,
    customer_no: str | None,
) -> dict:
    """跨四层删除某客户的会话状态、消息流水、画像与长期语义记忆。"""
    session_ids = await mysql_store.list_customer_session_ids(
        customer_id=customer_id,
        customer_no=customer_no,
    )
    # 先清 L1/L2 缓存，避免清库后旧热状态被再次回填
    for session_id in session_ids:
        local_cache.pop(session_id)
        await redis_store.delete_state(session_id)
    deleted = await mysql_store.delete_customer(
        customer_id=customer_id,
        customer_no=customer_no,
    )
    await qdrant_store.delete_customer(
        customer_id=customer_id,
        customer_no=customer_no,
        session_ids=session_ids,
    )
    return {
        "sessions": deleted.get("sessions", 0),
        "messages": deleted.get("messages", 0),
        "session_ids": session_ids,
    }


def purge_customer_memory(
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> dict:
    """按用户身份清理其全部长期记忆（画像、会话状态、消息流水与语义记忆）。

    清理范围覆盖 L1 本地缓存、L2 Redis、L3 MySQL 与 L4 Qdrant。
    ``customer_id`` 与 ``customer_no`` 至少传一个，全空时抛 ``ValueError``。
    """
    if customer_id is None and not customer_no:
        raise ValueError("必须提供 customer_id 或 customer_no")
    return get_runtime().run(_purge_customer_async(customer_id, customer_no))


# —— 读：回源链 + 语义召回 ——


async def _load_state_async(
    session_id: str,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> dict:
    """L2 → Qdrant → MySQL 回源；命中即回填上层，全 miss 返回空状态。"""
    state = await redis_store.get_state(session_id)
    if state is not None:
        return state

    sess = await qdrant_store.load_session(session_id)
    exact_qdrant_session = sess is not None
    if sess is None:
        sess = await qdrant_store.load_latest_customer_session(
            customer_id=customer_id,
            customer_no=customer_no,
        )
    if sess is not None:
        recent = (
            await qdrant_store.recent_messages(
                session_id, get_settings().memory_recent_messages
            )
            if exact_qdrant_session
            else []
        )
        state = {
            "history": recent,
            "rolling_summary": sess["rolling_summary"],
            "user_profile": sess["user_profile"],
            "turns": sess["turns"],
        }
        await redis_store.set_state(session_id, state)
        return state

    sess = await mysql_store.load_session(session_id)
    exact_session = sess is not None
    if sess is None:
        sess = await mysql_store.load_latest_customer_session(
            customer_id=customer_id,
            customer_no=customer_no,
        )
        if sess is None:
            return _default_state()

    recent = (
        await mysql_store.recent_messages(session_id, get_settings().memory_recent_messages)
        if exact_session
        else []
    )
    state = {
        "history": recent,
        "rolling_summary": sess["rolling_summary"],
        "user_profile": sess["user_profile"],
        "turns": sess["turns"],
    }
    await redis_store.set_state(session_id, state)
    await qdrant_store.upsert_session(
        session_id,
        state["rolling_summary"],
        state.get("user_profile", {}),
        state.get("turns", 0),
        customer_id=customer_id,
        customer_no=customer_no,
    )
    return state


async def _recall_async(
    session_id: str,
    query: str,
    top_k: int,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> list[dict]:
    """L4 语义召回：embedding → Qdrant 检索；失败仅告警，返回空。"""
    vector = await qdrant_store.embed(query)
    if vector is None:
        return []
    try:
        memories = await qdrant_store.search(
            session_id,
            vector,
            top_k,
            customer_id=customer_id,
            customer_no=customer_no,
        )
    except Exception as exc:  # noqa: BLE001 - 召回失败不应中断主流程
        logger.warning("语义召回失败：%s", exc)
        return []
    min_score = get_settings().memory_recall_min_score
    filtered: list[dict] = []
    for memory in memories:
        score = float(memory.get("score") or 0)
        if score < min_score:
            continue
        filtered.append(
            {
                "text": str(memory.get("text") or ""),
                "role": str(memory.get("role") or ""),
                "score": score,
                "turn": memory.get("turn"),
                "created_at": str(memory.get("created_at") or ""),
            }
        )
    return filtered


def recall_cross_session_memory(
    *,
    session_id: str,
    query: str,
    top_k: int | None = None,
    customer_id: int | None = None,
    customer_no: str | None = None,
    rolling_summary: str = "",
    user_profile: dict | None = None,
) -> list[dict]:
    """按需召回跨会话长期记忆，供 Memory Agent 工具调用。"""
    normalized_query = (query or "").strip()
    if not normalized_query:
        return []
    settings = get_settings()
    limit = top_k if top_k is not None else settings.memory_recall_top_k
    limit = max(1, min(int(limit), settings.memory_recall_top_k))
    recall_query = _memory_recall_query(
        normalized_query,
        rolling_summary,
        user_profile or {},
    )
    return get_runtime().run(
        _recall_async(
            session_id or "default",
            recall_query,
            limit,
            customer_id=customer_id,
            customer_no=customer_no,
        )
    )


def load_memory(ctx: AgentContext) -> None:
    """读取会话短期记忆并就地写入 ctx；历史超阈值时压缩窗口外旧消息。"""
    session_id = ctx.session_id or "default"
    runtime = get_runtime()

    # L1 命中即用；否则回源 L2→L3 并回填 L1
    state = local_cache.get(session_id)
    if state is None:
        state = runtime.run(
            _load_state_async(
                session_id,
                customer_id=ctx.customer_id,
                customer_no=ctx.customer_no,
            )
        )
        local_cache.put(session_id, state)

    history: list[dict] = list(state.get("history", []))
    rolling_summary: str = state.get("rolling_summary", "")
    user_profile: dict = _coerce_profile(state.get("user_profile", {})).model_dump()

    # 短期记忆固定采用「最新滚动摘要 + 最近 3 条消息」：
    # 只要窗口溢出就把旧消息压缩进摘要，避免后续链路拿到完整历史。
    if len(history) > _WINDOW_MESSAGES:
        overflow = history[:-_WINDOW_MESSAGES]
        history = history[-_WINDOW_MESSAGES:]
        rolling_summary = asyncio.run(_compress(rolling_summary, overflow))
        # 回写压缩结果到各层，避免后续轮次重复压缩
        state["history"] = history
        state["rolling_summary"] = rolling_summary
        local_cache.put(session_id, state)
        runtime.run(redis_store.set_state(session_id, state))

    authenticated_customer = runtime.run(_load_authenticated_customer(ctx.customer_id))

    recent_history = _memory_recent_history(rolling_summary, history)
    recall_tool = lambda query, top_k=None: recall_cross_session_memory(
        session_id=session_id,
        query=query,
        top_k=top_k,
        customer_id=ctx.customer_id,
        customer_no=ctx.customer_no,
        rolling_summary=rolling_summary,
        user_profile=user_profile,
    )

    # 记忆提取节点首轮只接收轻量画像；当模型判断确需完整画像时，再做二次提取。
    extract_agent = _memory_agent or _memory_extract_agent
    extract_payload = {
        "user_input": ctx.user_input,
        "authenticated_customer": authenticated_customer,
        "user_profile": _lightweight_profile(authenticated_customer, user_profile),
        "recent_history": recent_history,
        "profile_scope": "lightweight",
    }
    memory = asyncio.run(extract_agent.extract(extract_payload, recall_tool=recall_tool))
    if getattr(memory, "full_profile_needed", False):
        memory = asyncio.run(
            extract_agent.extract(
                {
                    **extract_payload,
                    "user_profile": user_profile,
                    "profile_scope": "full",
                },
                recall_tool=recall_tool,
            )
        )

    ctx.session_id = session_id
    ctx.history = history
    # 持久滚动摘要保持为窗口压缩产出，不被记忆 Agent 覆盖，避免逐轮自我回写堆积
    ctx.rolling_summary = rolling_summary
    # 本轮背景摘要来自记忆 Agent，仅供本轮下游使用，不落库
    ctx.turn_focus = ""
    ctx.background_summary = memory.background_summary
    # 画像由输出端独立维护；输入端只读不写，直接透传已加载画像
    ctx.user_profile = user_profile
    ctx.recalled_memories = []
    ctx.current_emotion = memory.current_emotion
    # 每轮开始重置本轮派生字段
    ctx.agent_results = {}
    ctx.final_answer = ""
    ctx.safety_passed = True
    ctx.safety_retry = 0
    ctx.safety_feedback = ""


# —— 写：写穿 + 异步落库 ——


async def _persist_async(
    session_id: str,
    state: dict,
    messages: list[dict],
    turn: int,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> None:
    """一次后台 loop 往返内完成 Qdrant 快照 + MySQL 最终记录落库。"""
    await qdrant_store.save_messages(session_id, messages, turn)
    await qdrant_store.upsert_session(
        session_id,
        state["rolling_summary"],
        state.get("user_profile", {}),
        turn,
        customer_id=customer_id,
        customer_no=customer_no,
    )
    await mysql_store.save_messages(session_id, messages, turn)
    await mysql_store.upsert_session(
        session_id,
        state["rolling_summary"],
        state.get("user_profile", {}),
        turn,
        customer_id=customer_id,
        customer_no=customer_no,
    )


async def _index_async(
    session_id: str,
    text: str,
    turn: int,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> None:
    vector = await qdrant_store.embed(text)
    if vector is None:
        logger.info("跳过语义记忆入库：embedding 未返回向量 session_id=%s turn=%d", session_id, turn)
        return
    await qdrant_store.upsert_memory(
        session_id,
        "turn",
        text,
        turn,
        vector,
        customer_id=customer_id,
        customer_no=customer_no,
    )


def _memory_summary_from_legacy(
    profile_update: ProfileUpdate | None = None,
    long_term_memory: LongTermMemoryDraft | None = None,
) -> MemorySummary:
    """兼容旧测试/旧扩展点：把拆分式输出包装成统一记忆总结。"""
    return MemorySummary(
        long_term_memory=long_term_memory or LongTermMemoryDraft(),
        profile_update=profile_update or ProfileUpdate(),
    )


async def _run_memory_summary(
    current_profile: UserProfile,
    user_input: str,
    final_answer: str,
) -> MemorySummary:
    """调用统一记忆总结；旧扩展点没有 summarize_turn 时退回拆分调用。"""
    update_agent = _memory_agent or _memory_summary_agent
    if hasattr(update_agent, "summarize_turn"):
        return await update_agent.summarize_turn(current_profile, user_input, final_answer)

    profile_update = None
    long_term_memory = None
    if hasattr(update_agent, "update_profile"):
        profile_update = await update_agent.update_profile(
            current_profile, user_input, final_answer
        )
    if hasattr(update_agent, "extract_long_term_memory"):
        long_term_memory = await update_agent.extract_long_term_memory(
            user_input, final_answer
        )
    return _memory_summary_from_legacy(profile_update, long_term_memory)


def _apply_profile_update(session_id: str, state: dict, update: ProfileUpdate) -> None:
    """合并画像并持久化；无价值变化时跳过。"""
    if not update.has_update:
        logger.info("跳过用户画像写入：本轮无值得长期保存的新信息 session_id=%s", session_id)
        return

    current_profile = _coerce_profile(state.get("user_profile", {}))
    merged = current_profile.merged_with(update)
    state["user_profile"] = merged.model_dump()
    local_cache.put(session_id, state)
    get_runtime().run(_persist_profile_async(session_id, state))


def _persist_summary_long_term_memory(
    session_id: str,
    draft: LongTermMemoryDraft,
    turn: int,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> None:
    """把统一记忆总结中的长期语义记忆向量化入 Qdrant。"""
    try:
        text = draft.memory_text.strip()
        if not draft.worth_saving or not text:
            logger.info("跳过语义记忆入库：本轮无可长期复用记忆 session_id=%s turn=%d", session_id, turn)
            return
        get_runtime().run(
            _index_async(
                session_id,
                text,
                turn,
                customer_id=customer_id,
                customer_no=customer_no,
            )
        )
    except Exception as exc:  # noqa: BLE001 - 长期记忆入库失败不影响主流程
        logger.warning("语义记忆入库失败：%s", exc)


def _persist_long_term_memory(
    session_id: str,
    user_input: str,
    final_answer: str,
    turn: int,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> None:
    """兼容旧入口：通过统一记忆总结提取并写入长期语义记忆。"""
    state = local_cache.get(session_id) or _default_state()
    current_profile = _coerce_profile(state.get("user_profile", {}))
    try:
        summary = asyncio.run(_run_memory_summary(current_profile, user_input, final_answer))
    except Exception as exc:  # noqa: BLE001 - 长期记忆入库失败不影响主流程
        logger.warning("语义记忆入库失败：%s", exc)
        return
    _persist_summary_long_term_memory(
        session_id,
        summary.long_term_memory,
        turn,
        customer_id=customer_id,
        customer_no=customer_no,
    )


async def _persist_profile_async(session_id: str, state: dict) -> None:
    await redis_store.set_state(session_id, state)
    await qdrant_store.upsert_session(
        session_id,
        state.get("rolling_summary", ""),
        state.get("user_profile", {}),
        state.get("turns", 0),
    )
    await mysql_store.upsert_session(
        session_id,
        state.get("rolling_summary", ""),
        state.get("user_profile", {}),
        state.get("turns", 0),
    )


def _async_profile_update(session_id: str, user_input: str, final_answer: str) -> None:
    """兼容旧入口：通过统一记忆总结维护用户画像。"""
    if _is_memory_inspection_query(user_input):
        logger.info("跳过用户画像更新：本轮是记忆查询类问题 session_id=%s", session_id)
        return

    state = local_cache.get(session_id) or _default_state()
    current_profile = _coerce_profile(state.get("user_profile", {}))
    try:
        summary = asyncio.run(_run_memory_summary(current_profile, user_input, final_answer))
    except Exception as exc:  # noqa: BLE001 - 异步更新失败不影响主流程
        logger.warning("用户画像异步更新失败：%s", exc)
        return

    _apply_profile_update(session_id, state, summary.profile_update)


def _async_memory_summary(
    session_id: str,
    user_input: str,
    final_answer: str,
    turn: int,
    customer_id: int | None,
    customer_no: str | None,
) -> None:
    """后台线程：一次性生成长期记忆、画像更新、实体关系和态度。"""
    if _is_memory_inspection_query(user_input):
        logger.info("跳过记忆总结写入：本轮是记忆查询类问题 session_id=%s turn=%d", session_id, turn)
        return

    state = local_cache.get(session_id) or _default_state()
    current_profile = _coerce_profile(state.get("user_profile", {}))
    try:
        summary = asyncio.run(_run_memory_summary(current_profile, user_input, final_answer))
    except Exception as exc:  # noqa: BLE001 - 记忆总结失败不影响主流程
        logger.warning("记忆总结失败：%s", exc)
        return

    _persist_summary_long_term_memory(
        session_id,
        summary.long_term_memory,
        turn,
        customer_id=customer_id,
        customer_no=customer_no,
    )
    _apply_profile_update(session_id, state, summary.profile_update)


def _trim_state_window(state: dict) -> dict:
    """把温状态裁剪为滚动摘要 + 最近窗口消息。"""
    history = list(state.get("history", []))
    if len(history) <= _WINDOW_MESSAGES:
        state["history"] = history
        return state
    overflow = history[:-_WINDOW_MESSAGES]
    state["history"] = history[-_WINDOW_MESSAGES:]
    state["rolling_summary"] = asyncio.run(
        _compress(str(state.get("rolling_summary") or ""), overflow)
    )
    return state


def _async_durable_write(
    session_id: str,
    state: dict,
    messages: list[dict],
    turn: int,
    user_input: str,
    final_answer: str,
    customer_id: int | None,
    customer_no: str | None,
) -> None:
    """后台写 Qdrant/MySQL；失败只记日志，不回滚已写缓存。"""
    try:
        get_runtime().run(
            _persist_async(
                session_id,
                state,
                messages,
                turn,
                customer_id=customer_id,
                customer_no=customer_no,
            )
        )
    except Exception as exc:  # noqa: BLE001 - 异步持久化失败不能影响主响应
        logger.warning("记忆快照/最终记录异步写入失败：%s", exc)

    if _is_memory_inspection_query(user_input):
        logger.info("跳过记忆总结写入：本轮是记忆查询类问题 session_id=%s turn=%d", session_id, turn)
        return
    _async_memory_summary(
        session_id,
        user_input,
        final_answer,
        turn,
        customer_id,
        customer_no,
    )


def save_memory(ctx: AgentContext) -> None:
    """写入会话记忆：先写缓存，再异步写 Qdrant 和 MySQL。"""
    session_id = ctx.session_id or "default"
    runtime = get_runtime()

    state = local_cache.get(session_id) or _default_state()
    state.setdefault("history", [])

    user_msg = {"role": "user", "content": ctx.user_input}
    bot_msg = {"role": "assistant", "content": ctx.final_answer}
    state["history"].append(user_msg)
    state["history"].append(bot_msg)
    state["rolling_summary"] = ctx.rolling_summary or state.get("rolling_summary", "")
    state["user_profile"] = ctx.user_profile or state.get("user_profile", {})
    state["turns"] = int(state.get("turns", 0)) + 1
    state = _trim_state_window(state)
    turn = state["turns"]

    # 先写 L1 + L2 缓存，让下一轮读取立即可见。
    local_cache.put(session_id, state)
    runtime.run(redis_store.set_state(session_id, state))

    threading.Thread(
        target=_async_durable_write,
        args=(
            session_id,
            state,
            [user_msg, bot_msg],
            turn,
            ctx.user_input,
            ctx.final_answer,
            ctx.customer_id,
            ctx.customer_no,
        ),
        daemon=True,
    ).start()

    # 长期记忆、画像、实体关系与态度已由 _async_durable_write 中的统一记忆总结处理。
