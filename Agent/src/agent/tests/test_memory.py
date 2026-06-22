"""多层记忆测试：双节点（输入端提取 / 输出端画像更新）+ 回源链 + 按需语义召回。

全程用 monkeypatch 注入「假后端」与「假运行时」，不依赖真实 Redis/MySQL/Qdrant/LLM。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import agent.memory.store as store
import agent.memory.qdrant_store as qdrant_store
from agent.customer_agent import AgentContext
from agent.agents.memory_extract import MemoryExtraction
from agent.agents.memory_summary import LongTermMemoryDraft, ProfileUpdate, UserProfile


class _FakeRuntime:
    """把协程在临时事件循环里同步跑完，替代真实记忆运行时。"""

    def run(self, coro):
        return asyncio.run(coro)


def test_user_profile_merge_keeps_unchanged_dimensions() -> None:
    current = UserProfile(
        brand_preferences=["Apple"],
        price_range="高端旗舰",
        historical_issues=["iPhone 14 屏幕进灰"],
        tone_preference="简洁直接",
    )
    update = ProfileUpdate(
        has_update=True,
        brand_preferences=["Apple", "华为"],
        historical_issues=["iPhone 14 屏幕进灰", "Mate60 充电异常"],
    )

    merged = current.merged_with(update)

    assert merged.brand_preferences == ["Apple", "华为"]
    assert merged.historical_issues == ["iPhone 14 屏幕进灰", "Mate60 充电异常"]
    assert merged.price_range == "高端旗舰"
    assert merged.tone_preference == "简洁直接"


def test_coerce_profile_drops_legacy_free_text_format() -> None:
    coerced = store._coerce_profile({"summary": "偏好高端旗舰"})
    assert coerced == UserProfile()


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

    assert "customer_no" not in captured["memory_payload"]
    assert "customer_id" not in captured["memory_payload"]
    assert captured["memory_payload"]["authenticated_customer"] == {
        "nickname": "小明",
        "member_level": "VIP",
    }
    assert captured["memory_payload"]["profile_scope"] == "lightweight"
    assert captured["memory_payload"]["user_profile"] == {
        "authenticated_customer": {"nickname": "小明", "member_level": "VIP"},
        "has_stored_profile": True,
    }
    assert ctx.rolling_summary == "老摘要"
    assert captured["memory_payload"]["recent_history"] == [
        {"role": "summary", "content": "压缩早期会话记忆：老摘要"},
        {"role": "user", "content": "早些的问题"},
    ]
    assert "rolling_summary" not in captured["memory_payload"]
    assert ctx.turn_focus == ""
    assert ctx.background_summary == ""
    assert ctx.user_profile == UserProfile(price_range="中端").model_dump()
    assert ctx.history == [{"role": "user", "content": "早些的问题"}]
    assert ctx.recalled_memories == []
    assert ctx.current_emotion == "中性"
    assert captured["recall_tool"] is None
    assert store.local_cache.get("sX") is not None
    assert captured["refilled"]["rolling_summary"] == "老摘要"


def test_load_reruns_memory_extract_with_full_profile_when_requested(monkeypatch) -> None:
    store.local_cache.clear()
    captured: dict = {"payloads": []}
    full_profile = UserProfile(
        brand_preferences=["小米"],
        historical_issues=["小米14 Pro 摄像头无法对焦"],
    ).model_dump()

    async def fake_get_state(_sid):
        return {
            "history": [],
            "rolling_summary": "",
            "user_profile": full_profile,
            "turns": 2,
        }

    async def fake_extract(payload, recall_tool=None):
        captured["payloads"].append(payload)
        if len(captured["payloads"]) == 1:
            return MemoryExtraction(
                current_emotion="中性",
                full_profile_needed=True,
            )
        return MemoryExtraction(
            background_summary="用户历史关注小米14 Pro 摄像头问题。",
            current_emotion="中性",
            full_profile_needed=False,
        )

    async def fake_load_customer(_customer_id):
        return {"nickname": "小明"}

    monkeypatch.setattr(store.redis_store, "get_state", fake_get_state)
    monkeypatch.setattr(store, "_memory_agent", SimpleNamespace(extract=fake_extract))
    monkeypatch.setattr(store, "_load_authenticated_customer", fake_load_customer)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    ctx = AgentContext(user_input="按我的历史问题继续处理", session_id="s-full")
    store.load_memory(ctx)

    assert len(captured["payloads"]) == 2
    assert captured["payloads"][0]["profile_scope"] == "lightweight"
    assert captured["payloads"][0]["user_profile"]["has_stored_profile"] is True
    assert captured["payloads"][1]["profile_scope"] == "full"
    assert captured["payloads"][1]["user_profile"] == full_profile
    assert ctx.background_summary == "用户历史关注小米14 Pro 摄像头问题。"


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
    assert captured["payload"]["recent_history"] == [
        {"role": "summary", "content": "压缩早期会话记忆：最近售后摘要"}
    ]
    assert captured["recall_tool"] is None
    assert ctx.rolling_summary == "最近售后摘要"
    assert ctx.user_profile == legacy_profile


def test_memory_extract_does_not_receive_or_call_long_term_recall(monkeypatch) -> None:
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
        raise AssertionError("记忆提取阶段不应执行长期语义召回")

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
        captured["recall_tool"] = recall_tool
        return MemoryExtraction(
            background_summary="用户长期关注高端旗舰手机与售后规则。",
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

    assert captured["payload"]["recent_history"] == [
        {"role": "summary", "content": "压缩早期会话记忆：用户当前有进行中的换货流程 AS202606030001"}
    ]
    assert captured["recall_tool"] is None
    assert ctx.background_summary == "用户长期关注高端旗舰手机与售后规则。"
    assert ctx.recalled_memories == []


def test_load_hits_local_cache_without_exposing_recall_tool(monkeypatch) -> None:
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
    assert captured["recall_tool"] is None
    assert ctx.current_emotion == "焦急"


def test_load_keeps_recent_three_turns_and_compresses_overflow(monkeypatch) -> None:
    store.local_cache.clear()
    store.local_cache.put(
        "s-window",
        {
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
        return MemoryExtraction(current_emotion="中性")

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

    assert "旧问题1" in captured["compress_prompt"]
    assert captured["payload"]["recent_history"] == [
        {"role": "summary", "content": "压缩早期会话记忆：已有摘要 + 旧对话摘要"},
        {"role": "user", "content": "问题2"},
        {"role": "assistant", "content": "回答2"},
        {"role": "user", "content": "问题3"},
        {"role": "assistant", "content": "回答3"},
        {"role": "user", "content": "最近问题"},
        {"role": "assistant", "content": "最近补充"},
    ]
    assert ctx.history == captured["payload"]["recent_history"][1:]


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

    assert captured["current"] == UserProfile(brand_preferences=["Apple"])
    merged = store.local_cache.get("s-profile")["user_profile"]
    assert merged["brand_preferences"] == ["Apple", "华为"]
    assert merged["price_range"] == "3000-5000 中端"
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


def test_purge_customer_memory_clears_all_layers(monkeypatch) -> None:
    store.local_cache.clear()
    store.local_cache.put("sA", {"history": [], "turns": 1})
    store.local_cache.put("sB", {"history": [], "turns": 2})
    captured: dict = {}

    async def fake_list_session_ids(customer_id=None, customer_no=None):
        captured["list_identity"] = (customer_id, customer_no)
        return ["sA", "sB"]

    async def fake_delete_state(session_id):
        captured.setdefault("redis_deleted", []).append(session_id)

    async def fake_delete_customer(customer_id=None, customer_no=None):
        captured["mysql_identity"] = (customer_id, customer_no)
        return {"sessions": 2, "messages": 7}

    async def fake_qdrant_delete(customer_id=None, customer_no=None, session_ids=None):
        captured["qdrant"] = (customer_id, customer_no, session_ids)

    monkeypatch.setattr(store.mysql_store, "list_customer_session_ids", fake_list_session_ids)
    monkeypatch.setattr(store.redis_store, "delete_state", fake_delete_state)
    monkeypatch.setattr(store.mysql_store, "delete_customer", fake_delete_customer)
    monkeypatch.setattr(store.qdrant_store, "delete_customer", fake_qdrant_delete)
    monkeypatch.setattr(store, "get_runtime", lambda: _FakeRuntime())

    result = store.purge_customer_memory(customer_id=7, customer_no="C007")

    assert store.local_cache.get("sA") is None
    assert store.local_cache.get("sB") is None
    assert captured["redis_deleted"] == ["sA", "sB"]
    assert captured["mysql_identity"] == (7, "C007")
    assert captured["qdrant"] == (7, "C007", ["sA", "sB"])
    assert result["sessions"] == 2
    assert result["messages"] == 7
    assert result["session_ids"] == ["sA", "sB"]


def test_purge_customer_memory_requires_identity() -> None:
    import pytest

    with pytest.raises(ValueError):
        store.purge_customer_memory()


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


def test_authenticated_customer_loader_is_disabled() -> None:
    """用户资料工具禁用后，记忆链路不再直连 MCP 查询客户资料。"""
    result = asyncio.run(store._load_authenticated_customer(7))

    assert result == {}
