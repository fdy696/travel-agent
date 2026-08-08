"""运行时不可变上下文。

它不属于聊天消息，也不属于 SQLite 业务状态。
Deep Agents 会把父 Agent 的 runtime context 传给同步 SubAgent。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TravelRuntimeContext:
    user_id: str
    session_id: str
    timezone: str = "Asia/Shanghai"
