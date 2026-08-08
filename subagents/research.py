"""只读 Travel Researcher SubAgent。

它不是第二个业务 Agent，只负责把高输出量 Research 隔离在 child context 中。
Main Agent 根据 subagent description 自主决定是否委派。
"""
from __future__ import annotations

from deepagents.middleware.subagents import SubAgent

from tools.agent_tools import get_weather, search_maps, search_travel_info


TRAVEL_RESEARCH_SYSTEM_PROMPT = """你是 Travel Researcher，只负责旅游事实研究。

你的任务是为父 Agent 收集当前、可验证、对旅行决策有用的事实，并把大量中间 Tool Results 留在自己的隔离 context 中。

工作原则：
1. 根据委派任务自主使用 search_travel_info / get_weather / search_maps。
2. 实时、可变化的信息必须通过工具核实；无法核实就明确标注不确定性。
3. 不创建、不修改、不保存旅行 Plan。
4. 不修改用户 Requirements，不做任何业务状态写入。
5. 不向用户追问。上下文不足时，在 Research Brief 中说明缺口。
6. 不输出原始搜索结果堆积，不写完整旅行计划。
7. 最终只返回一份简洁但信息充分的 Markdown Research Brief，供父 Agent继续规划。

推荐结构（按实际任务裁剪，不要机械凑章节）：
# Research Brief
## Weather / Season
## Transport / Route
## Attractions & Booking
## Accommodation Areas
## Practical Constraints
## Risks / Uncertainty
"""


def build_travel_researcher() -> SubAgent:
    return {
        "name": "travel-researcher",
        "description": (
            "Use for substantial multi-source travel research when search, weather, or map "
            "investigation would produce large intermediate tool output in the main context. "
            "Return only a concise factual research brief. Do not use for simple one-off lookups."
        ),
        "system_prompt": TRAVEL_RESEARCH_SYSTEM_PROMPT,
        "tools": [
            search_travel_info,
            get_weather,
            search_maps,
        ],
        # Research worker 不需要加载 planning Skill，保持 child context 最小。
        "skills": [],
    }
