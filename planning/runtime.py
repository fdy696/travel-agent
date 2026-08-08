"""运行时身份上下文。

它属于一次 run 的不可变上下文，不属于聊天消息，也不属于 PlanningState。
Deep Agents 会把父 Agent 的 runtime context 传给同步 Subagent。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TravelRuntimeContext:
    user_id: str
    session_id: str
