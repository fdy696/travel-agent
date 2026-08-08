import json
from typing import Optional

from deepagents.core.middleware import Middleware, MiddlewareV1
from deepagents.core.state import AgentState

MAX_COMPLETION_RETRY = 2


class PlanCompletionMiddleware(MiddlewareV1):
    """This middleware prevents the agent from ending the conversation prematurely
    if a travel plan is pending but has not yet been committed.
    """

    def after_model(self, state: AgentState) -> Optional[Middleware]:
        """Checks the state after the model runs and decides if the agent can end."""
        status = state.get("plan_task_status", "none")
        if status != "pending":
            return None

        # If status is pending, the agent must not end without a tool call.
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return None

        # The agent is trying to end with a pending task. Intercept.
        retry_count = state.get("completion_retry", 0)
        if retry_count >= MAX_COMPLETION_RETRY:
            # Too many retries, end with a failure message.
            return {
                "messages": [
                    (
                        "ai",
                        "ERROR PLAN_COMPLETION_FAILED\n抱歉，我在尝试完成计划时遇到内部错误，请稍后重试。",
                    )
                ]
            }

        # Force the agent to go back to the model for another thinking step.
        return {
            "state": {"completion_retry": retry_count + 1},
            "messages": [
                (
                    "system",
                    "当前 Plan 任务尚未完成。请继续生成完整计划并通过 Plan Domain Tool 提交。不要只描述下一步。",
                )
            ],
            "jump_to": "model",
        }
