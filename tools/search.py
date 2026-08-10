"""联网搜索统一入口。

环境策略：
- development -> DuckDuckGo（免费，不调用 Tavily）
- test        -> FakeSearch（完全离线）
- production  -> Tavily，失败/无结果时 DuckDuckGo fallback

Travel Agent 只看到 search_web / search_travel_info，不感知供应商。
"""
from __future__ import annotations

from functools import lru_cache
from typing import cast

from config import get_settings
from tools.search_providers.base import SearchDepth, SearchProvider, SearchTopic


@lru_cache
def get_search_provider() -> SearchProvider:
    """根据 APP_ENV 构建当前进程唯一的搜索策略。"""
    app_env = get_settings().APP_ENV

    if app_env == "development":
        from tools.search_providers.duckduckgo import DuckDuckGoSearchProvider

        return cast(SearchProvider, DuckDuckGoSearchProvider())

    if app_env == "test":
        from tools.search_providers.fake import FakeSearchProvider

        return cast(SearchProvider, FakeSearchProvider())

    if app_env == "production":
        from tools.search_providers.duckduckgo import DuckDuckGoSearchProvider
        from tools.search_providers.fallback import FallbackSearchProvider
        from tools.search_providers.tavily import TavilySearchProvider

        return cast(
            SearchProvider,
            FallbackSearchProvider(
                primary=TavilySearchProvider(),
                fallback=DuckDuckGoSearchProvider(),
            ),
        )

    # Settings 已用 Literal 校验；这里保留防御式分支。
    raise RuntimeError(f"不支持的 APP_ENV：{app_env}")


def search_web(
    query: str,
    max_results: int = 5,
    topic: SearchTopic = "general",
    search_depth: SearchDepth = "advanced",
    include_domains: list[str] | None = None,
) -> str:
    """执行环境自适应联网搜索，返回标题 + URL + 摘要。"""
    safe_max_results = max(1, min(max_results, 8))
    result = get_search_provider().search(
        query=query,
        max_results=safe_max_results,
        topic=topic,
        search_depth=search_depth,
        include_domains=include_domains,
    )
    return result or "未找到相关搜索结果。"


def current_search_provider_name() -> str:
    """供 CLI / diagnostics 显示当前实际搜索策略，不暴露给模型。"""
    provider = get_search_provider()
    if get_settings().APP_ENV == "production":
        return "tavily → duckduckgo fallback"
    return provider.name
