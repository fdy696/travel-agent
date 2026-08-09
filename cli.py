"""行伴开发 CLI。

默认开启开发调试模式，但终端只展示高可读执行轨迹；Deep Agents / LangGraph
暴露的完整 updates、debug、subgraph 事件写入日志文件，避免原始 payload 淹没终端。

说明：日志只记录框架实际暴露的事件，不尝试记录模型隐藏的 chain-of-thought。
"""
from __future__ import annotations

import asyncio
import pprint
import sys
import time
import traceback
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import typer
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
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
_SECRET_KEYWORDS = ("api_key", "apikey", "authorization", "password", "secret", "access_token")


class DebugLog:
    """把完整框架事件持续写入开发日志。"""

    def __init__(self, *, thread_id: str, enabled: bool, log_dir: Path) -> None:
        self.enabled = enabled
        self.path: Path | None = None
        self._fp: TextIO | None = None

        if not enabled:
            return

        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = (log_dir / f"travel-agent-{stamp}-{thread_id}.log").resolve()
        self._fp = self.path.open("a", encoding="utf-8")
        self.write_text(
            "SESSION START",
            f"thread_id={thread_id}\ncreated_at={datetime.now().isoformat(timespec='seconds')}",
        )

    def write_text(self, title: str, text: str) -> None:
        if self._fp is None:
            return
        self._fp.write(f"\n{'=' * 32} {title} {'=' * 32}\n")
        self._fp.write(text)
        if not text.endswith("\n"):
            self._fp.write("\n")
        self._fp.flush()

    def write_event(self, chunk: Any) -> None:
        if self._fp is None:
            return

        mode = chunk.get("type") if isinstance(chunk, Mapping) else type(chunk).__name__
        namespace = tuple(chunk.get("ns") or ()) if isinstance(chunk, Mapping) else ()
        title = f"STREAM mode={mode} namespace={namespace or ('MAIN',)}"
        rendered = pprint.pformat(
            _redact(chunk),
            width=180,
            depth=None,
            compact=False,
            sort_dicts=False,
        )
        self.write_text(title, rendered)

    def write_exception(self, exc: BaseException) -> None:
        self.write_text(
            f"EXCEPTION {type(exc).__name__}",
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )

    def close(self) -> None:
        if self._fp is None:
            return
        self.write_text("SESSION END", datetime.now().isoformat(timespec="seconds"))
        self._fp.close()
        self._fp = None


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _content_to_text(content: Any) -> str:
    """兼容 str 和 content-block 两种 Message.content。"""
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


def _redact(value: Any) -> Any:
    """写日志前隐藏常见密钥字段。"""
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(keyword in key_text for keyword in _SECRET_KEYWORDS):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def _namespace_label(namespace: Iterable[str] | None) -> str:
    return "SUB" if tuple(namespace or ()) else "MAIN"


def _iter_messages(value: Any) -> list[BaseMessage]:
    if isinstance(value, BaseMessage):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, BaseMessage)]
    return []


def _tool_call_fields(call: Any) -> tuple[str, Any]:
    if isinstance(call, Mapping):
        return str(call.get("name") or "<unknown>"), call.get("args") or {}
    return str(getattr(call, "name", "<unknown>")), getattr(call, "args", {})


def _short(text: str, limit: int = 110) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _elapsed_text(started_at: float) -> str:
    return f"{time.perf_counter() - started_at:6.1f}s"


def _trace(source: str, action: str, detail: str = "", *, started_at: float) -> None:
    prefix = f"[{_elapsed_text(started_at)}] [{source:<4}]"
    if detail:
        console.print(f"{prefix} {action:<10} {detail}", markup=False)
    else:
        console.print(f"{prefix} {action}", markup=False)


def _tool_detail(name: str, args: Any) -> str:
    if not isinstance(args, Mapping):
        return name

    if name == "read_file":
        path = str(args.get("file_path") or "")
        if path.endswith("/SKILL.md") and "/skills/" in path:
            skill_name = Path(path).parent.name
            return f"Skill: {skill_name}"
        if path.endswith("markdown-contract.md"):
            return "Contract: markdown-contract"
        return _short(path or name)

    if name == "search_travel_info":
        query = args.get("query") or args.get("queries")
        return _short(str(query or name))

    if name == "search_maps":
        return _short(str(args.get("query") or args.get("keyword") or args))

    if name == "get_weather":
        return _short(str(args.get("location") or args.get("city") or args))

    return _short(str(args)) if args else name


def _render_tool_call(call: Any, *, source: str, started_at: float) -> None:
    name, args = _tool_call_fields(call)

    if name == "task":
        subagent_type = "general-purpose"
        description = ""
        if isinstance(args, Mapping):
            subagent_type = str(args.get("subagent_type") or subagent_type)
            description = str(args.get("description") or "")
        _trace(source, "Delegate →", subagent_type, started_at=started_at)
        if description:
            _trace(source, "Brief", _short(description, 140), started_at=started_at)
        return

    detail = _tool_detail(name, args)
    if name == "read_file" and detail.startswith("Skill:"):
        _trace(source, "Load", detail, started_at=started_at)
    elif name == "read_file" and detail.startswith("Contract:"):
        _trace(source, "Load", detail, started_at=started_at)
    else:
        _trace(source, "Tool →", f"{name}  {detail}", started_at=started_at)


def _tool_failed(message: ToolMessage) -> bool:
    status = str(getattr(message, "status", "") or "").lower()
    if status in {"error", "failed", "failure"}:
        return True
    content = _content_to_text(message.content).lower()
    return content.startswith("error:") or "traceback (most recent call last)" in content


def _render_update(chunk: Mapping[str, Any], *, started_at: float) -> str | None:
    """终端只从 updates 提炼高可读轨迹；原始细节已写日志。"""
    namespace = tuple(chunk.get("ns") or ())
    source = _namespace_label(namespace)
    data = chunk.get("data")
    latest_answer: str | None = None

    if not isinstance(data, Mapping):
        return None

    for node_name, update in data.items():
        if not isinstance(update, Mapping):
            continue

        for message in _iter_messages(update.get("messages")):
            if isinstance(message, AIMessage):
                text = _content_to_text(message.content)
                tool_calls = list(getattr(message, "tool_calls", None) or [])

                for call in tool_calls:
                    _render_tool_call(call, source=source, started_at=started_at)

                if source == "MAIN" and text and not tool_calls:
                    latest_answer = text
                    _trace("MAIN", "Synthesis", "final answer ready", started_at=started_at)

            elif isinstance(message, ToolMessage):
                tool_name = str(getattr(message, "name", None) or "<unknown>")
                if _tool_failed(message):
                    detail = _short(_content_to_text(message.content), 160)
                    _trace(source, "Tool ✗", f"{tool_name}  {detail}", started_at=started_at)
                elif tool_name == "task":
                    _trace("MAIN", "Return ←", "general-purpose", started_at=started_at)

    return latest_answer


async def _answer_from_state(agent, *, thread_id: str) -> str:
    """Streaming 未捕获最终正文时，从 checkpoint 读取，不触发二次模型调用。"""
    try:
        snapshot = await agent.aget_state(_config(thread_id))
    except Exception:
        return ""

    values = getattr(snapshot, "values", None) or {}
    if not isinstance(values, Mapping):
        return ""
    messages = values.get("messages") or []
    if not messages:
        return ""
    return _content_to_text(messages[-1].content)


async def ask(
    agent,
    question: str,
    *,
    thread_id: str,
    debug: bool,
    debug_log: DebugLog,
) -> str:
    """提交本轮 user message；历史由 checkpointer 根据 thread_id 恢复。"""
    inputs = {"messages": [{"role": "user", "content": question}]}
    config = _config(thread_id)

    if not debug:
        result = await agent.ainvoke(inputs, config=config)
        messages = result.get("messages") or []
        if not messages:
            return ""
        return _content_to_text(messages[-1].content)

    started_at = time.perf_counter()
    debug_log.write_text("USER INPUT", question)
    _trace("MAIN", "Start", _short(question, 120), started_at=started_at)

    final_answer = ""
    try:
        async for chunk in agent.astream(
            inputs,
            config=config,
            stream_mode=["updates", "debug"],
            subgraphs=True,
            version="v2",
        ):
            # 完整原始事件先落盘，再做终端摘要。
            debug_log.write_event(chunk)

            if not isinstance(chunk, Mapping):
                continue

            if chunk.get("type") == "updates":
                answer = _render_update(chunk, started_at=started_at)
                if answer is not None:
                    final_answer = answer
    except Exception as exc:
        debug_log.write_exception(exc)
        _trace("MAIN", "Error", f"{type(exc).__name__}: {exc}", started_at=started_at)
        raise

    if not final_answer:
        final_answer = await _answer_from_state(agent, thread_id=thread_id)

    elapsed = time.perf_counter() - started_at
    debug_log.write_text("FINAL ANSWER", final_answer)
    debug_log.write_text("TURN COMPLETE", f"elapsed={elapsed:.3f}s")
    _trace("MAIN", "Done", f"{elapsed:.1f}s", started_at=started_at)
    return final_answer


async def _repl(agent, *, thread_id: str, debug: bool, debug_log: DebugLog) -> None:
    console.print("[bold]行伴 Travel Agent[/bold]")
    console.print(f"会话：{thread_id}", markup=False)
    if debug:
        console.print("开发调试：开启（终端简洁轨迹，完整事件写入日志）", markup=False)
        if debug_log.path:
            console.print(f"详细日志：{debug_log.path}", markup=False)
    else:
        console.print("开发调试：关闭", markup=False)
    console.print("输入 /quit 退出。\n")

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
                debug_log=debug_log,
            )
        except Exception as exc:
            console.print(f"[red]运行失败：{type(exc).__name__}: {exc}[/red]")
            if debug_log.path:
                console.print(f"完整异常见：{debug_log.path}", markup=False)
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
    debug_log = DebugLog(thread_id=thread_id, enabled=debug, log_dir=log_dir)

    try:
        if message:
            if debug and debug_log.path:
                console.print(f"详细日志：{debug_log.path}", markup=False)
            answer = await ask(
                agent,
                message,
                thread_id=thread_id,
                debug=debug,
                debug_log=debug_log,
            )
            console.print("\n[bold]行伴：[/bold]")
            console.print(Markdown(answer) if answer else "")
            return

        await _repl(agent, thread_id=thread_id, debug=debug, debug_log=debug_log)
    finally:
        debug_log.close()


@app.callback(invoke_without_command=True)
def main(
    message: str | None = typer.Option(None, "--message", "-m", help="单次问答 / 规划"),
    thread_id: str | None = typer.Option(None, "--thread-id", help="会话 ID（当前仅进程内有效）"),
    debug: bool = typer.Option(
        True,
        "--debug/--no-debug",
        help="默认开启：终端显示简洁执行轨迹，完整框架事件写入日志。",
    ),
    log_dir: Path = typer.Option(
        Path("logs"),
        "--log-dir",
        help="详细调试日志目录。",
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
