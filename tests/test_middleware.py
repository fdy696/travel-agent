from langchain.messages import AIMessage

from middleware import (
    MAX_COMPLETION_RETRY,
    MAX_PENDING_MODEL_CALLS,
    PlanCompletionMiddleware,
)


def test_pending_plan_without_tool_call_is_sent_back_to_model():
    middleware = PlanCompletionMiddleware()
    state = {
        "messages": [AIMessage(content="研究完成，现在准备生成计划。")],
        "plan_task_status": "pending",
        "expected_commit_tool": "create_plan",
        "completion_retry": 0,
        "pending_model_calls": 1,  # before_model has already run
    }

    update = middleware.after_model(state, runtime=None)

    assert update == {
        "completion_retry": 1,
        "jump_to": "model",
    }


def test_pending_plan_with_tool_call_is_allowed_to_continue():
    middleware = PlanCompletionMiddleware()
    state = {
        "messages": [
            AIMessage(
                content="再确认一下预约信息",
                tool_calls=[
                    {
                        "name": "search_travel_info",
                        "args": {"query": "故宫预约"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        ],
        "plan_task_status": "pending",
        "expected_commit_tool": "create_plan",
        "completion_retry": 0,
        "pending_model_calls": 3,
    }

    assert middleware.after_model(state, runtime=None) is None


def test_model_call_counter_is_incremented_before_each_round():
    middleware = PlanCompletionMiddleware()
    state = {
        "messages": [AIMessage(content="继续")],
        "plan_task_status": "pending",
        "expected_commit_tool": "create_plan",
        "completion_retry": 0,
        "pending_model_calls": 1,
    }

    update = middleware.before_model(state, runtime=None)
    assert update == {"pending_model_calls": 2}


def test_committed_plan_can_end_normally():
    middleware = PlanCompletionMiddleware()
    state = {
        "messages": [AIMessage(content="计划已提交")],
        "plan_task_status": "committed",
        "completion_retry": 0,
        "pending_model_calls": 0,
    }

    assert middleware.after_model(state, runtime=None) is None
    assert middleware.before_model(state, runtime=None) is None


def test_completion_guard_stops_after_bounded_plaintext_retries():
    middleware = PlanCompletionMiddleware()
    state = {
        "messages": [AIMessage(content="仍然没有提交")],
        "plan_task_status": "pending",
        "expected_commit_tool": "create_plan",
        "completion_retry": MAX_COMPLETION_RETRY,
        "pending_model_calls": 2,
    }

    update = middleware.after_model(state, runtime=None)

    assert update["jump_to"] == "end"
    assert update["plan_task_status"] == "none"
    assert update["completion_retry"] == 0
    assert update["pending_model_calls"] == 0
    assert "PLAN_COMPLETION_FAILED" in update["messages"][-1].content


def test_completion_guard_stops_before_next_model_when_pending_budget_exhausted():
    middleware = PlanCompletionMiddleware()
    state = {
        "messages": [AIMessage(content="工具结果已返回")],
        "plan_task_status": "pending",
        "expected_commit_tool": "create_plan",
        "completion_retry": 0,
        "pending_model_calls": MAX_PENDING_MODEL_CALLS,
    }

    update = middleware.before_model(state, runtime=None)

    assert update["jump_to"] == "end"
    assert update["plan_task_status"] == "none"
    assert "PLAN_COMPLETION_BUDGET_EXCEEDED" in update["messages"][-1].content
