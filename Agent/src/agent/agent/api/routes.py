"""API 路由：支持「发起 / 暂停 / 恢复」的会话式 Agent 接口。

三个核心接口围绕「阶段边界暂停 / 恢复」能力构建：
- POST /run      发送问题，新建会话线程并后台开始生成
- POST /pause    暂停指定会话的生成（在阶段边界生效）
- POST /resume   从挂起的阶段边界恢复生成

流式接口：
- POST /stream   发送问题，以 SSE 逐阶段流式推送执行进度与最终回答

辅助接口：
- GET /health            健康检查
- GET /sessions/{id}     查询会话当前状态与结果

本模块只定义路由（APIRouter），应用装配与中间件配置见 ``app.py``。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from agent.api.runner import RunSession, get_run_manager
from agent.api.schemas import (
    ConfirmRequest,
    MemoryAppendRequest,
    MemoryPurgeResponse,
    RunRequest,
    SessionResponse,
    ThreadRequest,
)
from agent.customer_agent import AgentContext
from agent.memory import mysql_store
from agent.memory import store as memory_store
from agent.memory.runtime import get_runtime
from agent.utils.io_log import print_io

router = APIRouter()


def _parse_customer_id(raw_customer_id: str | None, customer_no: str | None) -> int | None:
    """仅将纯数字客户编号转为工具可用的 userId，避免误用随机会话号或业务编号。"""
    for raw_value in (raw_customer_id, customer_no):
        if raw_value is None:
            continue
        value = raw_value.strip()
        if value.isdigit():
            return int(value)
    return None


def _to_response(session: RunSession) -> SessionResponse:
    return SessionResponse(
        thread_id=session.thread_id,
        session_id=session.session_id,
        status=session.status,
        final_answer=session.final_answer,
        error=session.error,
        pending_action=session.pending_review,
    )


def _confirm_args(pending_review: dict | None, args: dict | None) -> dict:
    if not pending_review:
        return dict(args or {})
    return {**dict(pending_review.get("args") or {}), **dict(args or {})}


def _validate_confirm_order_owner(
    pending_review: dict | None,
    args: dict | None,
    customer_id: int | None,
) -> None:
    """确认高风险写操作前校验订单归属，避免前端提交他人订单号。"""
    if not pending_review:
        return
    if pending_review.get("tool") not in {"createAfterSale", "createHumanService"}:
        return
    merged_args = _confirm_args(pending_review, args)
    order_no = str(merged_args.get("orderNo") or "").strip()
    if not order_no:
        return
    if customer_id is None:
        raise HTTPException(status_code=409, detail="当前未获取到认证客户ID，无法校验订单归属。")
    owner = get_runtime().run(mysql_store.order_owner(order_no))
    if owner is None:
        raise HTTPException(status_code=409, detail=f"未找到订单：{order_no}，请核对订单号后再提交。")
    if owner != customer_id:
        raise HTTPException(status_code=409, detail=f"订单 {order_no} 不属于当前登录用户，不能提交该操作。")


# —— 接口 ——

@router.get("/health")
def health() -> dict[str, str]:
    response = {"status": "ok"}
    print_io("GET /health", {}, response)
    return response


@router.post("/run", response_model=SessionResponse)
def run(
    payload: RunRequest,
    x_customer_no: str | None = Header(default=None, alias="X-Customer-No"),
    x_customer_id: str | None = Header(default=None, alias="X-Customer-Id"),
) -> SessionResponse:
    """发送问题：新建会话线程，后台开始生成，立即返回 thread_id。"""
    customer_id = _parse_customer_id(x_customer_id, x_customer_no)
    session = get_run_manager().start(
        payload.message,
        payload.session_id,
        new_session=payload.new_session,
        customer_no=x_customer_no,
        customer_id=customer_id,
    )
    response = _to_response(session)
    print_io(
        "POST /run",
        {**payload.model_dump(), "customer_no": x_customer_no, "customer_id": customer_id},
        response,
    )
    return response


@router.post("/stream")
def stream(
    payload: RunRequest,
    x_customer_no: str | None = Header(default=None, alias="X-Customer-No"),
    x_customer_id: str | None = Header(default=None, alias="X-Customer-Id"),
) -> StreamingResponse:
    """发送问题并以 SSE 流式返回：逐阶段推送执行进度，最后推送完整回答。

    响应为 ``text/event-stream``，每条事件形如 ``data: {json}\\n\\n``，
    事件类型见 ``RunManager.stream`` 的文档（start / stage / done / error）。
    生成在请求线程内同步进行（StreamingResponse 以同步生成器驱动，
    由 Starlette 放入线程池迭代），故阶段内部的 ``asyncio.run`` 不受影响。
    """
    manager = get_run_manager()
    customer_id = _parse_customer_id(x_customer_id, x_customer_no)

    def event_source() -> Iterator[str]:
        for event in manager.stream(
            payload.message,
            payload.session_id,
            new_session=payload.new_session,
            customer_no=x_customer_no,
            customer_id=customer_id,
        ):
            print_io("POST /stream event", payload, event)
            # ensure_ascii=False 保留中文；SSE 以空行分隔事件
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    response = StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关闭 Nginx 等反向代理的缓冲，确保逐事件实时下发
            "X-Accel-Buffering": "no",
        },
    )
    print_io(
        "POST /stream",
        {**payload.model_dump(), "customer_no": x_customer_no, "customer_id": customer_id},
        {"media_type": "text/event-stream"},
    )
    return response


@router.post("/pause", response_model=SessionResponse)
def pause(payload: ThreadRequest) -> SessionResponse:
    """暂停生成：在当前阶段完成后停止（已完成阶段已落 checkpoint）。"""
    manager = get_run_manager()
    try:
        session = manager.pause(payload.thread_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"会话不存在：{payload.thread_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    response = _to_response(session)
    print_io("POST /pause", payload, response)
    return response


@router.post("/resume", response_model=SessionResponse)
def resume(payload: ThreadRequest) -> SessionResponse:
    """从 checkpoint 恢复生成。"""
    manager = get_run_manager()
    try:
        session = manager.resume(payload.thread_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"会话不存在：{payload.thread_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    response = _to_response(session)
    print_io("POST /resume", payload, response)
    return response


@router.post("/confirm", response_model=SessionResponse)
def confirm(
    payload: ConfirmRequest,
    x_customer_no: str | None = Header(default=None, alias="X-Customer-No"),
    x_customer_id: str | None = Header(default=None, alias="X-Customer-Id"),
) -> SessionResponse:
    """用户审核确认/修改高风险写操作后恢复执行。

    仅 ``awaiting_review`` 状态的会话可确认；``approved=true`` 时可在 ``args`` 传入
    修改后的参数（如 type/reason），随后真正落库并继续后续阶段。
    """
    manager = get_run_manager()
    try:
        session = manager.get(payload.thread_id)
        if payload.approved:
            _validate_confirm_order_owner(
                session.pending_review,
                payload.args,
                _parse_customer_id(x_customer_id, x_customer_no),
            )
        session = manager.confirm(
            payload.thread_id,
            payload.approved,
            args=payload.args,
            message=payload.message or "",
            regenerate=payload.regenerate,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"会话不存在：{payload.thread_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    response = _to_response(session)
    print_io("POST /confirm", payload, response)
    return response


@router.post("/memory/append", response_model=SessionResponse)
def append_memory(
    payload: MemoryAppendRequest,
    x_customer_no: str | None = Header(default=None, alias="X-Customer-No"),
    x_customer_id: str | None = Header(default=None, alias="X-Customer-Id"),
) -> SessionResponse:
    """记录前端直接完成的业务事件，不触发 Agent 编排或工具调用。

    用于「商品卡直接下单」这类前端自助链路：业务已由 REST 完成，这里只把结果写入
    当前 Agent 记忆会话，保证下一轮用户输入能读到刚发生的订单上下文。
    """
    session_id = (payload.session_id or "").strip() or uuid.uuid4().hex
    customer_id = _parse_customer_id(x_customer_id, x_customer_no)
    ctx = AgentContext(
        user_input=payload.user_message,
        final_answer=payload.assistant_message,
        session_id=session_id,
        customer_no=x_customer_no,
        customer_id=customer_id,
    )
    try:
        memory_store.save_memory(ctx)
    except Exception as exc:  # noqa: BLE001 - 记忆写入失败要显式反馈给前端
        raise HTTPException(status_code=500, detail=f"会话记忆写入失败：{exc}")

    response = SessionResponse(
        thread_id="",
        session_id=session_id,
        status="completed",
        final_answer=payload.assistant_message,
        error="",
    )
    print_io(
        "POST /memory/append",
        {**payload.model_dump(), "customer_no": x_customer_no, "customer_id": customer_id},
        response,
    )
    return response


@router.delete("/memory/{customer_id}", response_model=MemoryPurgeResponse)
def purge_memory(
    customer_id: int,
    customer_no: str | None = Query(default=None, description="可选；按客户编号一并清理"),
) -> MemoryPurgeResponse:
    """按用户 id 清理其全部长期记忆：用户画像、会话状态、消息流水与语义记忆。

    清理覆盖 L1 本地缓存、L2 Redis、L3 MySQL、L4 Qdrant；该操作不可恢复。
    """
    try:
        result = memory_store.purge_customer_memory(
            customer_id=customer_id,
            customer_no=customer_no,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    response = MemoryPurgeResponse(
        customer_id=customer_id,
        customer_no=customer_no,
        deleted_sessions=result.get("sessions", 0),
        deleted_messages=result.get("messages", 0),
    )
    print_io(
        "DELETE /memory",
        {"customer_id": customer_id, "customer_no": customer_no},
        response.model_dump(),
    )
    return response


@router.get("/sessions/{thread_id}", response_model=SessionResponse)
def get_session(thread_id: str) -> SessionResponse:
    """查询会话状态与最终结果。"""
    try:
        session = get_run_manager().get(thread_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"会话不存在：{thread_id}")
    response = _to_response(session)
    return response
