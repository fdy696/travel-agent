"""Planning Workflow 中需要 LLM/Agent 判断的部分。

确定性状态推进仍在 workflow.py；本模块只处理自然语言抽取、研究、生成和语义修复。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from planning.models import (
    PlanDraft,
    RequirementsPatch,
    ResearchResult,
    TravelRequirements,
    ValidationIssue,
)
from tools.agent_tools import TRAVEL_TOOLS


class PlanningIntelligence(Protocol):
    async def extract_requirements(
        self,
        *,
        user_text: str,
        current: TravelRequirements,
    ) -> RequirementsPatch: ...

    async def research(self, requirements: TravelRequirements) -> ResearchResult: ...

    async def generate_plan(
        self,
        *,
        requirements: TravelRequirements,
        research: ResearchResult,
    ) -> PlanDraft: ...

    async def repair_plan(
        self,
        *,
        requirements: TravelRequirements,
        research: ResearchResult,
        draft: PlanDraft,
        issues: list[ValidationIssue],
    ) -> PlanDraft: ...


class LLMPlanningIntelligence:
    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self._requirements_model = llm.with_structured_output(
            RequirementsPatch,
            method="json_mode",
        )
        self._research_result_model = llm.with_structured_output(
            ResearchResult,
            method="json_mode",
        )
        self._plan_model = llm.with_structured_output(
            PlanDraft,
            method="json_mode",
        )
        # schema 在 __init__ 序列化一次，避免每次调用重复 model_json_schema()。
        self._requirements_schema = _schema_text(RequirementsPatch)
        self._research_schema = _schema_text(ResearchResult)
        self._plan_schema = _schema_text(PlanDraft)
        # Research needs tool calling and structured parsing, but combining both
        # in create_agent makes the provider choose a tool_choice for the final
        # response. Keep the tool loop text-based and parse it in a separate call.
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
        result = await self._invoke_json(
            self._requirements_model,
            [
                SystemMessage(
                    content=(
                        "你负责从旅游规划对话中抽取本轮新增或修改的需求。"
                        "必须只返回合法 JSON 对象，不要返回 Markdown 或解释。"
                        "只输出用户本轮明确表达或可直接推导的信息，不猜测高影响事实。"
                        "对于 destinations/must_visit/exclude，如果本轮涉及这些字段，"
                        "输出应用本轮修改后的完整列表；未涉及则保持 null。"
                        "相对日期必须结合今天解释。JSON 示例："
                        '{"origin":null,"destinations":["云南"],"duration_days":5,'
                        '"traveler_count":2,"budget_per_person_cny":null}'
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
        return _as_model(result, RequirementsPatch)

    async def research(self, requirements: TravelRequirements) -> ResearchResult:
        try:
            result = await self._research_agent.ainvoke(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                "为下面这次旅行规划做事实研究，并输出普通文本研究报告，"
                                "不要输出 JSON。\n"
                                f"requirements={requirements.model_dump_json()}\n"
                                "重点收集：适合季节/天气、核心景点与开放/门票信息、"
                                "城市间/景点间交通、住宿区域、美食与明显风险。"
                                "如果出行日期不在天气 API 近 3 天范围内，不要拿当前天气冒充未来天气，"
                                "应使用联网搜索获取季节气候信息。"
                            )
                        )
                    ]
                }
            )
            report = _last_text(result.get("messages", []))
            if not report:
                raise RuntimeError("research agent 返回空 content")

            parsed = await self._invoke_json(
                self._research_result_model,
                [
                    SystemMessage(
                        content=(
                            "你负责把旅游研究报告整理成 ResearchResult。"
                            "必须只返回合法 JSON 对象，不要返回 Markdown 或解释。"
                            "JSON 示例："
                            '{"weather":[],"attractions":[],"transport":[],'
                            '"accommodation":[],"food":[],"source_notes":[],'
                            '"assumptions":[],"partial_failures":[]}'
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"需求：{requirements.model_dump_json()}\n"
                            f"研究报告：{report}\n"
                            f"请按此 JSON Schema 输出：{self._research_schema}"
                        )
                    ),
                ],
            )
            return _as_model(parsed, ResearchResult)
        except Exception as exc:
            raise RuntimeError(f"research failed: {exc}") from exc

    async def generate_plan(
        self,
        *,
        requirements: TravelRequirements,
        research: ResearchResult,
    ) -> PlanDraft:
        result = await self._invoke_json(
            self._plan_model,
            [
                SystemMessage(content=PLAN_GENERATION_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        "根据以下已确认需求和研究信息生成完整结构化行程。\n"
                        f"requirements={requirements.model_dump_json()}\n"
                        f"research={research.model_dump_json()}\n"
                        f"请按此 JSON Schema 输出：{self._plan_schema}"
                    )
                ),
            ],
        )
        return _as_model(result, PlanDraft)

    async def repair_plan(
        self,
        *,
        requirements: TravelRequirements,
        research: ResearchResult,
        draft: PlanDraft,
        issues: list[ValidationIssue],
    ) -> PlanDraft:
        result = await self._invoke_json(
            self._plan_model,
            [
                SystemMessage(
                    content=(
                        "你负责修复旅游计划中的明确校验问题。"
                        "必须只返回合法 JSON 对象，不要返回 Markdown 或解释。"
                        "只修改必要部分，不得改变用户已确认需求，不得删除 must_visit，"
                        "不得加入 exclude。价格若无可靠来源只能作为估算并在 assumptions 说明。"
                    )
                ),
                HumanMessage(
                    content=(
                        f"requirements={requirements.model_dump_json()}\n"
                        f"research={research.model_dump_json()}\n"
                        f"draft={draft.model_dump_json()}\n"
                        f"issues={json.dumps([i.model_dump() for i in issues], ensure_ascii=False)}\n"
                        f"请按此 JSON Schema 输出：{self._plan_schema}"
                    )
                ),
            ],
        )
        return _as_model(result, PlanDraft)


    async def _invoke_json(self, model, messages):
        """DeepSeek JSON mode 偶发返回空 content；重试一次，其他异常直接抛给上层。"""
        result = await model.ainvoke(messages)
        if result is not None:
            return result
        result = await model.ainvoke(messages)
        if result is None:
            raise RuntimeError("JSON mode returned empty content twice")
        return result


def _schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False)


def _as_model(value: object, model: type[BaseModel]):
    if isinstance(value, model):
        return value
    if isinstance(value, dict) and "parsed" in value:
        value = value["parsed"]
    return model.model_validate(value)


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
- 报告应包含来源线索或搜索结论，方便后续 JSON 整理和追溯。
- 工具返回空结果、超时或鉴权失败时，保留已获得信息并明确标注，不要因此编造结论。"""


PLAN_GENERATION_SYSTEM_PROMPT = """你是专业旅游行程生成器。

必须只返回合法 JSON 对象，不要返回 Markdown 或解释。JSON 示例：
{"title":"云南5日自然风光游","requirements":{},"schedule":[],"budget_summary":{},"assumptions":[]}

根据已确认 requirements 与 research 生成可执行、不过度紧凑的多日计划。
要求：
- schedule 天数必须等于 duration_days。
- 每天活动给出 24 小时制 start_time/end_time，避免时间冲突。
- 跨城市移动必须给 transportation。
- 必须覆盖 must_visit，绝不安排 exclude。
- 预算未知时允许合理估算，但要写 assumptions；预算已知时尽量控制在预算内。
- 不要把出发地凭空补成某个城市；origin 为空时按“当地行程”处理。
- ID 字段可以留空，系统会在生成后统一分配稳定 ID。
- requirements 字段原样反映已确认需求，不自行修改。
- 请按输入中给出的 JSON Schema 输出。"""
