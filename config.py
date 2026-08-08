"""Application settings loaded from the project-root .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = ".env"


class Settings(BaseSettings):
    APP_NAME: str = "travel-agent"
    APP_DEBUG: bool = True

    # ---- Model ----
    DEEPSEEK_API_KEY: str = ""
    CHAT_MODEL: str = "deepseek-v4-flash"

    # ---- Search (Tavily) ----
    TAVILY_API_KEY: str = ""

    # ---- Weather (QWeather) ----
    QWEATHER_API_KEY: str = ""
    QWEATHER_API_HOST: str = ""

    # ---- Route (AMap) ----
    AMAP_API_KEY: str = ""

    # ---- Conversation Checkpointer (Redis) ----
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_CHECKPOINT_PREFIX: str = "travel-agent:checkpoint"
    REDIS_CHECKPOINT_WRITE_PREFIX: str = "travel-agent:checkpoint_write"
    REDIS_CHECKPOINT_TTL_MINUTES: float | None = None
    REDIS_CHECKPOINT_REFRESH_ON_READ: bool = True

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def require_key(name: str) -> str:
    value = getattr(get_settings(), name)
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}，请在项目根目录 .env 中配置。")
    return value
