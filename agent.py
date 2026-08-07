"""主 Agent 构建（v4 / Deep Agents / Week 1）。

Week 1 目标（对应文档第 11 节）：最小 Deep Agent —— 主 Agent + get_weather / search 工具，
通用问答跑通（CLI 模式）。暂不启用：Subagent（规划）、虚拟文件系统、permissions、memory、
interrupt_on、中间件——这些属于 Week 2+。

核心哲学（文档 1.2）：不重新造轮子，把业务逻辑聚焦在 Prompt 和 Tool 契约上。

注意：docstring 就是给 LLM 看的"说明书"——写清楚适用场景与参数含义，
直接决定模型选对工具的概率。
"""
from __future__ import annotations

from deepagents import create_deep_agent
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek

from config import get_settings, require_key
from tools.route import get_route as _get_route
from tools.search import SearchDepth, SearchTopic, search_web as _search_web
from tools.weather import get_weather as _get_weather


# ── 业务工具（@tool 包装底层 API 实现）──────────────────────────────

@tool
async def get_weather(city: str, forecast: bool = False) -> str:
    """查询一个城市的当前天气；forecast=True 时同时返回未来 3 天预报。

    用户问天气、气温、适不适合出行、穿什么衣服时使用。

    Args:
        city: 城市名，如 "北京"、"上海"、"丽江"
        forecast: 是否返回未来 3 天预报（规划行程、决定带什么衣服时建议 True）
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

    需要景点推荐、攻略、美食、门票价格、住宿、当地新闻、出发前注意事项等
    不在知识库里的实时信息时使用；要查当地最新动态、突发新闻时，用 topic="news"。
    默认只在主流旅游站点（携程/马蜂窝/穷游/大众点评/小红书等）内搜索，质量更稳。

    Args:
        query: 搜索词，写具体一些效果更好，如"丽江 3天 旅游攻略"
        max_results: 返回结果条数
        topic: general（综合）/ news（新闻，查当地最新动态时用）
        search_depth: basic（快）/ advanced（深，查详细攻略、价格对比时建议用）
    """
    return _search_web(query, max_results, topic, search_depth)


@tool
async def search_maps(origin: str, destination: str, mode: str = "driving") -> str:
    """查询两个地点之间的路线（驾车或公交），返回距离、耗时和逐向指引。

    用户问"怎么去、多远、多久、坐什么车"时使用。

    Args:
        origin: 起点地址，如 "北京西站"
        destination: 终点地址，如 "北京首都国际机场"
        mode: driving（驾车）/ transit（公交）
    """
    return await _get_route(origin, destination, mode)


TRAVEL_TOOLS = [
    get_weather,
    search_travel_info,
    search_maps,
]


# ── 主 Agent System Prompt（文档第 7 节骨架，裁剪到 Week 1 的通用问答范围）──

TRAVEL_AGENT_SYSTEM_PROMPT = """你是"行伴"旅游助手，一位专业、贴心的旅行规划伙伴。

# 你的能力
- 普通对话：闲聊、旅游建议、常识问答，直接回答即可。
- 查天气：调用 get_weather。用户问天气、气温、适不适合出行时使用。
  若涉及未来几天出行，传 forecast=True 获取预报。
- 查攻略/景点/美食/价格：调用 search_travel_info。需要实时信息时，先联网再回答。
- 查路线/交通：调用 search_maps。用户问"怎么去、多远、多久、坐什么车"时使用。

# 工具使用规则
- 涉及实时、可变的信息（天气、交通、价格、攻略、营业时间），必须先调工具，不要凭记忆编造。
- 一次只问清必要的信息。比如用户没说目的地，先问，再查。
- 简单常识问题直接回答，不必调工具。

# 回复风格
- 简洁、直接、口语化，像朋友聊天，不要罗列晦涩术语。
- 天气、交通信息可能有时效性，回答末尾可提醒用户出发前再确认。
- 不要暴露内部工具名或技术细节。"""


def build_agent():
    """构建主 Deep Agent（进程内懒加载，供 CLI / 后续 API 复用）。

    模型用与现有 backend 一致的 DeepSeek（v4 文档示例为 claude-sonnet-4，
    如需切换改 CHAT_MODEL + 对应 key 即可）。
    """
    llm = ChatDeepSeek(
        model=get_settings().CHAT_MODEL,
        api_key=require_key("DEEPSEEK_API_KEY"),
        temperature=0.3,
        max_retries=3,  # 指数退避重试
    )
    return create_deep_agent(
        model=llm,
        system_prompt=TRAVEL_AGENT_SYSTEM_PROMPT,
        tools=TRAVEL_TOOLS,
        name="travel_agent",
    )
