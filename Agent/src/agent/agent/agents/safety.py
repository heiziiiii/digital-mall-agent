"""本地安全审核。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.customer_agent import AgentContext

FALLBACK_ANSWER = "抱歉，这个问题我暂时无法直接回答。如需进一步帮助，请联系人工客服。"

_SENSITIVE_PATTERNS = (
    (r"(?<!\d)1[3-9]\d{9}(?!\d)", "回答包含未脱敏手机号"),
    (r"(?<![A-Za-z0-9])\d{17}[\dXx](?![A-Za-z0-9])", "回答包含未脱敏身份证号"),
    (r"(?<![A-Za-z0-9])\d{16,19}(?![A-Za-z0-9])", "回答包含疑似未脱敏银行卡号"),
)

_UNSAFE_TERMS = ("破解", "绕过安全", "绕过平台", "绕锁", "规避保修", "伪造凭证")
_DANGEROUS_TERMS = ("电池鼓包", "冒烟", "异味", "进水", "短路", "高压", "拆机")
_DANGEROUS_INSTRUCTION_TERMS = ("步骤", "首先", "然后", "继续使用", "自行拆", "拆开", "短接")
_UNVERIFIED_WRITE_PROMISES = (
    "已退款",
    "已换货",
    "已取消",
    "已改单",
    "已提交售后",
    "已创建售后",
    "已成功发起",
    "成功发起",
)


def audit(ctx: AgentContext, evidence: str = "") -> tuple[bool, str]:
    """本地规则安全审核，不调用 LLM。"""
    answer = ctx.final_answer.strip()
    if not answer:
        return False, "回答为空。"

    for pattern, feedback in _SENSITIVE_PATTERNS:
        if re.search(pattern, answer):
            return False, feedback

    combined = f"{ctx.user_input}\n{answer}".lower()
    if any(term in combined for term in _UNSAFE_TERMS):
        return False, "回答涉及破解、绕过安全机制或伪造凭证。"

    if any(term in combined for term in _DANGEROUS_TERMS) and any(
        term in answer for term in _DANGEROUS_INSTRUCTION_TERMS
    ):
        return False, "回答可能包含危险操作指导。"

    if getattr(ctx, "write_confirmed", False):
        return True, ""

    if any(term in answer for term in _UNVERIFIED_WRITE_PROMISES) and not any(
        term in evidence for term in _UNVERIFIED_WRITE_PROMISES
    ):
        return False, "回答包含未经工具结果确认的订单/售后写操作承诺。"

    return True, ""


def apply(ctx: AgentContext, evidence: str = "") -> None:
    """执行安全审核，不通过时切换兜底话术。"""
    passed, feedback = audit(ctx, evidence=evidence)
    if passed:
        ctx.safety_passed = True
        ctx.safety_feedback = ""
        return

    ctx.safety_passed = True
    ctx.safety_retry += 1
    ctx.safety_feedback = feedback
    ctx.final_answer = FALLBACK_ANSWER
