"""执行器测试：依赖分波 + 波内优先级并发；非法依赖与任务失败均直接抛出。"""

from __future__ import annotations

import asyncio

import pytest

from agent.customer_agent import CustomerAgent, Task


def _waves_as_agents(tasks: list[Task]) -> list[list[str]]:
    return [[t.agent for t in wave] for wave in CustomerAgent.plan_waves(tasks)]


def test_independent_same_priority_run_in_one_wave() -> None:
    tasks = [Task(agent="tech", priority=10), Task(agent="product", priority=10)]
    assert _waves_as_agents(tasks) == [["tech", "product"]]


def test_dependency_forces_later_wave() -> None:
    tasks = [
        Task(agent="order", priority=10),
        Task(agent="product", priority=10, depends_on=["order"]),
    ]
    assert _waves_as_agents(tasks) == [["order"], ["product"]]


def test_priority_orders_independent_tasks_into_separate_waves() -> None:
    tasks = [Task(agent="order", priority=10), Task(agent="tech", priority=50)]
    assert _waves_as_agents(tasks) == [["order"], ["tech"]]


def test_cyclic_dependency_raises() -> None:
    # 互相依赖（环）：无任何就绪任务时直接抛错，不再静默兜底推进
    tasks = [
        Task(agent="order", priority=10, depends_on=["product"]),
        Task(agent="product", priority=10, depends_on=["order"]),
    ]
    with pytest.raises(ValueError):
        CustomerAgent.plan_waves(tasks)


def test_run_wave_executes_concurrently_and_records_results() -> None:
    tasks = [Task(agent="tech"), Task(agent="product")]

    async def runner(task: Task) -> str:
        return f"{task.agent}-done"

    asyncio.run(CustomerAgent.run_wave(tasks, runner))

    assert {t.agent: (t.result, t.status) for t in tasks} == {
        "tech": ("tech-done", "done"),
        "product": ("product-done", "done"),
    }


def test_run_wave_propagates_single_task_failure() -> None:
    # 单任务失败不再被吞掉为占位结果，而是直接向上抛出
    tasks = [Task(agent="tech"), Task(agent="product")]

    async def runner(task: Task) -> str:
        if task.agent == "tech":
            raise RuntimeError("boom")
        return "ok"

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(CustomerAgent.run_wave(tasks, runner))

