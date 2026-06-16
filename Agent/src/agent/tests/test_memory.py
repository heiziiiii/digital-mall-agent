"""多层记忆测试：双节点（输入端提取 / 输出端画像更新）+ 回源链 + 按需语义召回。

全程用 monkeypatch 注入「假后端」与「假运行时」，不依赖真实 Redis/MySQL/Qdrant/LLM。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import agent.memory.store as store
import agent.memory.qdrant_store as qdrant_store
from agent.customer_agent import AgentContext
from agent.agents.memory_extract import LongTermMemory, MemoryExtraction
from agent.agents.memory_summary import LongTermMemoryDraft, ProfileUpdate, UserProfile


class _FakeRuntime:
    """把协程在临时事件循环里同步跑完，替代真实记忆运行时。"""

    def run(self, coro):
        return asyncio.run(coro)


# —— 输出端：四维画像结构与合并语义 ——


def test_user_profile_merge_keeps_unchanged_dimensions() -> None:
    current = UserProfile(
        brand_preferences=["Apple"],
        price_range="高端旗舰",
        historical_issues=["iPhone 14 屏幕进灰"],
        tone_preference="简洁直接",
    )
    # 只更新品牌与历史问题，其余维度返回 None 表示保持原状
    update = ProfileUpdate(
        has_update=True,
        brand_preferences=["Apple", "华为"],
        historical_issues=["iPhone 14 屏幕进灰", "Mate60 充电异常"],
    )

    merged = current.merged_with(update)

    assert merged.brand_preferences == ["Apple", "华为"]
    assert merged.historical_issues == ["iPhone 14 屏幕进灰", "Mate60 充电异常"]
    # 未变化维度保持原值
    assert merged.price_range == "高端旗舰"
    assert merged.tone_preference == "简洁直接"


def test_coerce_profile_drops_legacy_free_text_format() -> None:
    # 旧版自由文本画像（{"summary": ...}）的多余键被忽略，退化为空的四维画像
    coerced = store._coerce_profile({"summary": "偏好高端旗舰"})
    assert coerced == UserProfile()


# —— 输入端：回源链 + 提取 + 背景摘要 + 情绪 ——


def test_load_falls_back_to_mysql_and_refills_cache(monkeypatch) -> None:
    store.local_cache.clear()
    captured: dict = {}

    async def fake_get_state(_sid):
        return None  # L2 Redis miss

    async def fake_load_session(_sid):
        return {
            "rolling_summary": "老摘要",
            "user_profile": UserProfile(price_range="中端").model_dump(),
            "turns": 5,
        }

    async def fake_recent(_sid, _limit):
        return [{"role": "user", "content": "早些的问题"}]

    async def fake_set_state(_sid, state):
        captured["refilled"] = state  # 回填 Redis

    async def fake_embed(_text):
        return None  # 跳过语义召回

    async def fake_extract(payload, recall_tool=None):
        captured["memory_payload"] = payload
        captured["recall_tool"] = recall_tool
        return MemoryExtraction(
            turn_focus="本轮：用户打招呼",
            background_summary="",
            current_emotion="中性",
        )

    async def fake_load_customer(_customer_id):
        return {"nickname": "小明", "member_level": "VIP"}

    monkeypatch.setattr(store.redis_store, "get_state", fake_get_state)
    monkeypatch.setattr(store.redis_store, "set_state", fake_set_state)
    monkeypatch.setattr(store.qdrant_store, "load_session", fake_load_session)
    monkeypatch.setattr(store.qdrant_store, "recent_messages", fake_recent)
    monkeypatch.setattr(store.qdrant_store, "embed", fake_embed)
    monkeypatch.setattr(
        store,
        "_memory_agent",
        SimpleNamespace(extract=fake_extract),
    )
    monkeypatch.setattr(store, "_load_authenticated_customer", fake_load_customer)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    ctx = AgentContext(user_input="你好", session_id="sX", customer_no="C001", customer_id=1)
    store.load_memory(ctx)

    # 身份字段不进入记忆提取 payload
    assert "customer_no" not in captured["memory_payload"]
    assert "customer_id" not in captured["memory_payload"]
    assert captured["memory_payload"]["authenticated_customer"] == {
        "nickname": "小明",
        "member_level": "VIP",
    }
    # 提取 payload 携带四维画像
    assert captured["memory_payload"]["user_profile"] == UserProfile(price_range="中端").model_dump()
    # 持久滚动摘要保持为加载到的历史摘要，不被记忆 Agent 输出覆盖
    assert ctx.rolling_summary == "老摘要"
    # 本轮工作记忆与背景摘要来自记忆 Agent
    assert ctx.turn_focus == "本轮：用户打招呼"
    assert ctx.background_summary == ""
    # 画像由输入端只读透传：四维结构，不再混入认证资料
    assert ctx.user_profile == UserProfile(price_range="中端").model_dump()
    assert ctx.history == [{"role": "user", "content": "早些的问题"}]
    assert ctx.recalled_memories == []
    assert ctx.current_emotion == "中性"
    assert callable(captured["recall_tool"])
    # 回源后 L1 与 L2 都被回填
    assert store.local_cache.get("sX") is not None
    assert captured["refilled"]["rolling_summary"] == "老摘要"


def test_load_new_session_inherits_latest_customer_profile(monkeypatch) -> None:
    store.local_cache.clear()
    captured: dict = {}
    legacy_profile = UserProfile(
        price_range="高端旗舰", historical_issues=["关注售后规则"]
    ).model_dump()

    async def fake_get_state(_sid):
        return None

    async def fake_load_session(_sid):
        return None

    async def fake_latest_customer_session(**kwargs):
        captured["identity"] = kwargs
        return {
            "rolling_summary": "最近售后摘要",
            "user_profile": legacy_profile,
            "turns": 8,
        }

    async def fake_set_state(_sid, state):
        captured["refilled"] = state

    async def fake_embed(_text):
        return None

    async def fake_extract(payload, recall_tool=None):
        captured["payload"] = payload
        captured["recall_tool"] = recall_tool
        return MemoryExtraction(
            turn_focus="本轮：用户询问记忆内容",
            current_emotion="中性",
        )

    async def fake_load_customer(_customer_id):
        return {}

    monkeypatch.setattr(store.redis_store, "get_state", fake_get_state)
    monkeypatch.setattr(store.redis_store, "set_state", fake_set_state)
    monkeypatch.setattr(store.qdrant_store, "load_session", fake_load_session)
    monkeypatch.setattr(
        store.qdrant_store, "load_latest_customer_session", fake_latest_customer_session
    )
    monkeypatch.setattr(store.qdrant_store, "embed", fake_embed)
    monkeypatch.setattr(store, "_memory_agent", SimpleNamespace(extract=fake_extract))
    monkeypatch.setattr(store, "_load_authenticated_customer", fake_load_customer)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    ctx = AgentContext(
        user_input="现在你对我的记忆有什么",
        session_id="new-session",
        customer_id=3,
        customer_no="C100003",
    )
    store.load_memory(ctx)

    assert captured["identity"] == {"customer_id": 3, "customer_no": "C100003"}
    assert captured["refilled"]["rolling_summary"] == "最近售后摘要"
    assert captured["payload"]["recent_history"] == []
    assert callable(captured["recall_tool"])
    assert ctx.rolling_summary == "最近售后摘要"
    assert ctx.user_profile == legacy_profile


def test_memory_inspection_uses_expanded_qdrant_query(monkeypatch) -> None:
    store.local_cache.clear()
    store.local_cache.put(
        "s-memory-recall",
        {
            "history": [],
            "rolling_summary": "用户当前有进行中的换货流程 AS202606030001",
            "user_profile": UserProfile(price_range="偏好高端旗舰").model_dump(),
            "turns": 2,
        },
    )
    captured: dict = {}

    async def fake_embed(text):
        captured["embedding_query"] = text
        return [0.1, 0.2]

    async def fake_search(_sid, _vector, _top_k, **_kwargs):
        return [
            {
                "text": "用户关注高端旗舰手机和售后规则。",
                "role": "turn",
                "turn": 1,
                "score": 0.91,
            }
        ]

    async def fake_extract(payload, recall_tool=None):
        captured["payload"] = payload
        assert callable(recall_tool)
        recalled = await asyncio.to_thread(recall_tool, payload["user_input"], 2)
        return MemoryExtraction(
            turn_focus="本轮：用户询问记忆内容",
            background_summary="用户长期关注高端旗舰手机与售后规则。",
            long_term_memories=[LongTermMemory(**item) for item in recalled],
            current_emotion="中性",
        )

    async def fake_load_customer(_customer_id):
        return {}

    monkeypatch.setattr(store.qdrant_store, "embed", fake_embed)
    monkeypatch.setattr(store.qdrant_store, "search", fake_search)
    monkeypatch.setattr(
        store,
        "get_settings",
        lambda: SimpleNamespace(memory_recall_top_k=2, memory_recall_min_score=0.85),
    )
    monkeypatch.setattr(store, "_memory_agent", SimpleNamespace(extract=fake_extract))
    monkeypatch.setattr(store, "_load_authenticated_customer", fake_load_customer)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    ctx = AgentContext(user_input="现在你对我的记忆有什么", session_id="s-memory-recall")
    store.load_memory(ctx)

    assert "用户长期记忆" in captured["embedding_query"]
    assert "偏好高端旗舰" in captured["embedding_query"]
    assert "AS202606030001" in captured["embedding_query"]
    assert ctx.background_summary == "用户长期关注高端旗舰手机与售后规则。"
    assert ctx.recalled_memories == [
        {
            "text": "用户关注高端旗舰手机和售后规则。",
            "role": "turn",
            "turn": 1,
            "score": 0.91,
        }
    ]


def test_load_hits_local_cache_and_exposes_recall_tool_without_auto_call(monkeypatch) -> None:
    store.local_cache.clear()
    store.local_cache.put(
        "sR",
        {
            "history": [],
            "rolling_summary": "",
            "user_profile": UserProfile().model_dump(),
            "turns": 0,
        },
    )

    def _boom(*_a, **_k):  # L1 命中则不应回源 Redis
        raise AssertionError("L1 命中时不应访问 Redis")

    async def fake_embed(_text):
        raise AssertionError("load_memory 不应自动执行长期召回")

    async def fake_search(_sid, _vector, _top_k, **_kwargs):
        raise AssertionError("load_memory 不应自动访问 Qdrant")

    monkeypatch.setattr(store.redis_store, "get_state", _boom)
    monkeypatch.setattr(store.qdrant_store, "embed", fake_embed)
    monkeypatch.setattr(store.qdrant_store, "search", fake_search)
    monkeypatch.setattr(
        store,
        "get_settings",
        lambda: SimpleNamespace(memory_recall_top_k=3, memory_recall_min_score=0.75),
    )
    captured: dict = {}

    async def fake_extract(payload, recall_tool=None):
        captured["payload"] = payload
        captured["recall_tool"] = recall_tool
        return MemoryExtraction(
            turn_focus="本轮：用户着急想要推荐",
            current_emotion="焦急",
        )

    async def fake_load_customer(_customer_id):
        return {}

    monkeypatch.setattr(store, "_memory_agent", SimpleNamespace(extract=fake_extract))
    monkeypatch.setattr(store, "_load_authenticated_customer", fake_load_customer)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    ctx = AgentContext(user_input="我很着急，有推荐吗", session_id="sR")
    store.load_memory(ctx)

    assert ctx.recalled_memories == []
    assert ctx.background_summary == ""
    assert callable(captured["recall_tool"])
    assert ctx.current_emotion == "焦急"


def test_load_keeps_recent_three_turns_and_compresses_overflow(monkeypatch) -> None:
    store.local_cache.clear()
    store.local_cache.put(
        "s-window",
        {
            # 8 条消息 = 4 轮；窗口保留最近 3 轮（6 条），最早 1 轮（2 条）溢出压缩
            "history": [
                {"role": "user", "content": "旧问题1"},
                {"role": "assistant", "content": "旧回答1"},
                {"role": "user", "content": "问题2"},
                {"role": "assistant", "content": "回答2"},
                {"role": "user", "content": "问题3"},
                {"role": "assistant", "content": "回答3"},
                {"role": "user", "content": "最近问题"},
                {"role": "assistant", "content": "最近补充"},
            ],
            "rolling_summary": "已有摘要",
            "user_profile": UserProfile().model_dump(),
            "turns": 4,
        },
    )
    captured: dict = {}

    async def fake_simple_chat(_system_prompt, user_prompt, _purpose):
        captured["compress_prompt"] = user_prompt
        return "已有摘要 + 旧对话摘要"

    async def fake_extract(payload, recall_tool=None):
        captured["payload"] = payload
        return MemoryExtraction(turn_focus="本轮：用户继续", current_emotion="中性")

    async def fake_set_state(_sid, state):
        captured["state"] = state

    async def fake_embed(_text):
        return None

    async def fake_load_customer(_customer_id):
        return {}

    monkeypatch.setattr(store.redis_store, "set_state", fake_set_state)
    monkeypatch.setattr(store.qdrant_store, "embed", fake_embed)
    monkeypatch.setattr(
        store,
        "_memory_agent",
        SimpleNamespace(extract=fake_extract, simple_chat=fake_simple_chat),
    )
    monkeypatch.setattr(store, "_load_authenticated_customer", fake_load_customer)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    ctx = AgentContext(user_input="继续", session_id="s-window")
    store.load_memory(ctx)

    # 最早一轮被压缩进滚动摘要
    assert "旧问题1" in captured["compress_prompt"]
    assert captured["payload"]["rolling_summary"] == "已有摘要 + 旧对话摘要"
    # 窗口保留最近 3 轮共 6 条
    assert captured["payload"]["recent_history"] == [
        {"role": "user", "content": "问题2"},
        {"role": "assistant", "content": "回答2"},
        {"role": "user", "content": "问题3"},
        {"role": "assistant", "content": "回答3"},
        {"role": "user", "content": "最近问题"},
        {"role": "assistant", "content": "最近补充"},
    ]
    assert ctx.history == captured["payload"]["recent_history"]


# —— 输出端：记忆总结节点 ——


def test_save_memory_uses_unified_durable_summary_thread(monkeypatch) -> None:
    store.local_cache.clear()

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(store.redis_store, "set_state", _noop)
    monkeypatch.setattr(store.qdrant_store, "save_messages", _noop)
    monkeypatch.setattr(store.qdrant_store, "upsert_session", _noop)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    started: list = []

    class _FakeThread:
        def __init__(self, *args, target=None, **kwargs):
            self.target = target

        def start(self) -> None:
            started.append(self.target)

    monkeypatch.setattr(store.threading, "Thread", _FakeThread)

    ctx = AgentContext(user_input="推荐一款手机", session_id="memory-frequency")
    ctx.final_answer = "好的"

    store.save_memory(ctx)
    store.save_memory(ctx)
    store.save_memory(ctx)

    durable_starts = [t for t in started if t is store._async_durable_write]
    assert len(durable_starts) == 3
    assert store._async_profile_update not in started
    assert store.local_cache.get("memory-frequency")["turns"] == 3


def test_profile_update_merges_and_persists_when_valuable(monkeypatch) -> None:
    store.local_cache.clear()
    store.local_cache.put(
        "s-profile",
        {
            "history": [],
            "rolling_summary": "",
            "user_profile": UserProfile(brand_preferences=["Apple"]).model_dump(),
            "turns": 1,
        },
    )
    captured: dict = {}

    async def fake_update_profile(current_profile, user_input, final_answer):
        captured["current"] = current_profile
        captured["inputs"] = (user_input, final_answer)
        return ProfileUpdate(
            has_update=True,
            brand_preferences=["Apple", "华为"],
            price_range="3000-5000 中端",
        )

    async def fake_persist(session_id, state):
        captured["persisted"] = state

    monkeypatch.setattr(
        store, "_memory_agent", SimpleNamespace(update_profile=fake_update_profile)
    )
    monkeypatch.setattr(store, "_persist_profile_async", fake_persist)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    store._async_profile_update("s-profile", "我也喜欢华为，预算 3000-5000", "好的")

    # 输入端把已有画像作为 UserProfile 传入
    assert captured["current"] == UserProfile(brand_preferences=["Apple"])
    merged = store.local_cache.get("s-profile")["user_profile"]
    assert merged["brand_preferences"] == ["Apple", "华为"]
    assert merged["price_range"] == "3000-5000 中端"
    # 未变化维度保持原状（空）
    assert merged["historical_issues"] == []
    assert merged["tone_preference"] == ""
    assert captured["persisted"]["user_profile"] == merged


def test_profile_update_skips_when_no_valuable_info(monkeypatch) -> None:
    store.local_cache.clear()
    original = UserProfile(brand_preferences=["Apple"]).model_dump()
    store.local_cache.put(
        "s-noise",
        {"history": [], "rolling_summary": "", "user_profile": dict(original), "turns": 1},
    )

    async def fake_update_profile(_current, _user_input, _final_answer):
        return ProfileUpdate(has_update=False)

    def _boom(*_a, **_k):
        raise AssertionError("无价值信息时不应写库")

    monkeypatch.setattr(
        store, "_memory_agent", SimpleNamespace(update_profile=fake_update_profile)
    )
    monkeypatch.setattr(store, "_persist_profile_async", _boom)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    store._async_profile_update("s-noise", "今天天气不错", "是呀")

    # 画像保持原状，未触发写库
    assert store.local_cache.get("s-noise")["user_profile"] == original


def test_memory_inspection_does_not_write_long_term_or_profile(monkeypatch) -> None:
    store.local_cache.clear()
    captured: dict = {"long_term": 0, "profile_llm": 0}

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(store.redis_store, "set_state", _noop)
    monkeypatch.setattr(store.qdrant_store, "save_messages", _noop)
    monkeypatch.setattr(store.qdrant_store, "upsert_session", _noop)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())
    monkeypatch.setattr(
        store,
        "get_settings",
        lambda: SimpleNamespace(memory_profile_update_interval=1),
    )

    def fake_persist_long_term(*_args, **_kwargs):
        captured["long_term"] += 1

    async def fake_update_profile(*_args, **_kwargs):
        captured["profile_llm"] += 1
        return ProfileUpdate(has_update=False)

    class _FakeThread:
        def __init__(self, *args, target=None, **kwargs):
            self.target = target
            self.args = kwargs.get("args", ())

        def start(self) -> None:
            if self.target is not None:
                self.target(*self.args)

    monkeypatch.setattr(store, "_persist_long_term_memory", fake_persist_long_term)
    monkeypatch.setattr(
        store, "_memory_agent", SimpleNamespace(update_profile=fake_update_profile)
    )
    monkeypatch.setattr(store.threading, "Thread", _FakeThread)

    ctx = AgentContext(user_input="现在你对我的记忆有什么", session_id="s-memory-question")
    ctx.final_answer = "回答"
    store.save_memory(ctx)

    assert captured == {"long_term": 0, "profile_llm": 0}


# —— 后端：语义召回 / 长期记忆入库 ——


def test_recall_searches_by_authenticated_customer(monkeypatch) -> None:
    async def fake_embed(_text):
        return [0.1, 0.2]

    captured: dict = {}

    async def fake_search(_sid, _vector, _top_k, **kwargs):
        captured.update(kwargs)
        return [{"text": "用户偏好高端旗舰手机", "role": "turn", "turn": 3, "score": 0.88}]

    monkeypatch.setattr(store.qdrant_store, "embed", fake_embed)
    monkeypatch.setattr(store.qdrant_store, "search", fake_search)
    monkeypatch.setattr(
        store,
        "get_settings",
        lambda: SimpleNamespace(memory_recall_min_score=0.75),
    )

    result = asyncio.run(
        store._recall_async(
            "new-session",
            "推荐手机",
            3,
            customer_id=7,
            customer_no="C007",
        )
    )

    assert captured == {"customer_id": 7, "customer_no": "C007"}
    assert result == [{"text": "用户偏好高端旗舰手机", "role": "turn", "turn": 3, "score": 0.88}]


def test_persist_long_term_memory_indexes_when_worth_saving(monkeypatch) -> None:
    captured: dict = {}

    async def fake_extract(user_input, final_answer):
        captured["extract_input"] = (user_input, final_answer)
        return LongTermMemoryDraft(
            worth_saving=True, memory_text="用户关注 iPhone 退货时的未激活条件。"
        )

    async def fake_index(_session_id, text, _turn, **_kwargs):
        captured["indexed_text"] = text

    monkeypatch.setattr(
        store, "_memory_agent", SimpleNamespace(extract_long_term_memory=fake_extract)
    )
    monkeypatch.setattr(store, "_index_async", fake_index)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    store._persist_long_term_memory("s1", "我要退 iPhone", "需保持未激活", 2)

    assert captured["extract_input"] == ("我要退 iPhone", "需保持未激活")
    assert captured["indexed_text"] == "用户关注 iPhone 退货时的未激活条件。"


def test_persist_long_term_memory_skips_when_not_worth_saving(monkeypatch) -> None:
    async def fake_extract(_user_input, _final_answer):
        return LongTermMemoryDraft(worth_saving=False, memory_text="")

    async def _boom_index(*_a, **_k):
        raise AssertionError("无价值记忆不应入库")

    monkeypatch.setattr(
        store, "_memory_agent", SimpleNamespace(extract_long_term_memory=fake_extract)
    )
    monkeypatch.setattr(store, "_index_async", _boom_index)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    # 不抛异常即视为正确跳过
    store._persist_long_term_memory("s1", "你好", "你好", 1)


def test_qdrant_search_uses_query_points(monkeypatch) -> None:
    """适配 qdrant-client 1.18：语义检索应调用 query_points 而不是旧 search。"""
    captured: dict = {}

    class _Hit:
        payload = {"text": "用户预算 5000", "role": "turn", "turn": 1}
        score = 0.91

    class _FakeClient:
        async def query_points(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(points=[_Hit()])

    monkeypatch.setattr(qdrant_store, "_client", _FakeClient())
    monkeypatch.setattr(
        qdrant_store,
        "get_settings",
        lambda: SimpleNamespace(qdrant_collection="agent_memory"),
    )

    result = asyncio.run(qdrant_store.search("s1", [0.1, 0.2], 3))

    assert captured["collection_name"] == "agent_memory"
    assert captured["query"] == [0.1, 0.2]
    assert captured["limit"] == 3
    assert result == [
        {
            "text": "用户预算 5000",
            "role": "turn",
            "turn": 1,
            "session_id": "",
            "customer_id": None,
            "customer_no": None,
            "score": 0.91,
        }
    ]


def test_qdrant_search_prefers_customer_identity_and_falls_back_to_session(monkeypatch) -> None:
    captured: list[str] = []

    class _Hit:
        def __init__(self, payload, score):
            self.payload = payload
            self.score = score

    class _FakeClient:
        async def query_points(self, **kwargs):
            field = next(
                condition.key
                for condition in kwargs["query_filter"].must
                if condition.key != "memory_kind"
            )
            captured.append(field)
            if field == "customer_id":
                return SimpleNamespace(
                    points=[
                        _Hit(
                            {
                                "text": "跨会话偏好",
                                "role": "turn",
                                "turn": 2,
                                "session_id": "old-session",
                                "customer_id": 7,
                            },
                            0.96,
                        )
                    ]
                )
            if field == "session_id":
                return SimpleNamespace(
                    points=[
                        _Hit(
                            {
                                "text": "当前会话旧格式记忆",
                                "role": "turn",
                                "turn": 1,
                                "session_id": "new-session",
                            },
                            0.86,
                        )
                    ]
                )
            return SimpleNamespace(points=[])

    monkeypatch.setattr(qdrant_store, "_client", _FakeClient())
    monkeypatch.setattr(
        qdrant_store,
        "get_settings",
        lambda: SimpleNamespace(qdrant_collection="agent_memory"),
    )

    result = asyncio.run(
        qdrant_store.search(
            "new-session",
            [0.1, 0.2],
            3,
            customer_id=7,
            customer_no="C007",
        )
    )

    assert captured == [
        "customer_id",
        "customer_id",
        "customer_no",
        "customer_no",
        "session_id",
        "session_id",
    ]
    assert [item["text"] for item in result] == ["跨会话偏好", "当前会话旧格式记忆"]


def test_qdrant_upsert_memory_writes_customer_identity(monkeypatch) -> None:
    captured: dict = {}

    class _FakeClient:
        async def upsert(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(qdrant_store, "_client", _FakeClient())
    monkeypatch.setattr(
        qdrant_store,
        "get_settings",
        lambda: SimpleNamespace(qdrant_collection="agent_memory"),
    )

    asyncio.run(
        qdrant_store.upsert_memory(
            "s1",
            "turn",
            "用户：推荐手机\n客服：推荐旗舰",
            4,
            [0.1, 0.2],
            customer_id=7,
            customer_no="C007",
        )
    )

    point = captured["points"][0]
    assert captured["collection_name"] == "agent_memory"
    assert point.payload["session_id"] == "s1"
    assert point.payload["customer_id"] == 7
    assert point.payload["customer_no"] == "C007"


# —— 认证资料脱敏 ——


def test_customer_profile_is_sanitized_before_memory_agent() -> None:
    result = store._sanitize_customer(
        {
            "found": True,
            "customer": {
                "userId": 1,
                "phone": "13812345678",
                "email": "a@example.com",
                "address": "北京市朝阳区",
                "realName": "张三",
                "memberLevel": "VIP",
            },
        }
    )

    assert result == {"display_name": "张*", "member_level": "VIP"}


def test_authenticated_customer_direct_call_opens_mcp_session(monkeypatch) -> None:
    """认证资料直连 MCP 时也必须进入会话，避免工具清单未初始化。"""

    events: list[str] = []

    class _FakeMcpServer:
        async def __aenter__(self):
            events.append("enter")
            return self

        async def __aexit__(self, *_exc_info):
            events.append("exit")

        async def direct_call_tool(self, name, args):
            events.append(f"call:{name}:{args['userId']}")
            return {"customer": {"realName": "张三", "memberLevel": "VIP"}}

    monkeypatch.setattr(store, "get_mcp_server", lambda: _FakeMcpServer())

    result = asyncio.run(store._load_authenticated_customer(7))

    assert events == ["enter", "call:getCustomerById:7", "exit"]
    assert result == {"display_name": "张*", "member_level": "VIP"}
