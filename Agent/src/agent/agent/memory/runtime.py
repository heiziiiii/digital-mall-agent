"""记忆运行时：自持一个长生命周期的后台事件循环线程，统一承载异步后端 I/O。

为什么需要它：Agent 运行链路是同步生成器，每步用 ``asyncio.run`` 起临时事件循环，且跑在
多个后台守护线程里（见 ``api/runner.py``）。异步连接池（SQLAlchemy async /
``redis.asyncio`` / qdrant async）会绑定到创建它的事件循环，跨多次 ``asyncio.run``
复用会触发 "attached to a different loop"。

解法：把所有 **数据库 / 向量库 / embedding** 类异步客户端固定在本运行时的单一
loop 上创建与使用；对外只暴露同步阻塞接口 ``run(coro)``，内部用
``run_coroutine_threadsafe(coro, loop).result()`` 把协程投递到该 loop 执行。

注意：LLM（对话模型）调用不走这里——它沿用Agent 运行链路其它阶段的 ``asyncio.run`` 临时
loop，避免把对话模型的 httpx 客户端绑定到本 loop 而与本轮运行冲突。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from functools import lru_cache
from typing import Awaitable, TypeVar

from agent.memory import mysql_store, qdrant_store, redis_store

logger = logging.getLogger(__name__)

T = TypeVar("T")


class MemoryRuntime:
    """承载记忆层异步 I/O 的后台事件循环线程（单例，经 ``get_runtime`` 获取）。"""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """惰性启动后台事件循环线程并返回其 loop。"""
        with self._lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_loop, args=(loop,), name="memory-io-loop", daemon=True
            )
            thread.start()
            self._loop = loop
            self._thread = thread
            return loop

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def run(self, coro: Awaitable[T]) -> T:
        """把协程投递到后台 loop 执行并同步等待结果（供 worker 线程调用）。"""
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    def startup(self) -> None:
        """建连 / 建表 / 建集合 / ping：强校验，任一后端不可用则抛错（启动失败）。"""
        if self._started:
            return
        self.run(self._startup())
        self._started = True
        logger.info("记忆运行时启动完成（Redis / Qdrant 已就绪）。")

    @staticmethod
    async def _startup() -> None:
        await redis_store.startup()
        await mysql_store.startup()
        await qdrant_store.startup()

    def shutdown(self) -> None:
        """释放连接池并停止后台 loop；可安全重复调用。"""
        if not self._started:
            return
        try:
            self.run(self._shutdown())
        except Exception as exc:  # noqa: BLE001 - 关闭阶段异常仅告警，不影响进程退出
            logger.warning("记忆运行时关闭异常：%s", exc)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        with self._lock:
            self._loop = None
            self._thread = None
            self._started = False

    @staticmethod
    async def _shutdown() -> None:
        await redis_store.shutdown()
        await mysql_store.shutdown()
        await qdrant_store.shutdown()


@lru_cache(maxsize=1)
def get_runtime() -> MemoryRuntime:
    """记忆运行时单例。"""
    return MemoryRuntime()

