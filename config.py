"""行伴 v6 全局配置：从项目根目录 .env 读取，lru_cache 做单例。"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = ".env"


class Settings(BaseSettings):
    APP_NAME: str = "travel-agent-v6"
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
