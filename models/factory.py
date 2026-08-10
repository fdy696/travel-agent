"""Chat model provider factory.

LLM provider 与 APP_ENV 独立：
- LLM_PROVIDER 决定模型供应商；
- APP_ENV 决定搜索 / 测试等基础设施策略。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from config import get_settings, require_key


def build_chat_model() -> BaseChatModel:
    """按 LLM_PROVIDER 构造当前进程使用的聊天模型。"""
    settings = get_settings()

    if settings.LLM_PROVIDER == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            model=settings.CHAT_MODEL,
            api_key=require_key("DEEPSEEK_API_KEY"),
            temperature=0.3,
            max_tokens=32000,
            max_retries=3,
            extra_body={"thinking": {"type": "disabled"}},
        )

    if settings.LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.OLLAMA_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=0.3,
        )

    raise RuntimeError(f"不支持的 LLM_PROVIDER：{settings.LLM_PROVIDER}")


def current_model_provider_name() -> str:
    """返回 CLI / diagnostics 使用的模型标签。"""
    settings = get_settings()
    if settings.LLM_PROVIDER == "deepseek":
        return f"deepseek:{settings.CHAT_MODEL}"
    return f"ollama:{settings.OLLAMA_MODEL}"
