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


async def ask(agent, question: str, *, session_id: str) -> str:
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        config=_config(session_id),
        context=_context(session_id),
    )
    return _clean(result["messages"][-1].content)


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
            reply = asyncio.run(ask(agent, message, session_id=session_id))
        except Exception as e:
            _error(f"{type(e).__name__}: {e}")
            raise typer.Exit(1)
        console.print(reply, markup=False)
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

        try:
            reply = await ask(agent, user_input, session_id=session_id)
        except Exception as e:
            _error(f"{type(e).__name__}: {e}")
            console.print()
            continue

        console.print("[bold]助手：[/bold]")
        console.print(reply, markup=False)
        console.print()


if __name__ == "__main__":
    app()
