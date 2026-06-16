"""FastAPI 应用装配：创建实例、配置跨域（CORS）并挂载路由。

拆分目的：``app`` 负责应用级配置（中间件、文档信息），``routes`` 只管
端点逻辑，二者解耦，便于测试与扩展。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.api.routes import router
from agent.config import get_settings
from agent.llm.model import initialize_model
from agent.memory.runtime import get_runtime


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """服务接收请求前预热模型并拉起多层记忆（强校验各后端连通性），退出时释放连接。"""
    initialize_model()
    get_runtime().startup()
    yield
    get_runtime().shutdown()


def create_app() -> FastAPI:
    """构建并返回配置完毕的 FastAPI 应用。"""
    app = FastAPI(
        title="PydanticAI 智能客服 Agent",
        version="0.3.0",
        lifespan=lifespan,
    )

    settings = get_settings()
    # 配置跨域，保证前端（不同域 / 端口）能够正常访问接口。
    # 当 origins 含 "*" 时，浏览器规范不允许同时携带 Cookie，故关闭 credentials；
    # 若需携带凭证，请在配置中改为显式的前端来源列表。
    allow_all = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


# 模块级单例，供 uvicorn 以 "src.api.app:app" 方式加载
app = create_app()
