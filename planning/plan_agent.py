"""Declarative Travel Plan SubAgent。

不再使用自定义 Planning Workflow：Agent 自主决定 Research/Tool 调用路径，
Domain Tools 负责 Requirements / Plan 的确定性边界。
"""
from __future__ import annotations

from deepagents.middleware.subagents import SubAgent

from planning.domain_tools import PlanDomainTools
from tools.agent_tools import TRAVEL_TOOLS


TRAVEL_PLAN_SYSTEM_PROMPT = """你是 Travel Plan Agent，只负责会改变旅行计划的任务：
创建、修改、延长、缩短、换目的地、重排行程、重新规划。

你的工作方式是 Agent Loop，而不是固定状态机：先理解任务，再按需收集上下文、调用工具、
研究事实、形成完整 Plan，最后通过 Domain Tool 提交。

必须遵守：
1. 开始工作时使用 travel-planning Skill，并遵循其中的 create / modify playbook。
2. 新建/重新规划先用 update_requirements 外部化需求；缺阻塞字段就直接向用户追问，不 Research、不提交 Plan。
3. 修改现有 Plan 前必须 get_current_plan；不要从聊天历史重建 canonical Plan。
4. 实时/可变事实（天气、价格、营业时间、交通等）需要时使用 research tools；是否 Research、查几次由你根据任务判断，不靠关键词表。
5. 最终只通过 create_plan / update_plan 提交系统 Plan。不要声称保存成功，除非 Tool 返回 SUCCESS。
6. create_plan/update_plan 若返回 PLAN_SCHEMA_INVALID，只修 Schema/格式问题后最多重试一次；不要启动业务 Repair Loop。
7. Tool 成功后，把 <final_markdown> 与 </final_markdown> 之间的内容原样作为最终回答，不概括、不改写。
8. 不暴露 user_id、session_id、plan_id、内部工具名等技术细节。
"""


def build_travel_plan_subagent(*, domain_tools: PlanDomainTools) -> SubAgent:
    return {
        "name": "travel-planning",
        "description": (
            "Create or mutate the user's current multi-day travel plan. "
            "Use for new itinerary creation, replanning, extending/shortening, "
            "changing destinations, deleting/adding/rearranging activities, budget/pace/hotel changes. "
            "Do not use for ordinary travel Q&A or simple questions about an already visible plan."
        ),
        "system_prompt": TRAVEL_PLAN_SYSTEM_PROMPT,
        "tools": [
            *TRAVEL_TOOLS,
            domain_tools.update_requirements,
            domain_tools.get_current_plan,
            domain_tools.create_plan,
            domain_tools.update_plan,
        ],
        "skills": ["/skills/"],
    }
