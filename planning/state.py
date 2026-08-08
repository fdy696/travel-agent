"""Main Agent 的短期执行状态。

这里不是业务事实库。Requirements / Current Plan 仍只存在 SQLite；
这些字段只用于约束当前 Agent loop 是否允许结束，并给 completion guard 一个有限预算。
"""
from __future__ import annotations

from typing import Literal, NotRequired

from langchain.agents import AgentState


PlanTaskStatus = Literal["none", "pending", "committed"]
ExpectedCommitTool = Literal["create_plan", "update_plan"]


class TravelAgentState(AgentState):
    """Travel Agent 的 thread-scoped 控制状态。"""

    plan_task_status: NotRequired[PlanTaskStatus]
    expected_commit_tool: NotRequired[ExpectedCommitTool | None]
    completion_retry: NotRequired[int]
    pending_model_calls: NotRequired[int]
