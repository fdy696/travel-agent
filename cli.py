"""行伴 CLI：开发环境默认显示可读执行轨迹，完整原始事件写入日志。"""
from __future__ import annotations

import asyncio
import pprint
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from agent import build_agent
from config import get_settings
from tools.search import current_search_provider_name


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


def _truncate(value: Any, limit: int = 140) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _scope(namespace: Any) -> str:
    return "SUB " if namespace else "MAIN"


def _trace_line(started_at: float, scope: str, action: str, detail: str = "") -> None:
    elapsed = time.perf_counter() - started_at
    prefix = f"[{elapsed:7.1f}s] [{scope}]"
    if detail:
        console.print(f"{prefix} {action:<10} {detail}", markup=False)
    else:
        console.print(f"{prefix} {action}", markup=False)


def _tool_detail(name: str, args: dict[str, Any]) -> str:
    preferred_keys = (
        "query",
        "file_path",
        "location",
        "origin",
        "destination",
        "date",
    )
    for key in preferred_keys:
        if key in args and args[key] not in (None, ""):
            return _truncate(args[key])
    return _truncate(args)


def _is_skill_path(path: str) -> bool:
    return "/skills/" in path and path.endswith("/SKILL.md")


def _is_contract_path(path: str) -> bool:
    return path.endswith("/references/markdown-contract.md")


def _write_log(log_file, part: Any) -> None:
    timestamp = datetime.now().astimezone().isoformat()
    log_file.write(f"\n===== {timestamp} =====\n")
    log_file.write(pprint.pformat(part, width=180, sort_dicts=False))
    log_file.write("\n")
    log_file.flush()


def _handle_update(
    *,
    part: dict[str, Any],
    started_at: float,
    seen_calls: set[str],
    delegated_calls: dict[str, str],
) -> str | None:
    """把 raw updates 压缩成终端可读轨迹；返回 Main 最终文本（若出现）。"""
    namespace = part.get("ns") or ()
    scope = _scope(namespace)
    data = part.get("data") or {}
    if not isinstance(data, dict):
        return None

    final_text: str | None = None

    for node_name, update in data.items():
        if not isinstance(update, dict):
            continue
        messages = update.get("messages") or []
        if not isinstance(messages, list):
            continue

        for message in messages:
            if isinstance(message, AIMessage):
                tool_calls = message.tool_calls or []

                for call in tool_calls:
                    call_id = str(call.get("id") or "")
                    if call_id and call_id in seen_calls:
                        continue
                    if call_id:
                        seen_calls.add(call_id)

                    name = str(call.get("name") or "unknown")
                    args = call.get("args") or {}
                    if not isinstance(args, dict):
                        args = {"value": args}

                    if name == "task":
                        subagent_type = str(args.get("subagent_type") or "subagent")
                        if call_id:
                            delegated_calls[call_id] = subagent_type
                        _trace_line(
                            started_at,
                            scope,
                            "Delegate →",
                            subagent_type,
                        )
                        brief = args.get("description")
                        if brief:
                            _trace_line(
                                started_at,
                                scope,
                                "Brief",
                                _truncate(brief, 220),
                            )
                        continue

                    if name == "read_file":
                        path = str(args.get("file_path") or "")
                        if _is_contract_path(path):
                            _trace_line(started_at, scope, "Load", "Markdown Contract")
                        elif _is_skill_path(path):
                            skill_name = Path(path).parent.name
                            _trace_line(started_at, scope, "Load", f"Skill: {skill_name}")
                        else:
                            _trace_line(
                                started_at,
                                scope,
                                "Tool →",
                                f"{name}  {_tool_detail(name, args)}",
                            )
                        continue

                    _trace_line(
                        started_at,
                        scope,
                        "Tool →",
                        f"{name}  {_tool_detail(name, args)}",
                    )

                text = _content_to_text(message.content).strip()
                if not tool_calls and text:
                    if namespace:
                        _trace_line(started_at, scope, "Complete", _truncate(text, 160))
                    else:
                        final_text = text

            elif isinstance(message, ToolMessage):
                tool_name = str(getattr(message, "name", "") or "")
                status = str(getattr(message, "status", "") or "")
                text = _content_to_text(message.content).strip()

                if tool_name == "task" and not namespace:
                    tool_call_id = str(getattr(message, "tool_call_id", "") or "")
                    subagent_type = delegated_calls.get(tool_call_id, "subagent")
                    _trace_line(
                        started_at,
                        "MAIN",
                        "Return ←",
                        subagent_type,
                    )
                elif status and status.lower() not in {"success", "ok"}:
                    _trace_line(
                        started_at,
                        scope,
                        "Tool error",
                        f"{tool_name}: {_truncate(text, 180)}",
                    )

    return final_text


async def _final_answer_from_state(agent, *, thread_id: str) -> str:
    """只读当前 checkpoint，不额外触发一次模型调用。"""
    snapshot = await agent.aget_state(_config(thread_id))
    values = snapshot.values or {}
    messages = values.get("messages") or []

    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = _content_to_text(message.content).strip()
            if text:
                return text
    return ""


async def _ask_debug(
    agent,
    question: str,
    *,
    thread_id: str,
    log_dir: Path,
) -> str:
    """终端显示高可读执行链；完整 StreamPart 原样写日志。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    log_path = log_dir / (
        f"travel-agent-{now:%Y%m%d-%H%M%S}-{thread_id}.log"
    )

    started_at = time.perf_counter()
    seen_calls: set[str] = set()
    delegated_calls: dict[str, str] = {}
    final_answer = ""

    console.print(f"[dim]详细日志：{log_path.resolve()}[/dim]", markup=False)
    _trace_line(started_at, "MAIN", "Start", _truncate(question, 180))

    try:
        with log_path.open("a", encoding="utf-8", errors="backslashreplace") as log_file:
            async for part in agent.astream(
                {"messages": [{"role": "user", "content": question}]},
                config=_config(thread_id),
                stream_mode=["updates", "debug"],
                subgraphs=True,
                version="v2",
            ):
                _write_log(log_file, part)

                if not isinstance(part, dict) or part.get("type") != "updates":
                    continue

                maybe_final = _handle_update(
                    part=part,
                    started_at=started_at,
                    seen_calls=seen_calls,
                    delegated_calls=delegated_calls,
                )
                if maybe_final:
                    final_answer = maybe_final

            if not final_answer:
                final_answer = await _final_answer_from_state(
                    agent,
                    thread_id=thread_id,
                )

            log_file.write("\n===== FINAL ANSWER =====\n")
            log_file.write(final_answer)
            log_file.write("\n")
            log_file.flush()

    except Exception:
        # 完整 traceback 由调用层打印；已有 raw events 已经持续 flush 到日志。
        raise

    _trace_line(started_at, "MAIN", "Done", f"{time.perf_counter() - started_at:.1f}s")
    return final_answer


async def ask(
    agent,
    question: str,
    *,
    thread_id: str,
    debug: bool,
    log_dir: Path,
) -> str:
    """只提交本轮 user message；历史由 checkpointer 根据 thread_id 恢复。"""
    if debug:
        return await _ask_debug(
            agent,
            question,
            thread_id=thread_id,
            log_dir=log_dir,
        )

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        config=_config(thread_id),
    )
    messages = result.get("messages") or []
    if not messages:
        return ""
    return _content_to_text(messages[-1].content)


async def _repl(
    agent,
    *,
    thread_id: str,
    debug: bool,
    log_dir: Path,
) -> None:
    console.print("[bold]行伴 Travel Agent[/bold]")
    console.print(f"会话：{thread_id}", markup=False)
    settings = get_settings()
    console.print(
        f"环境：{settings.APP_ENV}｜搜索策略：{current_search_provider_name()}",
        markup=False,
    )
    console.print(
        "开发调试默认开启：终端显示简洁执行轨迹，完整原始事件写入日志。"
        if debug
        else "调试已关闭：只显示最终回答。"
    )
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
            answer = await ask(
                agent,
                user_input,
                thread_id=thread_id,
                debug=debug,
                log_dir=log_dir,
            )
        except Exception as exc:
            console.print(f"[red]运行失败：{type(exc).__name__}: {exc}[/red]")
            continue

        console.print("\n[bold]行伴：[/bold]")
        console.print(Markdown(answer) if answer else "[dim]（模型未返回正文）[/dim]")
        console.print()


async def _run(
    *,
    message: str | None,
    thread_id: str,
    debug: bool,
    log_dir: Path,
) -> None:
    checkpointer = InMemorySaver()
    agent = build_agent(checkpointer=checkpointer)

    if message:
        answer = await ask(
            agent,
            message,
            thread_id=thread_id,
            debug=debug,
            log_dir=log_dir,
        )
        console.print("\n[bold]行伴：[/bold]")
        console.print(Markdown(answer) if answer else "")
        return

    await _repl(
        agent,
        thread_id=thread_id,
        debug=debug,
        log_dir=log_dir,
    )


@app.callback(invoke_without_command=True)
def main(
    message: str | None = typer.Option(None, "--message", "-m", help="单次问答 / 规划"),
    thread_id: str | None = typer.Option(None, "--thread-id", help="会话 ID（当前仅进程内有效）"),
    debug: bool = typer.Option(
        True,
        "--debug/--no-debug",
        help="开发调试模式；默认开启。终端显示可读轨迹，完整事件写入日志。",
    ),
    log_dir: Path = typer.Option(
        Path("logs"),
        "--log-dir",
        help="完整调试日志目录",
    ),
) -> None:
    thread_id = thread_id or f"cli-{uuid.uuid4().hex[:12]}"

    try:
        asyncio.run(
            _run(
                message=message,
                thread_id=thread_id,
                debug=debug,
                log_dir=log_dir,
            )
        )
    except Exception as exc:
        console.print(f"[red]启动失败：{type(exc).__name__}: {exc}[/red]")
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
