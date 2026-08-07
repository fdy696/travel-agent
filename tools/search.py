"""联网搜索工具（Tavily）。用于攻略 / 景点 / 美食 / 交通等实时信息。"""
from typing import Literal

from tavily import TavilyClient

from config import require_key

SearchTopic = Literal["general", "news", "finance"]
SearchDepth = Literal["basic", "advanced"]

# 旅游内容站白名单：攻略 / 门票 / 住宿等垂直信息源，优先在这里搜（无结果自动回退全网）
TRAVEL_SITES = [
    "ctrip.com",       # 携程
    "qunar.com",       # 去哪儿
    "mafengwo.cn",     # 马蜂窝
    "qyer.com",        # 穷游
    "dianping.com",    # 大众点评
    "xiaohongshu.com", # 小红书
]

_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    """懒加载单例客户端（避免每次调用重建）。"""
    global _client
    if _client is None:
        _client = TavilyClient(api_key=require_key("TAVILY_API_KEY"))
    return _client


def search_web(
    query: str,
    max_results: int = 5,
    topic: SearchTopic = "general",
    search_depth: SearchDepth = "advanced",
    include_domains: list[str] | None = None,
) -> str:
    """联网搜索，返回格式化结果文本（标题 + URL + 摘要）。

    默认在旅游站白名单（TRAVEL_SITES）内搜索，白名单无结果时自动回退全网。

    Args:
        query: 搜索词，如 "北京 3天 亲子游 攻略"
        max_results: 返回条数
        topic: general / news / finance
        search_depth: basic（快）/ advanced（深）
        include_domains: 自定义域名白名单；None 时用默认旅游站白名单
    """
    client = _get_client()

    def _do_search(domains: list[str] | None) -> list[dict]:
        resp = client.search(
            query=query,
            max_results=max_results,
            topic=topic,
            search_depth=search_depth,
            include_domains=domains,
        )
        return resp.get("results") or []

    results = _do_search(include_domains if include_domains is not None else TRAVEL_SITES)
    if not results:
        results = _do_search(None)  # 白名单无结果 → 全网回退

    if not results:
        return "未找到相关搜索结果。"

    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r.get('title', '')}\n"
            f"   URL: {r.get('url', '')}\n"
            f"   {r.get('content', '')}"
        )
    return "\n\n".join(lines)
