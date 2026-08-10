"""测试环境离线 Fake Search Provider。"""
from __future__ import annotations

from tools.search_providers.base import SearchDepth, SearchTopic


class FakeSearchProvider:
    name = "fake"

    def search(
        self,
        *,
        query: str,
        max_results: int,
        topic: SearchTopic,
        search_depth: SearchDepth,
        include_domains: list[str] | None,
    ) -> str:
        # 确保自动化测试不依赖公网、DuckDuckGo 或 Tavily。
        return (
            "1. [FAKE SEARCH RESULT]\n"
            " URL: https://example.test/search\n"
            f" Test-only deterministic result for query: {query}"
        )
