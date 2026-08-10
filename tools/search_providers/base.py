"""统一搜索 Provider 协议。"""
from __future__ import annotations

from typing import Literal, Protocol


SearchTopic = Literal["general", "news", "finance"]
SearchDepth = Literal["basic", "advanced"]


class SearchProvider(Protocol):
    """统一搜索能力；Agent 不感知具体供应商。"""

    name: str

    def search(
        self,
        *,
        query: str,
        max_results: int,
        topic: SearchTopic,
        search_depth: SearchDepth,
        include_domains: list[str] | None,
    ) -> str:
        """返回格式化后的标题 + URL + 摘要；无结果时返回空字符串。"""
        ...


class SearchProviderError(RuntimeError):
    """所有可用搜索 Provider 都失败。"""
