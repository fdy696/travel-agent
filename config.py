"""行伴 v6 全局配置：从项目根目录 .env 读取，lru_cache 做单例。"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = ".env"
AppEnv = Literal["development", "test", "production"]
ModelProviderName = Literal["deepseek", "ollama"]


class Settings(BaseSettings):
    APP_NAME: str = "travel-agent-v6"
    APP_DEBUG: bool = True
    APP_ENV: AppEnv = "development"

    # ---- Agent 执行保护 ----
    # LangGraph recursion_limit：单次执行允许的最大 super-steps。
    # 这是异常循环的最后保险，不替代模型自身的正常停止判断。
    AGENT_RECURSION_LIMIT: PositiveInt = 80

    # ---- 模型 ----
    # 与 APP_ENV 独立：开发环境也可以使用 DeepSeek，生产环境也可以切 Ollama。
    LLM_PROVIDER: ModelProviderName = "deepseek"

    DEEPSEEK_API_KEY: str = ""
    CHAT_MODEL: str = "deepseek-v4-flash"  # DeepSeek 模型名，保留旧配置兼容

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:8b"

    # ---- 免费参考汇率（Frankfurter）----
    FX_BASE_URL: str = "https://api.frankfurter.dev/v2"

    # ---- 生产联网搜索（Tavily）----
    # development 不会调用 Tavily；production 才以 Tavily 为主搜索。
    TAVILY_API_KEY: str = ""

    # ---- 天气（和风天气）----
    QWEATHER_API_KEY: str = ""

    # ---- 路线（高德地图）----
    AMAP_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """读取配置（内存单例）。"""
    return Settings()


def require_key(name: str) -> str:
    """读取一个必须配置的 key，缺失时报出明确错误。"""
    value = getattr(get_settings(), name)
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}，请在仓库根 .env 中配置。")
    return value
