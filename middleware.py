"""Travel Agent middleware。

- RuntimeContextMiddleware: 向每次模型调用瞬时注入当前日期/时区。
- PlanCompletionMiddleware: 对已开始的 Plan mutation 强制 completion invariant。

注意：这里的 state 是 LangGraph thread state，不是 SQLite 业务状态。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    hook_config,
)
from langchain.messages import AIMessage, SystemMessage

from planning.runtime import TravelRuntimeContext
from planning.state import TravelAgentState


# “提前用纯文本结束”的恢复次数。它不是整个 agent 的循环上限。
MAX_COMPLETION_RETRY = 2

# Requirements 完整 / 修改任务开始之后，Main Agent 最多再进行多少次 model round。
# Researcher 内部的隔离搜索不按这里逐次计数；这里只限制 Main loop，防止无限“再查一下”。
MAX_PENDING_MODEL_CALLS = 8


def _append_system_text(request: ModelRequest, text: str) -> ModelRequest:
    new_content = list(request.system_message.content_blocks) + [
        {"type": "text", "text": text}
    ]
    return request.override(system_message=SystemMessage(content=new_content))


class RuntimeContextMiddleware(AgentMiddleware):
    """瞬时注入当前日期与用户时区，不写入 conversation history。"""

    @staticmethod
    def _prepare(request: ModelRequest) -> ModelRequest:
        context = request.runtime.context
        if not isinstance(context, TravelRuntimeContext):
            return request

        try:
            tz = ZoneInfo(context.timezone)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")

        current_date = datetime.now(tz).date().isoformat()
        return _append_system_text(
            request,
            (
                "# Runtime facts\n"
                f"Current date: {current_date}\n"
                f"User timezone: {context.timezone}\n"
                "Interpret relative dates such as 今天/明天/后天 strictly from these runtime facts."
            ),
        )

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._prepare(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._prepare(request))


class PlanCompletionMiddleware(AgentMiddleware[TravelAgentState]):
    """禁止已经开始的 Plan mutation 在 commit 前结束或无限游走。"""

    state_schema = TravelAgentState

    @staticmethod
    def _prepare(request: ModelRequest) -> ModelRequest:
        if request.state.get("plan_task_status", "none") != "pending":
            return request

        expected = request.state.get("expected_commit_tool") or "create_plan/update_plan"
        retry = request.state.get("completion_retry", 0)
        rounds = request.state.get("pending_model_calls", 0)

        if retry > 0:
            text = (
                "# Plan commit recovery\n"
                "Your previous model response attempted to finish a pending Plan mutation without committing it.\n"
                f"The deterministic code boundary expects `{expected}`.\n"
                "Do NOT perform additional research in this recovery call. "
                "Use the facts already gathered, construct the complete PlanContent, and call the expected commit tool now. "
                "If the commit tool returns a schema error, repair that schema error and retry. "
                "Do not output another statement of intent such as 'I will create the plan now'."
            )
        else:
            text = (
                "# Plan completion invariant\n"
                "A Plan mutation is currently pending. You may research, reason, repair schema, or use tools freely, "
                "but you MUST NOT finish with a normal text response before the Plan commit succeeds. "
                "A Research Brief or a statement that you are about to create the plan is intermediate output, never final delivery.\n"
                f"Expected commit tool from deterministic state: `{expected}`.\n"
                f"Main-agent pending round budget used: {rounds}/{MAX_PENDING_MODEL_CALLS}."
            )
        return _append_system_text(request, text)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._prepare(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._prepare(request))

    @staticmethod
    def _terminal_update(code: str, message: str) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content=f"ERROR {code}\n{message}")],
            "plan_task_status": "none",
            "expected_commit_tool": None,
            "completion_retry": 0,
            "pending_model_calls": 0,
            "jump_to": "end",
        }

    @hook_config(can_jump_to=["end"])
    def before_model(
        self,
        state: TravelAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        """在一个新的 model round 开始前检查 pending 预算。

        放在 before_model 而不是在已有 tool_calls 的 after_model 强行 end，
        可以保证上一轮 ToolMessage 已经完整落入消息历史，不制造悬空 tool call。
        """
        if state.get("plan_task_status", "none") != "pending":
            return None

        next_round_count = state.get("pending_model_calls", 0) + 1
        if next_round_count > MAX_PENDING_MODEL_CALLS:
            return self._terminal_update(
                "PLAN_COMPLETION_BUDGET_EXCEEDED",
                "行程规划已超过内部完成预算，系统已停止继续研究/循环，且没有声称保存成功。",
            )

        return {"pending_model_calls": next_round_count}

    @hook_config(can_jump_to=["model", "end"])
    def after_model(
        self,
        state: TravelAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        if state.get("plan_task_status", "none") != "pending":
            return None

        last_message = state["messages"][-1]

        # 有 tool call 时正常执行，但也必须计入 pending Main-model budget。
        # 这正是上一版漏掉的地方：模型可以无限 search/tool 而 completion_retry 始终为 0。
        if getattr(last_message, "tool_calls", None):
            return None

        retry_count = state.get("completion_retry", 0)
        if retry_count >= MAX_COMPLETION_RETRY:
            return self._terminal_update(
                "PLAN_COMPLETION_FAILED",
                "行程规划多次尝试结束但始终没有完成最终提交，系统已安全终止本轮任务。",
            )

        # 不替模型生成 Plan，也不替它调用业务 Tool；只把未完成的任务送回模型。
        # 下一次模型调用会收到更强的 transient commit-recovery instruction。
        return {
            "completion_retry": retry_count + 1,
            "jump_to": "model",
        }
