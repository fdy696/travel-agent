"""Agent-facing tool surfaces。

底层 API 实现继续复用 v6 已有 search.py / weather.py / route.py。
这一层只负责：
- 给模型提供清晰、稳定的 Tool schema；
- 做轻量参数收敛；
- 把外部 API 异常转成模型可理解的失败结果。
"""
from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool

from tools.budget import calculate_budget
from tools.currency import convert_currency
from tools.route import get_route as _get_route
from tools.search import search_web
from tools.weather import get_weather as _get_weather


@tool
async def get_weather(city: str, forecast: bool = False) -> str:
    """查询城市当前天气；规划未来 3 天内行程时可设置 forecast=true 获取 3 天预报。

    对明显超出未来 3 天的旅行日期，不应把当前 3 天预报当成届时天气；应改用
    search_travel_info 查询历史/季节气候，或向用户说明长期天气尚不能可靠预测。
    """
    try:
        return await _get_weather(city=city, forecast=forecast)
    except Exception as exc:  # 外部 API 失败要进入 Agent 上下文，而不是打断整个计划
        return f"天气查询暂时失败：{type(exc).__name__}: {exc}"


@tool
async def search_maps(
    origin: str,
    destination: str,
    mode: Literal["driving", "transit"] = "driving",
) -> str:
    """查询两个地点之间的驾车或公共交通路线、距离与预计耗时。

    当景点之间距离/耗时会影响每日路线是否可执行时使用。
    """
    try:
        return await _get_route(origin=origin, destination=destination, mode=mode)
    except Exception as exc:
        return f"路线查询暂时失败：{type(exc).__name__}: {exc}"


@tool
def search_travel_info(
    query: str,
    max_results: int = 5,
) -> str:
    """联网查询会变化的旅行信息，如景点开放/预约规则、近期攻略、交通政策和推荐。

    query 应尽量具体，包含目的地和需要核实的事实。简单稳定常识不必调用。
    """
    try:
        safe_max_results = max(1, min(max_results, 8))
        return search_web(query=query, max_results=safe_max_results)
    except Exception as exc:
        return f"联网搜索暂时失败：{type(exc).__name__}: {exc}"


TRAVEL_TOOLS = [
    search_travel_info,
    get_weather,
    search_maps,
]

# Main 在 Research 之后可使用确定性预算计算；Researcher 仍只持有 TRAVEL_TOOLS。
MAIN_TOOLS = [
    *TRAVEL_TOOLS,
    calculate_budget,
    convert_currency,
]
