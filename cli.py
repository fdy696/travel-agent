"""行伴 CLI：用于验证“生成计划 + 同会话自然语言修改”的最小闭环。"""
from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any

import typer
from langgraph.checkpoint.memory import InMemorySaver
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from agent import build_agent


for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


app = typer.Typer(name="travel-agent", help="行伴 Travel Agent", no_args_is_help=False)
console = Console()
QUIT_WORDS = ("/quit", "/exit", "/q", "退出")


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _content_to_text(content: Any) -> str:
    """兼容 str 和 content-block 两种 AIMessage.content。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        text = block.get("text") or block.get("content")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


async def ask(agent, question: str, *, thread_id: str) -> str:
    """只提交本轮 user message；历史由 checkpointer 根据 thread_id 恢复。"""
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        config=_config(thread_id),
    )
    messages = result.get("messages") or []
    if not messages:
        return ""
    return _content_to_text(messages[-1].content)


async def _repl(agent, *, thread_id: str) -> None:
    console.print("[bold]行伴 Travel Agent[/bold]")
    console.print(f"会话：{thread_id}", markup=False)
    console.print("可直接生成旅行计划；生成后继续说“第二天换成环球影城”等即可修改。")
    console.print("当前 CLI 使用内存 Checkpointer：退出进程后会话不保留。输入 /quit 退出。\n")

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
            answer = await ask(agent, user_input, thread_id=thread_id)
        except Exception as exc:
            console.print(f"[red]运行失败：{type(exc).__name__}: {exc}[/red]")
            continue

        console.print("\n[bold]行伴：[/bold]")
        console.print(Markdown(answer) if answer else "[dim]（模型未返回正文）[/dim]")
        console.print()


async def _run(*, message: str | None, thread_id: str) -> None:
    # Phase 1-2 只需要进程内连续对话；生产持久化留到 Runtime 阶段替换。
    checkpointer = InMemorySaver()
    agent = build_agent(checkpointer=checkpointer)

    if message:
        answer = await ask(agent, message, thread_id=thread_id)
        console.print(Markdown(answer) if answer else "")
        return

    await _repl(agent, thread_id=thread_id)


@app.callback(invoke_without_command=True)
def main(
    message: str | None = typer.Option(None, "--message", "-m", help="单次问答 / 规划"),
    thread_id: str | None = typer.Option(None, "--thread-id", help="会话 ID（当前仅进程内有效）"),
) -> None:
    thread_id = thread_id or f"cli-{uuid.uuid4().hex[:12]}"
    try:
        asyncio.run(_run(message=message, thread_id=thread_id))
    except Exception as exc:
        console.print(f"[red]启动失败：{type(exc).__name__}: {exc}[/red]")
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
