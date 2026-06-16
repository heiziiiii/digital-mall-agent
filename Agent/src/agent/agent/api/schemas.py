"""API 请求 / 响应数据模型（Pydantic）。

集中维护对外契约，路由层只负责编排，模型定义不散落在各处。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """发起新会话的请求体。"""

    message: str = Field(..., min_length=1, description="用户问题")
    session_id: str | None = Field(None, description="可选；用于延续同一记忆会话")
    new_session: bool = Field(False, description="为 true 时忽略传入 session_id，强制开启全新记忆会话")


class ThreadRequest(BaseModel):
    """针对已有会话（暂停 / 恢复）的请求体。"""

    thread_id: str = Field(..., min_length=1, description="会话线程 id")


class ConfirmRequest(BaseModel):
    """用户审核确认/修改高风险写操作（如创建售后单）的请求体。"""

    thread_id: str = Field(..., min_length=1, description="会话线程 id")
    approved: bool = Field(..., description="true 确认执行，false 取消")
    regenerate: bool = Field(
        False,
        description=(
            "approved=false 时是否带意见重新生成待确认方案；false 表示取消，true 表示后端按 message/args 继续生成"
        ),
    )
    args: dict | None = Field(
        None, description="确认时可传入修改后的工具参数（如 type/reason）；为空则沿用模型原参数"
    )
    message: str | None = Field(None, description="取消说明或重新生成意见，可选")


class SessionResponse(BaseModel):
    """统一会话响应结构。"""

    thread_id: str
    session_id: str = ""
    status: str                       # running / paused / awaiting_review / completed / error
    final_answer: str = ""
    error: str = ""
    # 当 status=awaiting_review 时返回：待用户审核确认/修改的写操作 JSON
    pending_action: dict | None = None
