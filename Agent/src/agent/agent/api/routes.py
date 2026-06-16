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
from collections.abc import Iterator

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from agent.api.runner import RunSession, get_run_manager
from agent.api.schemas import ConfirmRequest, RunRequest, SessionResponse, ThreadRequest
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
def confirm(payload: ConfirmRequest) -> SessionResponse:
    """用户审核确认/修改高风险写操作后恢复执行。

    仅 ``awaiting_review`` 状态的会话可确认；``approved=true`` 时可在 ``args`` 传入
    修改后的参数（如 type/reason），随后真正落库并继续后续阶段。
    """
    manager = get_run_manager()
    try:
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


@router.get("/sessions/{thread_id}", response_model=SessionResponse)
def get_session(thread_id: str) -> SessionResponse:
    """查询会话状态与最终结果。"""
    try:
        session = get_run_manager().get(thread_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"会话不存在：{thread_id}")
    response = _to_response(session)
    return response
