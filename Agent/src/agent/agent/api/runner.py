"""会话运行管理器：支持「后台执行 / 暂停 / 从阶段边界恢复」。

编排由 ``CustomerAgent.iter_run`` 返回的**同步生成器**承载，它在每完成一个阶段后挂起于
``yield``。本管理器据此实现：

- 执行：在独立守护线程中逐事件消费生成器（阶段内部用 ``asyncio.run`` 跑异步 Agent）。
- 暂停：置 Event 标志，worker 在「当前阶段完成（收到其事件）后」停止消费。
  生成器对象挂起在下一个阶段之前，状态已落在会话持有的 ctx 中，可安全恢复。
- 恢复：另起 worker **继续消费同一个生成器对象**，Python 生成器自动从挂起处续跑。

暂停只在阶段边界生效，无法中断正在执行中的单个阶段；记忆为进程内存储，
进程重启后丢失。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from agent.config import get_settings
from agent.utils.io_log import print_io
from agent.customer_agent import AgentContext, CustomerAgent
from agent.customer_agent import STAGE_LABELS as CUSTOMER_STAGE_LABELS

logger = logging.getLogger(__name__)

# 会话运行状态机
RunStatus = Literal["running", "paused", "awaiting_review", "completed", "error"]
_ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    "running": {"paused", "awaiting_review", "completed", "error"},
    "paused": {"running", "error"},
    "awaiting_review": {"running", "error"},
    "completed": set(),
    "error": set(),
}

# 阶段 -> 面向前端的中文进度标签（复用协调器定义）
STAGE_LABELS: dict[str, str] = CUSTOMER_STAGE_LABELS


class RunWorker:
    """后台任务句柄；兼容旧测试/调用方使用 ``join`` 等待完成。"""

    def __init__(self, future: Future) -> None:
        self._future = future

    def join(self, timeout: float | None = None) -> None:
        self._future.result(timeout=timeout)


@dataclass
class RunSession:
    """单个会话的运行态。"""

    thread_id: str
    session_id: str
    status: RunStatus = "running"
    pause_event: threading.Event = field(default_factory=threading.Event)
    worker: RunWorker | None = None
    ctx: AgentContext | None = None
    events: Iterator[dict[str, Any]] | None = None  # 持有的运行生成器，供恢复时续跑
    final_answer: str = ""
    error: str = ""
    # HITL：待用户审核确认的高风险写操作（交前端展示并允许修改），由 confirm 消费。
    pending_review: dict | None = None
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None
    review_started_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class RunManager:
    """管理所有会话的后台执行、暂停与恢复。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._sessions: dict[str, RunSession] = {}
        self._registry_lock = threading.Lock()
        self._customer_agent = CustomerAgent()
        self._max_workers = max(1, settings.agent_max_workers)
        self._queue_size = max(0, settings.agent_queue_size)
        self._session_ttl = max(60, settings.run_session_ttl_seconds)
        self._review_ttl = max(60, settings.run_review_ttl_seconds)
        self._cleanup_interval = max(10, settings.run_cleanup_interval_seconds)
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="agent-run",
        )
        self._execution_slots = threading.BoundedSemaphore(
            self._max_workers + self._queue_size
        )
        self._stop_cleaner = threading.Event()
        self._cleaner = threading.Thread(
            target=self._cleanup_loop,
            name="agent-run-cleaner",
            daemon=True,
        )
        self._cleaner.start()

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex

    def _resolve_session_id(self, session_id: str | None, new_session: bool = False) -> str:
        """解析记忆会话 id：显式新会话时强制隔离，否则复用调用方传入的 id。"""
        if new_session:
            return self._new_id()
        cleaned = session_id.strip() if session_id else ""
        if not cleaned:
            return self._new_id()
        with self._registry_lock:
            existing_thread = self._sessions.get(cleaned)
        if existing_thread is not None:
            return existing_thread.session_id
        return cleaned

    # —— 对外接口 ——

    def start(
        self,
        message: str,
        session_id: str | None = None,
        new_session: bool = False,
        customer_no: str | None = None,
        customer_id: int | None = None,
    ) -> RunSession:
        """新建会话并在后台开始执行。立即返回，不阻塞。"""
        thread_id = self._new_id()
        memory_session_id = self._resolve_session_id(session_id, new_session)
        ctx = AgentContext(
            user_input=message,
            session_id=memory_session_id,
            customer_no=customer_no,
            customer_id=customer_id,
        )
        session = RunSession(
            thread_id=thread_id,
            session_id=memory_session_id,
            ctx=ctx,
            events=self._customer_agent.iter_run(ctx),
        )
        with self._registry_lock:
            self._sessions[thread_id] = session
        self._spawn(session)
        return session

    def pause(self, thread_id: str) -> RunSession:
        """请求暂停：置标志，worker 在当前阶段结束后停止。"""
        session = self._require(thread_id)
        with session.lock:
            if session.status != "running":
                raise ValueError(f"会话 {thread_id} 当前状态为 {session.status}，无法暂停")
            session.pause_event.set()
        return session

    def resume(self, thread_id: str) -> RunSession:
        """从挂起处恢复执行（继续消费同一生成器）。"""
        session = self._require(thread_id)
        with session.lock:
            if session.status != "paused":
                raise ValueError(f"会话 {thread_id} 当前状态为 {session.status}，无法恢复")
            session.pause_event.clear()
            self._transition(session, "running")
        self._spawn(session)
        return session

    def confirm(
        self,
        thread_id: str,
        approved: bool,
        args: dict[str, Any] | None = None,
        message: str = "",
        regenerate: bool = False,
    ) -> RunSession:
        """用户审核确认/修改后恢复：把审批决定注入挂起的生成器，继续执行落库与后续阶段。"""
        session = self._require(thread_id)
        with session.lock:
            self._expire_review_if_needed(session)
            if session.status != "awaiting_review":
                raise ValueError(f"会话 {thread_id} 当前状态为 {session.status}，无法确认")
            pending_review = session.pending_review
            if approved:
                self._validate_approval_args(pending_review, args)
            self._transition(session, "running")
            session.pending_review = None
        decision = {
            "approved": approved,
            "args": args,
            "message": message,
            "regenerate": regenerate,
        }
        self._spawn(session, send_value=decision)
        return session

    def stream(
        self,
        message: str,
        session_id: str | None = None,
        new_session: bool = False,
        customer_no: str | None = None,
        customer_id: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """同步流式执行：在调用线程内逐阶段产出进度事件（阶段级粒度）。

        与 start/pause/resume 的后台模式相互独立：本方法直接驱动运行生成器，
        每个阶段完成即产出一条事件，适配 SSE「边生成边推送」。事件结构：
        - {"type": "start", "thread_id": ..., "session_id": ...}
        - {"type": "stage", "stage": 名称, "label": 中文标签, "update": 该阶段的状态增量}
        - {"type": "done", "thread_id": ..., "session_id": ..., "status": "completed", "final_answer": ...}
        - {"type": "error", "thread_id": ..., "session_id": ..., "status": "error", "message": ...}
        """
        thread_id = self._new_id()
        memory_session_id = self._resolve_session_id(session_id, new_session)
        ctx = AgentContext(
            user_input=message,
            session_id=memory_session_id,
            customer_no=customer_no,
            customer_id=customer_id,
        )
        events = self._customer_agent.iter_run(ctx)
        session = RunSession(
            thread_id=thread_id,
            session_id=memory_session_id,
            ctx=ctx,
            events=events,
        )
        with self._registry_lock:
            self._sessions[thread_id] = session

        yield {"type": "start", "thread_id": thread_id, "session_id": memory_session_id}
        if not self._execution_slots.acquire(blocking=False):
            message = "系统繁忙，当前 Agent 执行队列已满，请稍后重试。"
            with session.lock:
                session.error = message
                self._transition(session, "error")
            yield {
                "type": "error",
                "thread_id": thread_id,
                "session_id": memory_session_id,
                "status": "error",
                "message": message,
            }
            return
        try:
            stage_started = time.monotonic()
            for event in events:
                self._log_stage_elapsed(session, event, stage_started, mode="stream")
                stage_started = time.monotonic()
                yield event
                if event.get("stage") == "awaiting_review":
                    with session.lock:
                        self._transition(session, "awaiting_review")
                        session.pending_review = event.get("update", {}).get("pending_action")
                    print_io(
                        "RunManager.stream awaiting_review",
                        {
                            "message": message,
                            "session_id": session_id,
                            "memory_session_id": memory_session_id,
                            "new_session": new_session,
                            "customer_no": customer_no,
                            "customer_id": customer_id,
                        },
                        {
                            "thread_id": thread_id,
                            "session_id": memory_session_id,
                            "pending_review": session.pending_review,
                        },
                    )
                    return

            with session.lock:
                session.final_answer = ctx.final_answer
                self._transition(session, "completed")
            yield {
                "type": "done",
                "thread_id": thread_id,
                "session_id": memory_session_id,
                "status": "completed",
                "final_answer": ctx.final_answer,
            }
            print_io(
                "RunManager.stream completed",
                {
                    "message": message,
                    "session_id": session_id,
                    "memory_session_id": memory_session_id,
                    "new_session": new_session,
                    "customer_no": customer_no,
                    "customer_id": customer_id,
                },
                {
                    "thread_id": thread_id,
                    "session_id": memory_session_id,
                    "final_answer": ctx.final_answer,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 流式执行异常需落会话状态并告知前端
            logger.exception("会话 %s 流式执行失败", thread_id)
            with session.lock:
                session.error = str(exc)
                self._transition(session, "error")
            # 已进入流式响应，无法再返回错误码，改以事件告知前端
            yield {
                "type": "error",
                "thread_id": thread_id,
                "session_id": memory_session_id,
                "status": "error",
                "message": str(exc),
            }
            print_io(
                "RunManager.stream error",
                {
                    "message": message,
                    "session_id": session_id,
                    "memory_session_id": memory_session_id,
                    "new_session": new_session,
                    "customer_no": customer_no,
                    "customer_id": customer_id,
                },
                {"thread_id": thread_id, "session_id": memory_session_id, "error": str(exc)},
            )
        finally:
            self._execution_slots.release()

    def get(self, thread_id: str) -> RunSession:
        session = self._require(thread_id)
        with session.lock:
            self._expire_review_if_needed(session)
        return session

    # —— 内部实现 ——

    def _require(self, thread_id: str) -> RunSession:
        with self._registry_lock:
            session = self._sessions.get(thread_id)
        if session is None:
            raise KeyError(thread_id)
        return session

    def _spawn(self, session: RunSession, send_value: Any | None = None) -> None:
        if not self._execution_slots.acquire(blocking=False):
            with session.lock:
                session.error = "系统繁忙，当前 Agent 执行队列已满，请稍后重试。"
                self._transition(session, "error")
            logger.warning(
                "Agent 执行队列已满，拒绝调度会话 %s max_workers=%d queue_size=%d",
                session.thread_id,
                self._max_workers,
                self._queue_size,
            )
            return
        future = self._executor.submit(self._consume_with_slot, session, send_value)
        session.worker = RunWorker(future)

    def _consume_with_slot(self, session: RunSession, send_value: Any | None = None) -> None:
        try:
            self._consume(session, send_value)
        finally:
            self._execution_slots.release()

    @staticmethod
    def _transition(session: RunSession, status: RunStatus) -> None:
        """显式状态机迁移，防止后台线程把会话推进到非法状态。"""
        if status == session.status:
            session.updated_at = time.monotonic()
            return
        allowed = _ALLOWED_TRANSITIONS[session.status]
        if status not in allowed:
            raise ValueError(f"会话 {session.thread_id} 状态不能从 {session.status} 切换到 {status}")
        session.status = status
        session.updated_at = time.monotonic()
        if status == "awaiting_review":
            session.review_started_at = session.updated_at
        if status in {"completed", "error"}:
            session.completed_at = session.updated_at

    @staticmethod
    def _validate_approval_args(pending_review: dict | None, args: dict[str, Any] | None) -> None:
        """确认执行前校验前端已补齐必填字段，避免空原因等参数真正落库。"""
        if not pending_review:
            return
        if pending_review.get("tool") not in {"createOrder", "createAfterSale", "createHumanService"}:
            return
        merged_args = {**pending_review.get("args", {}), **(args or {})}
        missing = []
        for field_name in pending_review.get("required_fields", ["reason"]):
            value = merged_args.get(field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(field_name)
        if missing:
            raise ValueError(f"确认申请前请补齐字段：{', '.join(missing)}")

    def _expire_review_if_needed(self, session: RunSession) -> None:
        """待确认会话超过 TTL 后失效，避免高风险操作长时间悬挂。"""
        if session.status != "awaiting_review":
            return
        started_at = session.review_started_at or session.updated_at
        if time.monotonic() - started_at <= self._review_ttl:
            return
        session.pending_review = None
        session.error = "确认操作已超时，请重新发起本次业务请求。"
        self._transition(session, "error")

    def _cleanup_loop(self) -> None:
        """定期清理过期会话运行态，防止进程内会话字典无限增长。"""
        while not self._stop_cleaner.wait(self._cleanup_interval):
            try:
                self.cleanup_expired_sessions()
            except Exception:  # noqa: BLE001 - 清理线程不能影响主服务
                logger.exception("清理过期 Agent 会话失败")

    def cleanup_expired_sessions(self) -> int:
        """清理过期会话；返回移除的会话数量，便于测试和运维观测。"""
        now = time.monotonic()
        expired: list[str] = []
        with self._registry_lock:
            for thread_id, session in list(self._sessions.items()):
                with session.lock:
                    self._expire_review_if_needed(session)
                    if session.status in {"completed", "error"}:
                        finished_at = session.completed_at or session.updated_at
                        if now - finished_at >= self._session_ttl:
                            expired.append(thread_id)
            for thread_id in expired:
                self._sessions.pop(thread_id, None)
        if expired:
            logger.info("已清理过期 Agent 会话 %d 个", len(expired))
        return len(expired)

    @staticmethod
    def _log_stage_elapsed(
        session: RunSession,
        event: dict[str, Any],
        started_at: float,
        *,
        mode: str,
    ) -> None:
        stage = str(event.get("stage") or event.get("type") or "unknown")
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.info(
            "Agent 阶段完成 thread_id=%s session_id=%s mode=%s stage=%s elapsed_ms=%d",
            session.thread_id,
            session.session_id,
            mode,
            stage,
            elapsed_ms,
        )

    def _consume(self, session: RunSession, send_value: Any | None = None) -> None:
        """在后台线程中逐阶段消费运行生成器。

        - 首次启动 / 阶段恢复：``send_value`` 为 None。
        - 用户审核确认恢复：``send_value`` 为审批决定，注入到 awaiting_review 的挂起点。

        遇到 awaiting_review 事件挂起等待确认；收到暂停标志时在阶段边界停止。
        """
        gen = session.events
        if gen is None:
            return
        try:
            stage_started = time.monotonic()
            event = gen.send(send_value)  # 首步 send(None) 启动；确认恢复时 send(decision)
            while True:
                self._log_stage_elapsed(session, event, stage_started, mode="background")
                stage_started = time.monotonic()
                # 命中高风险写操作：落待确认信息并挂起，生成器停在 awaiting_review 的 yield 处
                if event.get("stage") == "awaiting_review":
                    with session.lock:
                        self._transition(session, "awaiting_review")
                        session.pending_review = event.get("update", {}).get("pending_action")
                    logger.info("会话 %s 进入待用户确认", session.thread_id)
                    return
                # 当前阶段已完成并落入 ctx，此处暂停可安全恢复
                if session.pause_event.is_set():
                    with session.lock:
                        self._transition(session, "paused")
                    logger.info("会话 %s 已在阶段边界暂停", session.thread_id)
                    return
                event = gen.send(None)
        except StopIteration:
            # 生成器自然耗尽：本轮运行完成
            with session.lock:
                session.final_answer = session.ctx.final_answer if session.ctx else ""
                self._transition(session, "completed")
            print_io(
                "RunManager.background completed",
                {
                    "thread_id": session.thread_id,
                    "message": session.ctx.user_input if session.ctx else "",
                },
                {
                    "status": session.status,
                    "final_answer": session.final_answer,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 后台执行异常需记录并落到会话状态
            logger.exception("会话 %s 执行失败", session.thread_id)
            with session.lock:
                session.error = str(exc)
                self._transition(session, "error")
            print_io(
                "RunManager.background error",
                {
                    "thread_id": session.thread_id,
                    "message": session.ctx.user_input if session.ctx else "",
                },
                {"status": session.status, "error": session.error},
            )


@lru_cache(maxsize=1)
def get_run_manager() -> RunManager:
    """运行管理器单例。"""
    return RunManager()
