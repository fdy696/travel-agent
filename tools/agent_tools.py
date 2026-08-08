"""LangChain/Deep Agents 可见的旅游业务工具。

底层 API 实现继续放在 tools.weather / tools.search / tools.route；本模块只负责
把它们包装成有清晰契约的 LangChain Tools，供 Main Agent 与 Travel Researcher SubAgent 自主调用。

原则：Research Tools 只提供外部事实能力；Plan 的确定性状态操作放在 planning/domain_tools.py。
"""
from __future__ import annotations

import asyncio

from langchain_core.tools import tool

from tools.route import get_route as _get_route
from tools.search import SearchDepth, SearchTopic, search_web as _search_web
from tools.weather import get_weather as _get_weather


@tool
async def get_weather(city: str, forecast: bool = False) -> str:
    """查询一个城市的当前天气；forecast=True 时同时返回未来 3 天预报。

    用户问天气、气温、适不适合出行、穿什么衣服时使用。
    仅适合当前/近 3 天天气；更远日期应使用 search_travel_info 查询历史气候或季节特征。

    Args:
        city: 城市名，如 "北京"、"上海"、"丽江"。
        forecast: 是否返回未来 3 天预报；近几天出行时建议 True。
    """
    return await _get_weather(city, forecast)


@tool
async def search_travel_info(
    query: str,
    max_results: int = 5,
    topic: SearchTopic = "general",
    search_depth: SearchDepth = "advanced",
) -> str:
    """联网搜索实时旅游信息。

    需要景点推荐、攻略、美食、门票价格、住宿、营业时间、当地新闻、季节气候、
    出发前注意事项等实时/外部信息时使用。查当地最新动态时用 topic="news"。

    Args:
        query: 具体搜索词，如 "丽江 10月 气候 穿衣"、"大理 三日游 景点 门票"。
        max_results: 返回结果条数。
        topic: general（综合）/ news（新闻）。
        search_depth: basic（快）/ advanced（深）。
    """
    return await asyncio.to_thread(
        _search_web,
        query,
        max_results,
        topic,
        search_depth,
    )


@tool
async def search_maps(origin: str, destination: str, mode: str = "driving") -> str:
    """查询两个地点之间的路线，返回距离、耗时和逐向指引。

    用户问"怎么去、多远、多久、坐什么车"，或规划阶段需要验证地点间交通时使用。

    Args:
        origin: 起点地址，如 "北京西站"。
        destination: 终点地址，如 "北京首都国际机场"。
        mode: driving（驾车）/ transit（公交）。
    """
    return await _get_route(origin, destination, mode)


TRAVEL_TOOLS = [get_weather, search_travel_info, search_maps]
