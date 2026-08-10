"""Tavily 生产搜索 Provider。"""
from __future__ import annotations

from tavily import TavilyClient

from config import require_key
from tools.search_providers.base import SearchDepth, SearchTopic


TRAVEL_SITES = [
    "ctrip.com",
    "qunar.com",
    "mafengwo.cn",
    "qyer.com",
    "dianping.com",
    "xiaohongshu.com",
]


class TavilySearchProvider:
    name = "tavily"

    def __init__(self) -> None:
        self._client: TavilyClient | None = None

    def _get_client(self) -> TavilyClient:
        if self._client is None:
            self._client = TavilyClient(api_key=require_key("TAVILY_API_KEY"))
        return self._client

    def search(
        self,
        *,
        query: str,
        max_results: int,
        topic: SearchTopic,
        search_depth: SearchDepth,
        include_domains: list[str] | None,
    ) -> str:
        client = self._get_client()

        def _do_search(domains: list[str] | None) -> list[dict]:
            response = client.search(
                query=query,
                max_results=max_results,
                topic=topic,
                search_depth=search_depth,
                include_domains=domains,
            )
            return response.get("results") or []

        # 保留 GitHub 当前 v6 行为：未显式传域名时先搜旅游垂直站，无结果再回退全网。
        results = _do_search(
            include_domains if include_domains is not None else TRAVEL_SITES
        )
        if not results:
            results = _do_search(None)
        if not results:
            return ""

        lines: list[str] = []
        for index, result in enumerate(results, 1):
            lines.append(
                f"{index}. {result.get('title', '')}\n"
                f" URL: {result.get('url', '')}\n"
                f" {result.get('content', '')}"
            )
        return "\n\n".join(lines)
