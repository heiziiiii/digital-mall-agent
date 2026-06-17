#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Agent 自动问答测试记录脚本。

用法：
    python tests/test_agent_qa_record.py

脚本会按当前项目 CLI/前端 SSE 同一条链路调用 RunManager.stream，
逐个执行内置问题，并把测试数据与回答结果写入：
    tests/results/agent_qa_test_YYYYMMDD_HHMMSS.md

注意：
    该脚本没有 pytest 测试函数，普通 pytest 回归不会自动触发真实 LLM/MCP/记忆后端调用。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows PowerShell 默认可能是 GBK。LLM 输出里常见 emoji、项目符号等字符，
# 若 stdout/stderr 仍是 GBK，内部 I/O 日志打印会触发 UnicodeEncodeError。
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QATestCase:
    """一条人工可读、可落报告的 QA 测试数据。"""

    num: str
    category: str
    difficulty: str
    question: str
    expected: str
    session_key: str = "default"
    customer_id: int | None = 1
    customer_no: str | None = "C001"


# 测试问题：从简单问答到复杂链路，覆盖记忆、HITL、MCP 写审批等能力。
TEST_CASES: list[QATestCase] = [
    QATestCase(
        num="QA-001",
        category="基础问答",
        difficulty="简单",
        question="你好，你能帮我做什么？",
        expected="普通客服问候与能力说明；不应调用商品、订单、售后专家工具。",
        session_key="basic",
    ),
    QATestCase(
        num="QA-002",
        category="商品咨询",
        difficulty="简单",
        question="推荐一款拍照好、预算 3000 左右的手机。",
        expected="编排到商品专家；回答应基于商品工具证据，不编造价格、库存或活动。",
        session_key="product",
    ),
    QATestCase(
        num="QA-003",
        category="技术支持",
        difficulty="中等",
        question="手机突然充不进电了，我应该怎么排查？",
        expected="编排到技术专家；给出可操作排查步骤，不直接承诺售后成功。",
        session_key="tech",
    ),
    QATestCase(
        num="QA-004",
        category="订单售后",
        difficulty="中等",
        question="帮我查一下最近的订单物流状态。",
        expected="编排到订单专家；只使用订单工具返回的真实数据回答。",
        session_key="order",
    ),
    QATestCase(
        num="QA-005",
        category="多任务协作",
        difficulty="复杂",
        question="我想买一台拍照好的手机，顺便查一下我上次买的耳机物流。",
        expected="拆成商品与订单任务；无依赖时可并发执行；最终总结合并两个结果。",
        session_key="multi_task",
    ),
    QATestCase(
        num="QA-006",
        category="依赖任务",
        difficulty="复杂",
        question="我刚买的手机开不了机，帮我看看是不是能售后。",
        expected="优先查询订单或购买上下文，再结合技术/售后规则回答。",
        session_key="dependent_task",
    ),
    QATestCase(
        num="MEM-001",
        category="短期记忆",
        difficulty="中等",
        question="请记住，我以后买手机优先考虑安卓、小屏，预算 4000 以内。",
        expected="正常回复已记录偏好；输出端记忆应判断为有价值画像/长期记忆候选。",
        session_key="memory_profile",
    ),
    QATestCase(
        num="MEM-002",
        category="短期记忆",
        difficulty="中等",
        question="按照刚才的偏好，继续推荐一款手机。",
        expected="复用同一 session 的偏好上下文，不重复询问预算和系统偏好。",
        session_key="memory_profile",
    ),
    QATestCase(
        num="MEM-003",
        category="长期记忆",
        difficulty="复杂",
        question="你现在还记得我之前关注什么手机偏好吗？",
        expected="按需读取/召回记忆并克制回答；本轮记忆查询不应反写长期记忆或画像。",
        session_key="memory_profile",
    ),
    QATestCase(
        num="HITL-001",
        category="HITL 审批",
        difficulty="复杂",
        question="帮我申请退货，原因是手机无法开机。",
        expected="触发 createAfterSale 等高风险写操作审批；停在 awaiting_review，不应直接提交。",
        session_key="hitl_after_sale",
    ),
    QATestCase(
        num="HITL-002",
        category="HITL 审批",
        difficulty="复杂",
        question="我要转人工处理刚才那个售后问题。",
        expected="推断人工服务需求；触发 createHumanService 审批并等待用户确认。",
        session_key="hitl_human",
    ),
    QATestCase(
        num="API-001",
        category="流式事件",
        difficulty="中等",
        question="查一下订单，然后推荐一个能搭配它的配件。",
        expected="报告中应记录 start、memory_load、decide、专家阶段、summarize、memory_save/done 等事件。",
        session_key="stream_events",
    ),
]


def _session_id_for(case: QATestCase, session_ids: dict[str, str]) -> str:
    if case.session_key not in session_ids:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        session_ids[case.session_key] = f"qa-{case.session_key}-{timestamp}"
    return session_ids[case.session_key]


def _compact_update(update: Any) -> str:
    """把阶段 update 压成适合报告阅读的短文本。"""
    if update is None:
        return ""
    try:
        text = json.dumps(update, ensure_ascii=False, default=str)
    except TypeError:
        text = str(update)
    if len(text) > 1200:
        return text[:1200] + "\n...（已截断）"
    return text


def _run_one(case: QATestCase, session_id: str) -> dict[str, Any]:
    from agent.api.runner import get_run_manager

    start = time.perf_counter()
    events: list[dict[str, Any]] = []
    final_answer = ""
    pending_action: dict[str, Any] | None = None
    status = "success"
    error = ""

    try:
        for event in get_run_manager().stream(
            case.question,
            session_id=session_id,
            customer_id=case.customer_id,
            customer_no=case.customer_no,
        ):
            events.append(event)
            event_type = event.get("type")
            if event_type == "done":
                final_answer = event.get("final_answer", "")
            elif event_type == "error":
                status = "error"
                error = event.get("message", "")
            elif event.get("stage") == "awaiting_review":
                status = "awaiting_review"
                pending_action = event.get("update", {}).get("pending_action")
                break
    except Exception as exc:  # noqa: BLE001 - 测试报告需要记录所有失败
        status = "error"
        error = str(exc)
        logger.exception("测试用例 %s 执行失败", case.num)

    duration = round(time.perf_counter() - start, 2)
    return {
        "num": case.num,
        "category": case.category,
        "difficulty": case.difficulty,
        "question": case.question,
        "expected": case.expected,
        "session_id": session_id,
        "customer_id": case.customer_id,
        "customer_no": case.customer_no,
        "answer": final_answer,
        "pending_action": pending_action,
        "events": events,
        "status": status,
        "error": error,
        "duration": duration,
    }


def _run_one_in_child(case: QATestCase, session_id: str) -> dict[str, Any]:
    """在独立 Python 子进程里执行单条用例，避免异步模型客户端跨用例复用。"""
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix=f"{case.num.lower()}_",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        result_path = Path(tmp.name)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--case-index",
        str(TEST_CASES.index(case)),
        "--session-id",
        session_id,
        "--result-file",
        str(result_path),
    ]

    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=360,
            check=False,
        )
        if completed.stdout:
            print(completed.stdout.strip())

        if result_path.exists() and result_path.stat().st_size > 0:
            with result_path.open("r", encoding="utf-8") as f:
                return json.load(f)

        return {
            "num": case.num,
            "category": case.category,
            "difficulty": case.difficulty,
            "question": case.question,
            "expected": case.expected,
            "session_id": session_id,
            "customer_id": case.customer_id,
            "customer_no": case.customer_no,
            "answer": "",
            "pending_action": None,
            "events": [],
            "status": "error",
            "error": f"子进程未生成结果，退出码={completed.returncode}",
            "duration": round(time.perf_counter() - start, 2),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "num": case.num,
            "category": case.category,
            "difficulty": case.difficulty,
            "question": case.question,
            "expected": case.expected,
            "session_id": session_id,
            "customer_id": case.customer_id,
            "customer_no": case.customer_no,
            "answer": "",
            "pending_action": None,
            "events": [],
            "status": "error",
            "error": f"子进程超时：{exc}",
            "duration": round(time.perf_counter() - start, 2),
        }
    finally:
        try:
            result_path.unlink(missing_ok=True)
        except OSError:
            pass


def _run_child(case_index: int, session_id: str, result_file: Path) -> None:
    """子进程入口：只执行一条用例并把结构化结果写到文件。"""
    from agent.llm.model import initialize_model
    from agent.memory.runtime import get_runtime
    from agent.utils.helpers import configure_logging

    configure_logging(verbose=False)
    initialize_model()

    runtime = get_runtime()
    runtime.startup()
    try:
        result = _run_one(TEST_CASES[case_index], session_id)
    finally:
        runtime.shutdown()

    result_file.parent.mkdir(parents=True, exist_ok=True)
    with result_file.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)


def save_results(results: list[dict[str, Any]]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = PROJECT_ROOT / "tests" / "results" / f"agent_qa_test_{timestamp}.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    success = sum(1 for r in results if r["status"] == "success")
    awaiting = sum(1 for r in results if r["status"] == "awaiting_review")
    failed = sum(1 for r in results if r["status"] == "error")
    total_time = sum(float(r["duration"]) for r in results)

    with output.open("w", encoding="utf-8") as f:
        f.write("# Agent QA 测试报告\n\n")
        f.write(f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## 统计\n\n")
        f.write(f"- 总问题: {len(results)}\n")
        f.write(f"- 成功完成: {success}\n")
        f.write(f"- 等待人工确认: {awaiting}\n")
        f.write(f"- 失败: {failed}\n")
        f.write(f"- 总耗时: {total_time:.1f}秒\n")
        f.write(f"- 平均: {total_time / len(results):.1f}秒/问题\n\n")

        f.write("## 测试数据\n\n")
        f.write("| 编号 | 分类 | 难度 | Session | Customer | 预期 |\n")
        f.write("| --- | --- | --- | --- | --- | --- |\n")
        for r in results:
            customer = f"{r['customer_id']} / {r['customer_no']}"
            f.write(
                f"| {r['num']} | {r['category']} | {r['difficulty']} | "
                f"`{r['session_id']}` | `{customer}` | {r['expected']} |\n"
            )
        f.write("\n")

        f.write("## QA 对\n\n")
        for r in results:
            marker = {
                "success": "通过",
                "awaiting_review": "待人工确认",
                "error": "失败",
            }.get(r["status"], r["status"])
            f.write(f"### {marker} {r['num']}: {r['question']}\n\n")
            f.write(f"**分类**: {r['category']} / {r['difficulty']}\n\n")
            f.write(f"**Session**: `{r['session_id']}`\n\n")
            f.write(f"**耗时**: {r['duration']}秒\n\n")
            f.write(f"**预期**: {r['expected']}\n\n")

            if r["error"]:
                f.write("**错误**:\n\n")
                f.write(f"```text\n{r['error']}\n```\n\n")

            if r["pending_action"]:
                f.write("**待人工确认动作**:\n\n")
                f.write(
                    "```json\n"
                    + json.dumps(r["pending_action"], ensure_ascii=False, indent=2, default=str)
                    + "\n```\n\n"
                )

            f.write("**回答**:\n\n")
            f.write(f"```text\n{r['answer'] or '（无最终回答）'}\n```\n\n")

            f.write("**事件流**:\n\n")
            f.write("| 序号 | 类型 | 阶段 | 标签 | 关键数据 |\n")
            f.write("| --- | --- | --- | --- | --- |\n")
            for idx, event in enumerate(r["events"], 1):
                event_type = event.get("type", "")
                stage = event.get("stage", "")
                label = event.get("label", "")
                update = _compact_update(event.get("update"))
                update = update.replace("\n", "<br>").replace("|", "\\|")
                f.write(f"| {idx} | `{event_type}` | `{stage}` | {label} | {update} |\n")
            f.write("\n---\n\n")

    return output


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Agent QA 测试记录脚本")
    parser.add_argument("--case-index", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--session-id", default="", help=argparse.SUPPRESS)
    parser.add_argument("--result-file", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.case_index is not None:
        if not args.result_file:
            raise SystemExit("--result-file 不能为空")
        _run_child(args.case_index, args.session_id, Path(args.result_file))
        return

    print("=" * 70)
    print("Agent QA 测试 - 开始")
    print("=" * 70)

    session_ids: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    print(f"\n[1/2] 运行 {len(TEST_CASES)} 个测试问题（每条用例独立子进程）...\n")
    for index, case in enumerate(TEST_CASES, 1):
        session_id = _session_id_for(case, session_ids)
        print(f"问题 {index}/{len(TEST_CASES)} {case.num}: {case.question}")
        result = _run_one_in_child(case, session_id)
        results.append(result)
        print(f"状态: {result['status']}，耗时: {result['duration']}秒\n")

    print("[2/2] 保存结果...")
    output = save_results(results)
    print(f"结果已保存: {output}")

    success = sum(1 for r in results if r["status"] == "success")
    awaiting = sum(1 for r in results if r["status"] == "awaiting_review")
    failed = sum(1 for r in results if r["status"] == "error")
    total_time = sum(float(r["duration"]) for r in results)
    print("=" * 70)
    print(f"统计: 成功 {success}, 待人工确认 {awaiting}, 失败 {failed}, 总耗时 {total_time:.1f}秒")
    print("=" * 70)


if __name__ == "__main__":
    main()
