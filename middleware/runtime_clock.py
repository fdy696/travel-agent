"""Runtime clock middleware.

为 Agent 每次模型调用动态注入当前日期、星期、时间、时区和年份。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage

_WEEKDAY_NAMES = (
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
)


def runtime_clock_context() -> str:
    """生成当前调用时刻的时间上下文。"""
    now = datetime.now().astimezone()
    timezone_name = now.tzname() or str(now.utcoffset() or "local")
    return (
        "# Runtime Current Date\n"
        f"当前日期：{now:%Y-%m-%d}\n"
        f"当前星期：{_WEEKDAY_NAMES[now.weekday()]}\n"
        f"当前时间：{now:%H:%M:%S}\n"
        f"当前时区：{timezone_name}\n"
        f"当前年份：{now:%Y}\n\n"
        "以上 Runtime 时间是处理相对日期、最新信息和时效性 Research 的唯一时间基准。"
    )


def _append_runtime_context(request: ModelRequest) -> ModelRequest:
    context = runtime_clock_context()
    current_content = request.system_message.content

    if isinstance(current_content, str):
        content: Any = (
            f"{current_content}\n\n{context}"
            if current_content
            else context
        )
    else:
        content = [
            *current_content,
            {"type": "text", "text": context},
        ]

    return request.override(system_message=SystemMessage(content=content))


class RuntimeClockMiddleware(AgentMiddleware):
    """每次模型调用前动态注入当前时间上下文。"""

    name = "RuntimeClockMiddleware"

    def wrap_model_call(self, request: ModelRequest, handler):
        return handler(_append_runtime_context(request))

    async def awrap_model_call(self, request: ModelRequest, handler):
        return await handler(_append_runtime_context(request))
