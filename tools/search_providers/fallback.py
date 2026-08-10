"""生产环境主搜索 + 免费降级搜索。"""
from __future__ import annotations

from tools.search_providers.base import (
    SearchDepth,
    SearchProvider,
    SearchProviderError,
    SearchTopic,
)


class FallbackSearchProvider:
    name = "fallback"

    def __init__(self, *, primary: SearchProvider, fallback: SearchProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    def search(
        self,
        *,
        query: str,
        max_results: int,
        topic: SearchTopic,
        search_depth: SearchDepth,
        include_domains: list[str] | None,
    ) -> str:
        primary_error: Exception | None = None

        try:
            result = self._primary.search(
                query=query,
                max_results=max_results,
                topic=topic,
                search_depth=search_depth,
                include_domains=include_domains,
            )
            if result:
                return result
        except Exception as exc:
            primary_error = exc

        try:
            result = self._fallback.search(
                query=query,
                max_results=max_results,
                topic=topic,
                search_depth=search_depth,
                include_domains=include_domains,
            )
            if result:
                return result
        except Exception as fallback_error:
            primary_detail = (
                f"{type(primary_error).__name__}: {primary_error}"
                if primary_error
                else "no results"
            )
            raise SearchProviderError(
                "主搜索和备用搜索均失败："
                f"primary={primary_detail}; "
                f"fallback={type(fallback_error).__name__}: {fallback_error}"
            ) from fallback_error

        if primary_error:
            raise SearchProviderError(
                "主搜索失败，备用搜索也未找到结果："
                f"{type(primary_error).__name__}: {primary_error}"
            ) from primary_error

        return ""
