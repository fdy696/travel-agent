"""v4 Week 1 CLI：通用问答交互入口（REPL / 单次问答）。

用法（在 backend_v4 目录下）：
  uv run python -m cli                            # 交互式 REPL
  uv run python -m cli --message "北京天气怎么样"    # 单次问答（供冒烟测试）

交互命令：
  - 直接输入问题 → 得到回答
  - 输入 /quit /exit /q 或 退出 → 结束

实现基于 typer + rich（不手写 CLI）：参数解析交给 typer，输出交给 rich。
编码兜底：把 stdout/stderr 重配置为 UTF-8 + errors="replace"，LLM 回复里偶发的
非法字符（孤立代理项/emoji）会被安全替换为 "?"，而不是抛 UnicodeEncodeError 崩溃。
"""
from __future__ import annotations

import asyncio
import sys

import typer
from rich.console import Console
from rich.prompt import Prompt

from agent import build_agent

# Windows 控制台默认 GBK；统一重配置为 UTF-8，非法字符替换为 "?" 而非崩溃
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # 非 TTY / 已配置时跳过

app = typer.Typer(
    name="travel-agent",
    help="行伴旅游助手（v4 / Deep Agents / Week 1）",
    no_args_is_help=False,
)
console = Console()

QUIT_WORDS = ("/quit", "/exit", "/q", "退出")


def _clean(text: str) -> str:
    """剔除字符串里的孤立代理项，避免 utf-8 严格编码时抛 UnicodeEncodeError。

    LLM 回复里偶发的 emoji 在管线里可能被解码成代理项；若某个代理项被截断成
    孤立半段（如 \\udc80），任何 utf-8 严格编码都会报 "surrogates not allowed"。
    这里先把整串按 utf-8（errors=replace）编码再解码回来，把坏字符替换成 "?"，
    保证后续打印永不崩溃（rich 内部编码路径不一定继承 stdout 的 errors="replace"）。
    """
    if not isinstance(text, str):
        return str(text)
    return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _error(msg: str) -> None:
    """红色错误提示；动态内容走 markup=False，避免回复里的 [ ] 被误当标记。"""
    console.print("[red][错误][/red]", end=" ")
    console.print(msg, markup=False)


async def ask(agent, question: str) -> str:
    """单轮问答。"""
    result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})
    return _clean(result["messages"][-1].content)


@app.callback(invoke_without_command=True)
def main(
    message: str = typer.Option(None, "--message", "-m", help="单次问答，不进入交互模式"),
) -> None:
    """不带参数进入交互 REPL，带 --message 做单次问答。"""
    try:
        agent = build_agent()
    except Exception as e:
        _error(f"初始化失败：{type(e).__name__}: {e}")
        raise typer.Exit(1)

    if message:
        try:
            reply = asyncio.run(ask(agent, message))
        except Exception as e:
            _error(f"{type(e).__name__}: {e}")
            raise typer.Exit(1)
        console.print(reply, markup=False)
        return

    asyncio.run(_repl(agent))


async def _repl(agent) -> None:
    console.print("[bold]行伴旅游助手（v4 / Deep Agents / Week 1）[/bold]")
    console.print("输入问题开始对话；输入 /quit 退出。\n")
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
            reply = await ask(agent, user_input)
        except Exception as e:
            _error(f"{type(e).__name__}: {e}")
            console.print()
            continue
        console.print("[bold]助手：[/bold]")
        console.print(reply, markup=False)
        console.print()


if __name__ == "__main__":
    app()
