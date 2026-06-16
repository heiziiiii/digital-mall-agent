"""Project entry point for CLI and optional API startup."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any, Iterable

from agent.api.runner import get_run_manager
from agent.api.server import run as run_server
from agent.customer_agent import CustomerAgent
from agent.llm.model import initialize_model
from agent.memory.runtime import get_runtime
from agent.utils.helpers import configure_logging


_customer_agent = CustomerAgent()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PydanticAI 智能客服 Agent")
    parser.add_argument("message", nargs="?", help="First user message for the CLI chat mode")
    parser.add_argument("--serve", action="store_true", help="Run the FastAPI server")
    parser.add_argument(
        "--once",
        action="store_true",
        help="单次问答模式：只处理一条 message 后退出",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="CLI 流式调试（单次）：逐阶段实时打印事件，等价于前端 /stream SSE 的内容",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="进入命令行对话窗口：多轮交互，每轮逐阶段 SSE 流式输出（输入 exit/quit 退出）",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="配合 --stream/--chat：原样打印每条事件的 JSON（与 SSE data: 载荷一致），便于排查前端解析问题",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="调试日志：降到 DEBUG，打开 openai/httpx 请求级日志（重试、HTTP 往返、异常堆栈）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", default=8001, type=int, help="Server port")
    parser.add_argument(
        "--customer-id",
        "--user-id",
        dest="customer_id",
        type=int,
        default=1,
        help="仿真真实登录用户：透传给订单/售后专家的客户 ID",
    )
    parser.add_argument(
        "--customer-no",
        default=None,
        help="仿真真实登录用户：透传给订单/售后专家的客户编号",
    )
    return parser


def run_cli(
    message: str,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> dict[str, Any]:
    result = _customer_agent.run(message, customer_id=customer_id, customer_no=customer_no)
    print(result.final_answer)
    return result


def _render_events(events: Iterable[dict[str, Any]], raw: bool = False) -> None:
    """逐条渲染 RunManager.stream 产出的 SSE 事件到终端（实时 flush）。

    raw=True 时原样打印事件 JSON（与前端 SSE ``data:`` 载荷一致），便于对照前端解析；
    raw=False 时渲染为人类可读的逐阶段进度。
    """
    for event in events:
        if raw:
            print(json.dumps(event, ensure_ascii=False), flush=True)
            continue

        etype = event.get("type")
        if etype == "start":
            print(f"▶ 会话开始 thread_id={event['thread_id']}", flush=True)
        elif etype == "stage":
            # 阶段完成即刷新一行，直观看到链路推进节奏
            print(f"  ├ [{event['label']}] {event['stage']} 完成", flush=True)
        elif etype == "done":
            print(f"  └ ✔ 完成\n\n🤖 {event['final_answer']}", flush=True)
        elif etype == "error":
            print(f"  └ ✖ 出错：{event['message']}", file=sys.stderr, flush=True)


def run_cli_stream(
    message: str,
    raw: bool = False,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> None:
    """流式调试入口（单次）：直接驱动后端 RunManager.stream，逐阶段实时打印。

    与前端 /stream 走的是同一条生成路径，因此可用来判断「流式产出」本身是否正常：
    若此处能逐阶段实时刷新，问题就在前端 SSE 解析/渲染；若此处也卡到最后才一次性
    输出，则问题在后端（阶段级粒度，或某阶段内部阻塞）。
    """
    _render_events(
        get_run_manager().stream(message, customer_id=customer_id, customer_no=customer_no),
        raw=raw,
    )


def run_cli_chat(
    initial_message: str | None = None,
    raw: bool = False,
    customer_id: int | None = None,
    customer_no: str | None = None,
) -> None:
    """命令行对话窗口：多轮交互，每轮逐阶段 SSE 流式输出。

    整个会话固定同一个 session_id，使记忆阶段（历史/滚动摘要/用户画像）跨轮累积，
    行为与前端持有同一会话连续提问一致。可传入 initial_message 作为第一轮输入；
    输入 exit/quit/q 或 Ctrl-C/Ctrl-D 退出。
    """
    manager = get_run_manager()
    session_id = uuid.uuid4().hex
    identity = f"，customer_id={customer_id}" if customer_id is not None else ""
    print(f"💬 进入对话窗口（session_id={session_id}{identity}）。输入 exit / quit 退出。\n", flush=True)
    pending_message = initial_message.strip() if initial_message else ""

    while True:
        if pending_message:
            message = pending_message
            pending_message = ""
            print(f"你 > {message}", flush=True)
        else:
            try:
                message = input("你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n已退出对话。", flush=True)
                return

        if not message:
            continue
        if message.lower() in {"exit", "quit", "q"}:
            print("已退出对话。", flush=True)
            return

        # 同一 session_id 复用记忆；逐阶段流式渲染本轮回答
        _render_events(
            manager.stream(
                message,
                session_id,
                customer_no=customer_no,
                customer_id=customer_id,
            ),
            raw=raw,
        )
        print(flush=True)  # 轮次间留空行


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(verbose=args.verbose)
    initialize_model()

    if args.serve:
        # 服务模式下记忆运行时由 FastAPI lifespan 管理，这里不重复拉起
        run_server(host=args.host, port=args.port, reload=False)
        return

    # CLI 模式不走 FastAPI lifespan，需显式拉起 / 释放多层记忆运行时
    get_runtime().startup()
    try:
        if args.stream:
            message = args.message or input("请输入一段消息：").strip()
            if not message:
                raise SystemExit("消息不能为空")
            run_cli_stream(
                message,
                raw=args.raw,
                customer_id=args.customer_id,
                customer_no=args.customer_no,
            )
            return

        if args.chat or not args.once:
            run_cli_chat(
                initial_message=args.message,
                raw=args.raw,
                customer_id=args.customer_id,
                customer_no=args.customer_no,
            )
            return

        message = args.message or input("请输入一段消息：").strip()
        if not message:
            raise SystemExit("消息不能为空")

        run_cli(message, customer_id=args.customer_id, customer_no=args.customer_no)
    finally:
        get_runtime().shutdown()


if __name__ == "__main__":
    main()




