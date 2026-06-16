"""API package.

模块划分：
- ``app``     : FastAPI 应用装配与 CORS 等中间件配置
- ``routes``  : 业务端点（APIRouter）
- ``schemas`` : 请求 / 响应数据模型
- ``server``  : uvicorn 启动入口
- ``runner``  : 会话后台执行 / 暂停 / 恢复管理器
"""

__all__ = ["app"]


def __getattr__(name: str):
    """按需加载 FastAPI app，避免导入 runner 时提前初始化完整服务依赖。"""
    if name == "app":
        from agent.api.app import app

        return app
    raise AttributeError(name)
