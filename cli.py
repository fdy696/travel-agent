"""v4.1 Week 2 CLI：通用问答 + 多轮首次行程规划。

用法（在 backend_v4 目录下）：
  uv run python -m cli
  uv run python -m cli --message "帮我规划云南5日游，2个人"
  uv run python -m cli --session-id demo-001

Week 2 使用 InMemorySaver 保持当前进程中的对话上下文；PlanningTask/Plan V1
另存 SQLite，因此业务数据不会跟随一次 LLM 调用消失。
"""
from __future__ import annotations

import asyncio
import sys
import uuid

import typer
from rich.console import Console
from rich.prompt import Prompt

from agent import build_agent
from planning.runtime import TravelRuntimeContext

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

app = typer.Typer(
    name="travel-agent",
    help="行伴旅游助手（v4.1 / Deep Agents / Week 2）",
    no_args_is_help=False,
)
console = Console()
QUIT_WORDS = ("/quit", "/exit", "/q", "退出")


def _clean(text: str) -> str:
    if not isinstance(text, str):
        return str(text)
    return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _error(msg: str) -> None:
    console.print("[red][错误][/red]", end=" ")
    console.print(msg, markup=False)


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _context(session_id: str) -> TravelRuntimeContext:
    return TravelRuntimeContext(user_id="cli-user", session_id=session_id)


# 子 Agent（travel-planning）内部节点 → 进度提示
_PLANNING_STEPS = {
    "load_task": "读取会话记录",
    "extract_requirements": "分析你的需求",
    "check_requirements": "检查需求完整性",
    "respond_need_more": "向你补充提问",
    "research": "调研目的地信息",
    "generate": "生成行程草案",
    "persist": "保存行程",
    "finish": "整理行程输出",
    "fail": "规划未能完成",
}

# 主 Agent 直接调用的工具 → 提示
_TOOL_STEPS = {
    "get_weather": "查询天气",
    "search_travel_info": "搜索旅游信息",
    "search_maps": "查询路线",
    "read_active_plan": "读取当前行程",
    "modify_travel_plan": "修改行程",
}


async def ask_stream(agent, question: str, *, session_id: str) -> str:
    """流式执行一轮问答。

    参照 DeepSeek/豆包的交互：工具调用、子 Agent 内部进度以状态行实时呈现，
    最终回答逐字输出（打字机效果），而不是 ainvoke 一次卡住等结果。
    返回最终回答文本（供单次模式使用），流式内容已直接打印。
    """
    parts: list[str] = []
    in_text = False
    seen: set[tuple[str, str]] = set()

    def end_text() -> None:
        nonlocal in_text
        if in_text:
            print()
            in_text = False

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": question}]},
        config=_config(session_id),
        context=_context(session_id),
        version="v2",
    ):
        ev = event["event"]
        node = event.get("metadata", {}).get("langgraph_node", "")
        name = event.get("name", "")

        # 主 Agent 正文（travel-planning / research 子 agent 内部的 LLM 节点
        # 也有 node="model"，但它们的 langgraph_checkpoint_ns 以 "tools:" 开头，
        # 用这个差异过滤掉，只流式显示主 Agent 的回答。）
        if ev == "on_chat_model_stream" and node == "model":
            meta = event.get("metadata", {})
            if meta.get("langgraph_checkpoint_ns", "").startswith("tools:"):
                continue
            chunk = event.get("data", {}).get("chunk")
            delta = getattr(chunk, "content", "") or ""
            if delta:
                if not in_text:
                    print()
                    in_text = True
                print(delta, end="", flush=True)
                parts.append(delta)
            continue

        # 主 Agent 直接调工具：显示"做什么"（含参数摘要）
        if ev == "on_tool_start" and node == "tools":
            if name == "task":
                continue  # task 参数是长 description，统一由"开始规划行程…"提示
            label = _TOOL_STEPS.get(name, name)
            summary = ""
            inp = event.get("data", {}).get("input")
            if isinstance(inp, dict):
                # modify_travel_plan 只展示用户指令，不暴露 plan_id/version 内部细节
                if name == "modify_travel_plan" and inp.get("instruction"):
                    summary = str(inp["instruction"])[:40]
                else:
                    vals = [
                        str(v)
                        for v in inp.values()
                        if isinstance(v, (str, int))
                        and not isinstance(v, bool)
                        and str(v).strip()
                        and not str(v).strip().isdigit()
                    ]
                    if vals:
                        summary = "：".join(vals[:2])[:40]
            end_text()
            print(f"  · {label}{('：' + summary) if summary else ''}", flush=True)
            continue

        # 子 Agent 委派与内部节点进度
        if ev == "on_chain_start" and "Middleware" not in node:
            if node == "tools" and name == "travel-planning":
                end_text()
                print("  · 开始规划行程…", flush=True)
            elif node in _PLANNING_STEPS:
                key = ("node", node)
                if key not in seen:
                    seen.add(key)
                    end_text()
                    print(f"  · {_PLANNING_STEPS[node]}", flush=True)

    end_text()
    return _clean("".join(parts))


@app.callback(invoke_without_command=True)
def main(
    message: str = typer.Option(None, "--message", "-m", help="单次问答，不进入交互模式"),
    session_id: str = typer.Option(
        None,
        "--session-id",
        help="会话 ID；不传则本次进程自动生成。用于调试规划任务续接。",
    ),
) -> None:
    session_id = session_id or f"cli-{uuid.uuid4().hex[:12]}"
    try:
        agent = build_agent()
    except Exception as e:
        _error(f"初始化失败：{type(e).__name__}: {e}")
        raise typer.Exit(1)

    if message:
        try:
            asyncio.run(ask_stream(agent, message, session_id=session_id))
        except Exception as e:
            _error(f"{type(e).__name__}: {e}")
            raise typer.Exit(1)
        print()
        return

    asyncio.run(_repl(agent, session_id=session_id))


async def _repl(agent, *, session_id: str) -> None:
    console.print("[bold]行伴旅游助手（v4.1 / Deep Agents / Week 2）[/bold]")
    console.print(f"会话：{session_id}", markup=False)
    console.print("支持通用问答与首次多轮行程规划；输入 /quit 退出。\n")

    while True:
        try:
            user_input = Prompt.ask("你").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n再见！")
            return

        if not user_input:
            continue
        if user_input.lower() in QUIT_WORDS:
            console.print("再见！")
            return

        console.print("[bold]助手：[/bold]")
        try:
            await ask_stream(agent, user_input, session_id=session_id)
        except Exception as e:
            _error(f"{type(e).__name__}: {e}")
            console.print()
            continue
        console.print()


if __name__ == "__main__":
    app()
