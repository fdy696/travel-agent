"""Planning Workflow 中需要 LLM/Agent 判断的部分。

确定性状态推进仍在 workflow.py；本模块只处理自然语言抽取、研究、生成和格式修复。
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from planning.llm_json import invoke_json, parse_model, schema_text, structured_generate
from planning.models import (
    PlanDraft,
    RequirementsPatch,
    TravelRequirements,
)
from tools.agent_tools import TRAVEL_TOOLS


class PlanningIntelligence(Protocol):
    async def extract_requirements(
        self,
        *,
        user_text: str,
        current: TravelRequirements,
    ) -> RequirementsPatch: ...

    async def research(self, requirements: TravelRequirements) -> str: ...

    async def generate_plan(
        self,
        *,
        requirements: TravelRequirements,
        research: str,
    ) -> PlanDraft: ...

    async def generate_modification(
        self,
        *,
        current: PlanDraft,
        instruction: str,
        research: str,
    ) -> PlanDraft: ...


class LLMPlanningIntelligence:
    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self._requirements_model = llm.with_structured_output(
            RequirementsPatch,
            method="json_mode",
        )
        self._plan_model = llm.with_structured_output(
            PlanDraft,
            method="json_mode",
        )
        # schema 在 __init__ 序列化一次，避免每次调用重复 model_json_schema()。
        self._requirements_schema = schema_text(RequirementsPatch)
        self._plan_schema = schema_text(PlanDraft)
        # Research Agent 先以普通文本完成工具调用和报告撰写；最终计划仍使用结构化输出。
        self._research_agent = create_agent(
            model=llm,
            tools=TRAVEL_TOOLS,
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            name="travel-planning-research",
        )

    async def extract_requirements(
        self,
        *,
        user_text: str,
        current: TravelRequirements,
    ) -> RequirementsPatch:
        today = datetime.now().date().isoformat()
        result = await invoke_json(
            self._requirements_model,
            [
                SystemMessage(
                    content=(
                        "你负责从旅游规划对话中抽取本轮新增或修改的需求。"
                        "必须只返回合法 JSON 对象，不要返回 Markdown 或解释。"
                        "只输出用户本轮明确表达或可直接推导的信息，不猜测高影响事实。"
                        "对于 destinations/must_visit/exclude，如果本轮涉及这些字段，"
                        "输出应用本轮修改后的完整列表；未涉及则保持 null。"
                        "住宿倾向（如‘靠近老门东，方便逛吃夜景’）填 accommodation_preference。"
                        "相对日期必须结合今天解释。JSON 示例："
                        '{"origin":null,"destinations":["云南"],"duration_days":5,'
                        '"traveler_count":2,"budget_per_person_cny":null,"pace":"comfortable",'
                        '"accommodation_preference":null}'
                    )
                ),
                HumanMessage(
                    content=(
                        f"今天是 {today}。\n"
                        f"已有需求：{current.model_dump_json()}\n"
                        f"用户本轮输入：{user_text}\n"
                        f"请按此 JSON Schema 输出：{self._requirements_schema}"
                    )
                ),
            ],
        )
        return parse_model(result, RequirementsPatch)

    async def research(self, requirements: TravelRequirements) -> str:
        try:
            result = await self._research_agent.ainvoke(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                "为下面这次旅行规划做事实研究，并输出 Markdown 研究报告。\n"
                                f"requirements={requirements.model_dump_json()}\n"
                                "重点收集：适合季节/天气、核心景点与开放/门票信息、"
                                "城市间/景点间交通、住宿区域、美食与明显风险。"
                                "如果出行日期不在天气 API 近 3 天范围内，不要拿当前天气冒充未来天气，"
                                "应使用联网搜索获取季节气候信息。"
                                "报告应包含来源线索或搜索结论，方便后续生成计划时追溯。"
                            )
                        )
                    ]
                }
            )
            report = _last_text(result.get("messages", []))
            if not report:
                raise RuntimeError("research agent 返回空 content")
            return report
        except Exception as exc:
            raise RuntimeError(f"research failed: {exc}") from exc

    async def generate_plan(
        self,
        *,
        requirements: TravelRequirements,
        research: str,
    ) -> PlanDraft:
        """生成计划：Schema Parse，失败时 Format Repair 一次。"""
        return await structured_generate(
            self._plan_model,
            model_type=PlanDraft,
            schema=self._plan_schema,
            system=PLAN_GENERATION_SYSTEM_PROMPT,
            user=(
                "根据以下已确认需求和研究信息生成完整结构化行程。\n"
                f"requirements={requirements.model_dump_json()}\n"
                f"research={research}\n"
                f"请按此 JSON Schema 输出：{self._plan_schema}"
            ),
            repair_context=(
                f"requirements={requirements.model_dump_json()}\n"
                f"research={research}"
            ),
        )

    async def generate_modification(
        self,
        *,
        current: PlanDraft,
        instruction: str,
        research: str,
    ) -> PlanDraft:
        """基于当前行程和修改指令生成修改后的完整行程；research 可为空字符串。"""
        return await structured_generate(
            self._plan_model,
            model_type=PlanDraft,
            schema=self._plan_schema,
            system=PLAN_MODIFICATION_SYSTEM_PROMPT,
            user=(
                "根据当前行程、修改指令和补充研究信息，生成修改后的完整结构化行程。\n"
                f"当前行程：{current.model_dump_json()}\n"
                f"修改指令：{instruction}\n"
                f"补充研究：{research or '无'}\n"
                f"请按此 JSON Schema 输出：{self._plan_schema}"
            ),
            repair_context=(
                f"当前行程：{current.model_dump_json()}\n"
                f"修改指令：{instruction}"
            ),
        )


def _last_text(messages: list[object]) -> str:
    for message in reversed(messages):
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            return content
    return ""


RESEARCH_SYSTEM_PROMPT = """你是旅游行程规划的 Research Agent。

你只负责收集和整理规划所需事实，不生成最终行程，也不要输出 JSON。
可使用天气、联网搜索和地图路线工具；需要时允许多轮调用工具。

边界处理：
- 实时/可变事实必须来自工具结果，不要凭记忆编造。
- 天气 API 只用于当前/近 3 天；更远日期查询季节气候资料。
- 单个来源失败时记录在普通文本报告的“部分失败”段落，不要假装成功。
- 报告应包含来源线索或搜索结论，方便后续生成计划时追溯。
- 工具返回空结果、超时或鉴权失败时，保留已获得信息并明确标注，不要因此编造结论。"""


PLAN_GENERATION_SYSTEM_PROMPT = """你是专业旅游攻略生成器。

你不是在生成一个简短的 itinerary summary，而是在生成一份可以直接交付给游客
使用的完整旅行攻略。必须只返回合法 JSON 对象，不要返回 Markdown 或解释。

JSON 示例：
{"title":"大理—丽江3日经典游","subtitle":"8月 · 2人 · 人均3000元","requirements":{},"overview":"","weather_summary":"","weather_details":[],"weather_tip":"","schedule":[],"transportation_guide":[],"food_recommendations":[],"food_route":[],"attraction_guides":[],"accommodation_recommendations":[],"budget_breakdown":[],"budget_total":"","booking_tips":[],"transportation_tips":[],"clothing_tips":[],"photo_tips":[],"budget_tips":[],"warnings":[]}

输入：
- requirements：已确认的出行需求 JSON
- research：完整研究报告（Markdown），可能包含大量景点、美食、天气、交通、预约、风险细节

Plan 必须同时覆盖以下 14 项，缺一不可：

1. 出行基础信息（时间/人数/预算/偏好/住宿偏好）
2. 天气与季节建议（按月参考 + 携带提醒）
3. 每日详细行程（时间、去哪、做什么）
4. 每段活动的具体游览路线（怎么走）
5. 推荐打卡点 / 看什么
6. 交通方式与耗时
7. 景点门票、开放、预约信息
8. 核心景点深度攻略（历史背景、看点、拍照位置、避坑、替代方案）
9. 美食与餐厅推荐（按地区/分类，含推荐菜、价格、位置、推荐理由）
10. 住宿区域与住宿建议（区域、酒店、参考价格、为什么推荐）
11. 预算参考（分项 + 总计）
12. 拍照建议
13. 穿搭和出行准备
14. 风险、避坑与备选方案

约束：
- schedule 天数必须等于 requirements.duration_days。
- 跨城市移动：既要写进当天活动，也要在 transportation_guide 单独给完整说明
  （方式/用时/价格/出发到达站/班次建议）。
- 必须覆盖 must_visit，绝不安排 exclude。
- 不要把出发地凭空补成某个城市；origin 为空时按“当地行程”处理。
- ID 字段可以留空，系统会在生成后统一分配稳定 ID。
- requirements 字段原样反映已确认需求，不自行修改。

Research 中与用户实际旅行决策相关的重要信息，应尽可能进入最终 Plan。
不要仅仅生成“上午去哪、下午去哪”的时间表；不要为了简洁而删除有实际价值的信息；
没有可靠信息时允许字段为空或空列表，不要为了填充 Schema 编造事实。
费用一律用文字描述（如“约90元”“免费”“1.5-3.5元/个”），不要用数字。
请按输入中给出的 JSON Schema 输出。"""


PLAN_FORMAT_REPAIR_SYSTEM_PROMPT = """你是 JSON 格式修复器。

上一次模型输出无法解析为符合目标 Schema 的 JSON。请只修正格式问题
（字段名、类型、缺失必填项、非法枚举等），把内容整理成一份严格符合
给定 JSON Schema 的完整 JSON 对象，不要改变行程的语义内容。"""


PLAN_MODIFICATION_SYSTEM_PROMPT = """你是专业旅游行程修改助手。

必须只返回合法 JSON 对象，不要返回 Markdown、解释或前言。
根据当前行程 JSON、用户修改指令和补充研究信息，输出修改后的完整 PlanDraft。

原则：
- 只改用户要求的部分，完整保留其他内容的有价值细节。
- requirements 字段保持原行程一致，不自行修改用户未提及的出行人数/目的地/天数等。
- 补充研究有内容时，将相关信息融入修改后的行程。
- ID 字段可留空，系统会统一重新分配稳定 ID。
- 没有可靠信息时允许字段为空，不编造事实。
- 费用一律用文字描述（如"约90元"），不要用数字。
请按输入中给出的 JSON Schema 输出。"""
