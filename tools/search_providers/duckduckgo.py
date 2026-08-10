"""DuckDuckGo 免费本地开发搜索 Provider。"""
from __future__ import annotations

from ddgs import DDGS
from ddgs.exceptions import DDGSException

from tools.search_providers.base import SearchDepth, SearchTopic

# 备用 backend：auto 会依次尝试 wikipedia/google/brave 等多个引擎，最稳；
# 偶发限流/空结果时再退到 html 端点重试一次。
_FALLBACK_BACKENDS = ("auto", "html")


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def search(
        self,
        *,
        query: str,
        max_results: int,
        topic: SearchTopic,
        search_depth: SearchDepth,
        include_domains: list[str] | None,
    ) -> str:
        # DDGS 没有 Tavily 的 include_domains 参数；显式传入域名时用 site: 语法收敛。
        effective_query = query
        if include_domains:
            site_filter = " OR ".join(f"site:{domain}" for domain in include_domains)
            effective_query = f"{query} ({site_filter})"

        ddgs = DDGS(timeout=10)
        results: list[dict] = []
        for backend in _FALLBACK_BACKENDS:
            try:
                results = ddgs.text(
                    effective_query,
                    max_results=max_results,
                    backend=backend,
                ) or []
            except DDGSException:
                continue  # 该 backend 失败/被限流，换下一个。
            if results:
                break
        if not results:
            return ""

        lines: list[str] = []
        for index, result in enumerate(results, 1):
            lines.append(
                f"{index}. {result.get('title', '')}\n"
                f" URL: {result.get('href', '')}\n"
                f" {result.get('body', '')}"
            )
        return "\n\n".join(lines)
