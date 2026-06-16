"""服务启动入口：用 uvicorn 拉起 FastAPI 应用。

以字符串 "agent.api.app:app" 方式传入，方便开启 reload 热重载。
"""

from __future__ import annotations

import uvicorn


def run(host: str = "127.0.0.1", port: int = 8001, reload: bool = False) -> None:
    """启动 API 服务。"""
    uvicorn.run("agent.api.app:app", host=host, port=port, reload=reload, access_log=False)


if __name__ == "__main__":
    run()
