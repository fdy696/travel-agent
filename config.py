"""全局配置：从仓库根目录 .env 读取，lru_cache 做单例。

.env 位置：backend_v4/config.py → 上溯 1 级 = 仓库根（与 backend/app 共用同一个 .env）。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend_v4/config.py → parents[1] = 仓库根
ENV_FILE = ".env"


class Settings(BaseSettings):
    APP_NAME: str = "travel-agent-v4"
    APP_DEBUG: bool = True

    # ---- 模型 ----
    DEEPSEEK_API_KEY: str = ""
    CHAT_MODEL: str = "deepseek-v4-flash"

    # ---- 联网搜索（Tavily）----
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
