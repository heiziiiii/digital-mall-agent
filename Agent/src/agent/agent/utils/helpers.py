"""General-purpose helpers."""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO, *, verbose: bool = False) -> None:
    """配置全局日志。

    verbose=True 时：整体降到 DEBUG，并打开 openai / httpx / httpcore 的请求级日志
    （可看到每次重试、底层 HTTP 往返），用于排查超时、连接等问题；
    verbose=False 时：保持 INFO，并压低 httpx 的逐请求噪声，保留我们自己的阶段日志。
    """
    if verbose:
        level = logging.DEBUG
    # 含 logger 名与行号，便于定位是哪个阶段/模块打印的
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s",
        force=True,  # 覆盖已有 handler，确保格式生效
    )

    if verbose:
        for name in ("openai", "httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.DEBUG)
    else:
        # 非调试模式下，第三方库每条 HTTP 请求的 INFO 噪声较大，压到 WARNING
        logging.getLogger("httpx").setLevel(logging.WARNING)

