"""会话运行管理器测试：确保运行线程与记忆会话相互隔离。"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from agent.api import routes
from agent.api.schemas import MemoryAppendRequest
from agent.api.runner import RunManager, RunSession


def _fake_iter_run(ctx):
    ctx.final_answer = f"answer:{ctx.session_id}"
    yield {"type": "stage", "stage": "memory_load", "label": "记忆提取", "update": {}}


class _FakeCustomerAgent:
    def iter_run(self, ctx):
        return _fake_iter_run(ctx)


class _HitlCustomerAgent:
    def __init__(self) -> None:
        self.decisions: list[dict] = []

    def iter_run(self, ctx):
        decision = yield {
            "type": "stage",
            "stage": "awaiting_review",
            "label": "待用户确认",
            "update": {
                "pending_action": {
                    "kind": "tool_approval",
                    "tool": "createAfterSale",
                    "call_id": "call_1",
                    "args": {"orderNo": "O1", "type": 3, "reason": "仅退款"},
                    "required_fields": ["orderNo", "type", "reason"],
                }
            },
        }
        self.decisions.append(decision)
        ctx.final_answer = "confirmed"
        yield {"type": "stage", "stage": "order_agent", "label": "订单售后", "update": {}}


def test_stream_returns_distinct_thread_and_session() -> None:
    manager = RunManager()
    manager._customer_agent = _FakeCustomerAgent()

    events = list(manager.stream("你好"))

    start = events[0]
    done = events[-1]
    assert start["type"] == "start"
    assert done["type"] == "done"
    assert start["thread_id"] != start["session_id"]
    assert done["thread_id"] == start["thread_id"]
    assert done["session_id"] == start["session_id"]


def test_stream_reuses_memory_session_but_not_thread() -> None:
    manager = RunManager()
    manager._customer_agent = _FakeCustomerAgent()

    first_start = list(manager.stream("第一轮", session_id="s1"))[0]
    second_start = list(manager.stream("第二轮", session_id="s1"))[0]

    assert first_start["session_id"] == "s1"
    assert second_start["session_id"] == "s1"
    assert first_start["thread_id"] != second_start["thread_id"]


def test_stream_accepts_previous_thread_id_as_session_alias() -> None:
    manager = RunManager()
    manager._customer_agent = _FakeCustomerAgent()

    first_start = list(manager.stream("第一轮", session_id="s1"))[0]
    second_start = list(manager.stream("第二轮", session_id=first_start["thread_id"]))[0]

    assert second_start["session_id"] == "s1"
    assert second_start["thread_id"] != first_start["thread_id"]


def test_new_session_ignores_stale_session_id() -> None:
    manager = RunManager()
    manager._customer_agent = _FakeCustomerAgent()

    start = list(manager.stream("新对话", session_id="s1", new_session=True))[0]

    assert start["session_id"] != "s1"
    assert start["thread_id"] != start["session_id"]


def test_confirm_requires_completed_after_sale_fields() -> None:
    manager = RunManager()
    session = RunSession(
        thread_id="t1",
        session_id="s1",
        status="awaiting_review",
        pending_review={
            "tool": "createAfterSale",
            "args": {"orderNo": "O1", "type": 3, "reason": ""},
            "required_fields": ["orderNo", "type", "reason"],
        },
    )
    manager._sessions["t1"] = session

    with pytest.raises(ValueError, match="reason"):
        manager.confirm("t1", approved=True, args={"orderNo": "O1", "type": 3})


def test_confirm_requires_human_service_reason() -> None:
    manager = RunManager()
    session = RunSession(
        thread_id="t1",
        session_id="s1",
        status="awaiting_review",
        pending_review={
            "tool": "createHumanService",
            "args": {"orderNo": "O1", "reason": ""},
            "required_fields": ["reason"],
        },
    )
    manager._sessions["t1"] = session

    with pytest.raises(ValueError, match="reason"):
        manager.confirm("t1", approved=True, args={"orderNo": "O1"})


def test_awaiting_review_expires_before_confirm() -> None:
    manager = RunManager()
    manager._review_ttl = 1
    session = RunSession(
        thread_id="t-expire",
        session_id="s1",
        status="awaiting_review",
        pending_review={
            "tool": "createAfterSale",
            "args": {"orderNo": "O1", "type": 3, "reason": "仅退款"},
            "required_fields": ["orderNo", "type", "reason"],
        },
    )
    session.review_started_at = time.monotonic() - 2
    manager._sessions[session.thread_id] = session

    with pytest.raises(ValueError, match="error"):
        manager.confirm(
            session.thread_id,
            approved=True,
            args={"orderNo": "O1", "type": 3, "reason": "仅退款"},
        )

    assert session.status == "error"
    assert session.pending_review is None
    assert "超时" in session.error


def test_cleanup_removes_finished_sessions_after_ttl() -> None:
    manager = RunManager()
    manager._session_ttl = 1
    session = RunSession(thread_id="t-old", session_id="s1", status="completed")
    session.completed_at = time.monotonic() - 2
    manager._sessions[session.thread_id] = session

    assert manager.cleanup_expired_sessions() == 1
    with pytest.raises(KeyError):
        manager.get(session.thread_id)


def test_stream_stops_at_awaiting_review_without_auto_denial() -> None:
    manager = RunManager()
    fake = _HitlCustomerAgent()
    manager._customer_agent = fake

    events = list(manager.stream("我要退款"))

    assert events[-1]["stage"] == "awaiting_review"
    assert not any(event.get("type") == "done" for event in events)
    thread_id = events[0]["thread_id"]
    session = manager.get(thread_id)
    assert session.status == "awaiting_review"
    assert session.pending_review["call_id"] == "call_1"
    assert fake.decisions == []


def test_confirm_can_resume_stream_session_after_review() -> None:
    manager = RunManager()
    fake = _HitlCustomerAgent()
    manager._customer_agent = fake

    events = list(manager.stream("我要退款"))
    thread_id = events[0]["thread_id"]

    session = manager.confirm(
        thread_id,
        approved=True,
        args={"orderNo": "O1", "type": 3, "reason": "仅退款"},
    )
    assert session.worker is not None
    session.worker.join(timeout=2)

    deadline = time.time() + 2
    while session.status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert session.status == "completed"
    assert session.final_answer == "confirmed"
    assert fake.decisions[0]["approved"] is True


def test_confirm_order_owner_validation_rejects_foreign_order(monkeypatch) -> None:
    class _Runtime:
        @staticmethod
        def run(coro):
            coro.close()
            return 3

    monkeypatch.setattr(routes, "get_runtime", lambda: _Runtime())

    with pytest.raises(HTTPException) as exc:
        routes._validate_confirm_order_owner(
            {
                "tool": "createAfterSale",
                "args": {"orderNo": "O1", "type": 1, "reason": "退货"},
            },
            None,
            customer_id=5,
        )

    assert exc.value.status_code == 409
    assert "不属于当前登录用户" in exc.value.detail


def test_append_memory_records_external_business_event(monkeypatch) -> None:
    saved = {}

    def _save_memory(ctx):
        saved["session_id"] = ctx.session_id
        saved["user_input"] = ctx.user_input
        saved["final_answer"] = ctx.final_answer
        saved["customer_id"] = ctx.customer_id

    monkeypatch.setattr(routes.memory_store, "save_memory", _save_memory)

    response = routes.append_memory(
        MemoryAppendRequest(
            session_id="s1",
            user_message="立即下单：小米 14 Pro（P10006）x1",
            assistant_message="已为你创建待付款订单 O200。",
        ),
        x_customer_id="5",
    )

    assert response.status == "completed"
    assert response.session_id == "s1"
    assert saved == {
        "session_id": "s1",
        "user_input": "立即下单：小米 14 Pro（P10006）x1",
        "final_answer": "已为你创建待付款订单 O200。",
        "customer_id": 5,
    }


