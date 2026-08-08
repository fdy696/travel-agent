"""CLI：Main Deep Agent + Travel Skill + Redis Checkpointer。"""
from __future__ import annotations

import asyncio
import sys
import uuid

import typer
from rich.console import Console
from rich.prompt import Prompt

from agent import build_agent
from config import get_settings
from persistence import open_redis_checkpointer
from planning.runtime import TravelRuntimeContext


for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

app = typer.Typer(name="travel-agent", help="行伴旅游助手", no_args_is_help=False)
console = Console()
QUIT_WORDS = ("/quit", "/exit", "/q", "退出")

_TOOL_STEPS = {
    "get_weather": "查询天气",
    "search_travel_info": "搜索旅游信息",
    "search_maps": "查询路线",
    "update_requirements": "整理出行需求",
    "get_current_plan": "读取当前行程",
    "create_plan": "保存新行程",
    "update_plan": "保存修改后的行程",
    "begin_plan_change": "准备修改行程",
}


def _config(session_id: str) -> dict:
    # recursion_limit 是正常复杂 agent run 的全局容量，不承担业务循环保护。
    # PlanCompletionMiddleware 自己有更小的 pending budget 来终止跑偏。
    return {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 60,
    }


def _context(session_id: str) -> TravelRuntimeContext:
    return TravelRuntimeContext(
        user_id="cli-user",
        session_id=session_id,
        timezone=get_settings().TRAVEL_TIMEZONE,
    )


async def ask_stream(agent, question: str, *, session_id: str) -> str:
    parts: list[str] = []
    in_text = False
    announced_task = False

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
        meta = event.get("metadata", {})

        # 只打印 Main Agent 最终正文；SubAgent model 输出保留在隔离 context。
        if ev == "on_chat_model_stream" and node == "model":
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

        if ev == "on_tool_start":
            if name == "task":
                if not announced_task:
                    announced_task = True
                    end_text()
                    print("  · 深入检索中…", flush=True)
                continue
            if name in _TOOL_STEPS:
                end_text()
                print(f"  · {_TOOL_STEPS[name]}", flush=True)

    end_text()
    return "".join(parts)


async def _run(*, message: str | None, session_id: str) -> None:
    # Redis checkpointer 与 agent 的生命周期绑定；退出 CLI 时自动关闭连接。
    async with open_redis_checkpointer() as checkpointer:
        agent = build_agent(checkpointer=checkpointer)

        if message:
            await ask_stream(agent, message, session_id=session_id)
            print()
            return

        await _repl(agent, session_id=session_id)


@app.callback(invoke_without_command=True)
def main(
    message: str = typer.Option(None, "--message", "-m", help="单次问答"),
    session_id: str = typer.Option(None, "--session-id", help="会话 ID"),
) -> None:
    session_id = session_id or f"cli-{uuid.uuid4().hex[:12]}"
    try:
        asyncio.run(_run(message=message, session_id=session_id))
    except Exception as exc:
        console.print(f"[red]运行失败：{type(exc).__name__}: {exc}[/red]")
        raise typer.Exit(1)


async def _repl(agent, *, session_id: str) -> None:
    console.print("[bold]行伴旅游助手[/bold]")
    console.print(f"会话：{session_id}", markup=False)
    console.print("支持旅游问答、完整行程创建与自然语言修改；输入 /quit 退出。\n")

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
        except Exception as exc:
            console.print(f"[red]{type(exc).__name__}: {exc}[/red]")
        console.print()


if __name__ == "__main__":
    app()
