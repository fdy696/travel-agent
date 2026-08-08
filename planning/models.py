"""旅游规划领域模型与结构化输出 Schema。"""
from __future__ import annotations

from datetime import date as Date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator


Pace = Literal["relaxed", "moderate", "intense", "comfortable"]
TaskState = Literal["collecting", "processing", "completed", "failed", "cancelled"]


class TravelRequirements(BaseModel):
    """一次旅游规划的已确认/已收集需求。"""

    origin: str | None = None
    destinations: list[str] = Field(default_factory=list)
    start_date: Date | None = None
    end_date: Date | None = None
    duration_days: int | None = Field(default=None, ge=1, le=60)
    traveler_count: int | None = Field(default=None, ge=1, le=50)
    budget_per_person_cny: int | None = Field(default=None, ge=1)
    pace: Pace | None = None
    must_visit: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    accommodation_preference: str | None = Field(default=None, description="住宿倾向，如「靠近老门东/夫子庙，方便逛吃夜景」")
    notes: str | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "TravelRequirements":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self


class RequirementsPatch(BaseModel):
    """从本轮用户输入抽取出的需求增量。

    字段为 None 表示本轮未提及；列表如果显式给空列表表示用户希望清空该约束。
    """

    origin: str | None = None
    destinations: list[str] | None = None
    start_date: Date | None = None
    end_date: Date | None = None
    duration_days: int | None = Field(default=None, ge=1, le=60)
    traveler_count: int | None = Field(default=None, ge=1, le=50)
    budget_per_person_cny: int | None = Field(default=None, ge=1)
    pace: Pace | None = None
    must_visit: list[str] | None = None
    exclude: list[str] | None = None
    accommodation_preference: str | None = None
    notes: str | None = None


class Poi(BaseModel):
    """行程中的地点卡片：名称 + 地址。"""

    name: str
    address: str | None = None


class Activity(BaseModel):
    """一段具体的游览/体验活动。

    信息容量对齐完整攻略：去哪、怎么玩、怎么走、看什么、拍什么、怎么预约、有什么坑与替代方案。
    """

    activity_id: str = ""
    period: str | None = Field(default=None, description="如「上午」「下午」「傍晚」「晚上」")
    start_time: str | None = Field(default=None, description="24小时制 HH:MM")
    end_time: str | None = Field(default=None, description="24小时制 HH:MM")
    title: str
    description: str | None = Field(default=None, description="活动内容/怎么玩")
    route: list[str] = Field(default_factory=list, description="推荐路线，如「龙龛码头 → 才村 → 磻溪S湾」")
    highlights: list[str] = Field(default_factory=list, description="打卡点/看什么")
    photo_spots: list[str] = Field(default_factory=list, description="📸 推荐打卡/拍照位置")
    pois: list[Poi] = Field(default_factory=list, description="涉及的景点/店铺卡片，含名称与地址")
    location: str | None = None
    transportation: str | None = Field(default=None, description="到达/移动方式与耗时")
    estimated_cost: str | None = Field(default=None, description="参考花费，如「约90元」「免费」「1.5-3.5元/个」")
    booking_notes: list[str] = Field(default_factory=list, description="🎫 预约/购票/开放说明")
    tips: list[str] = Field(default_factory=list, description="💡 小贴士")
    alternatives: list[str] = Field(default_factory=list, description="备选方案/停运替代")
    source_url: str | None = None


class Transportation(BaseModel):
    trans_id: str = ""
    from_location: str
    to_location: str
    mode: str
    estimated_duration_minutes: int | None = Field(default=None, ge=0)
    estimated_cost: str | None = Field(default=None, description="参考花费，如「约30元」")


class Accommodation(BaseModel):
    acc_id: str = ""
    area: str
    type: str
    name: str | None = None
    estimated_cost: str | None = Field(default=None, description="参考价格，如「约400元/晚」")


class DayPlan(BaseModel):
    day_id: str = ""
    day: int = Field(ge=1)
    date: Date | None = None
    title: str | None = Field(default=None, description="当日主题，如「老门东夫子庙 Citywalk」")
    city: str
    summary: str | None = None
    activities: list[Activity] = Field(default_factory=list)
    transportation: list[Transportation] = Field(default_factory=list)
    accommodation: Accommodation | None = None
    day_tips: list[str] = Field(default_factory=list, description="当日注意事项")


class FoodRecommendation(BaseModel):
    """独立美食推荐（不是日程里的一个条目）。"""

    name: str
    category: str | None = Field(default=None, description="分类，如「老门东必吃小吃」「正餐菜馆」「本地口碑老店」")
    area: str | None = None
    address: str | None = None
    recommended_dishes: list[str] = Field(default_factory=list)
    price_reference: str | None = Field(default=None, description="如「牛肉锅贴约12元/份」")
    description: str | None = Field(default=None, description="推荐理由")
    best_time: str | None = None
    tips: list[str] = Field(default_factory=list)
    source_url: str | None = None


class AttractionGuide(BaseModel):
    """独立景点深度攻略，承载历史背景、看点与拍照位置。"""

    name: str
    introduction: str | None = Field(default=None, description="景点介绍")
    history: str | None = Field(default=None, description="历史/文化背景")
    highlights: list[str] = Field(default_factory=list, description="核心看点")
    recommended_duration: str | None = Field(default=None, description="建议游览时长")
    ticket_info: str | None = None
    opening_hours: str | None = None
    booking_info: str | None = Field(default=None, description="预约说明")
    photo_spots: list[str] = Field(default_factory=list, description="拍照位置建议")
    best_visit_time: str | None = None
    tips: list[str] = Field(default_factory=list)
    source_url: str | None = None


class AccommodationRecommendation(BaseModel):
    """独立住宿推荐。"""

    name: str | None = None
    area: str | None = None
    address: str | None = None
    type: str | None = Field(default=None, description="如「舒适型酒店」「民宿」")
    price_reference: str | None = None
    description: str | None = None
    tips: list[str] = Field(default_factory=list)
    source_url: str | None = None


class WeatherReference(BaseModel):
    """单个时段/月份的天气参考。"""

    month: str | None = Field(default=None, description="如「6月」「7月」")
    summary: str = Field(description="该月天气/温度/降雨/穿衣要点")


class TransportationGuide(BaseModel):
    """一段城际/主要移动方式的完整说明。"""

    from_location: str
    to_location: str
    mode: str | None = Field(default=None, description="如「高铁」「飞机」「大巴」")
    duration: str | None = Field(default=None, description="用时，如「约2小时」")
    price: str | None = Field(default=None, description="价格，如「约145元/人」")
    departure_station: str | None = Field(default=None, description="出发站/机场")
    arrival_station: str | None = Field(default=None, description="到达站/机场")
    schedule: str | None = Field(default=None, description="班次/时刻建议")
    suggestion: str | None = Field(default=None, description="建议，如「提前订票」")


class BudgetBreakdown(BaseModel):
    """预算分项参考。"""

    item: str = Field(description="如「住宿」「餐饮」「景点」「市内交通」「城际交通」")
    per_person: str = Field(description="人均参考，如「约800元」")


class PlanDraft(BaseModel):
    """LLM 生成、尚未持久化的计划。

    信息容量覆盖完整攻略：基础信息、天气、逐日行程、城际交通、景点深度攻略、美食、住宿、预算与出行准备。
    费用字段一律用字符串（如「约90元」「免费」），不用数值，避免 Schema 解析被自由文本价格卡死。
    """

    title: str
    subtitle: str | None = Field(default=None, description="一行简介，如「2026年6-7月 · 情侣二人 · 松弛逛吃」")
    requirements: TravelRequirements

    overview: str | None = Field(default=None, description="整体规划思路/路线逻辑")
    weather_summary: str | None = Field(default=None, description="天气整体概述")
    weather_details: list[WeatherReference] = Field(default_factory=list, description="按月/分时段的天气参考")
    weather_tip: str | None = Field(default=None, description="天气实用提醒，如「携带防晒用品、雨具并及时补水」")

    schedule: list[DayPlan] = Field(default_factory=list)

    transportation_guide: list[TransportationGuide] = Field(default_factory=list, description="城际/主要移动方式说明")

    food_recommendations: list[FoodRecommendation] = Field(default_factory=list)
    food_route: list[str] = Field(default_factory=list, description="美食逛吃路线，如「早餐:科巷/红庙 → 锅贴配鸭血汤」")
    attraction_guides: list[AttractionGuide] = Field(default_factory=list)
    accommodation_recommendations: list[AccommodationRecommendation] = Field(default_factory=list)

    budget_breakdown: list[BudgetBreakdown] = Field(default_factory=list, description="预算分项参考")
    budget_total: str | None = Field(default=None, description="预计总计，如「两人约5000-7000元（不含大交通）」")

    booking_tips: list[str] = Field(default_factory=list)
    transportation_tips: list[str] = Field(default_factory=list)
    clothing_tips: list[str] = Field(default_factory=list)
    photo_tips: list[str] = Field(default_factory=list)
    budget_tips: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    assumptions: list[str] = Field(default_factory=list)


class PlanningTask(BaseModel):
    task_id: str
    user_id: str
    session_id: str
    state: TaskState
    requirements: TravelRequirements = Field(default_factory=TravelRequirements)
    delivered_plan_id: str | None = None
    last_error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class PlanDocument(PlanDraft):
    """正式持久化的当前计划文档；每个 plan_id 只保留这一份最新内容。"""

    plan_id: str
    user_id: str
    session_id: str
    created_at: datetime

    _META_FIELDS = {"plan_id", "user_id", "session_id", "created_at"}

    def to_draft(self) -> PlanDraft:
        """转回纯 PlanDraft（去掉持久化元数据），供修改工具作为 LLM 输入。"""
        data = {k: v for k, v in self.model_dump().items() if k not in self._META_FIELDS}
        return PlanDraft.model_validate(data)



def merge_requirements(
    current: TravelRequirements,
    patch: RequirementsPatch,
) -> TravelRequirements:
    """把本轮增量合并到已有需求，并归一化日期/默认值。"""
    updates: dict[str, object] = dict(current.model_dump())
    for field_name in RequirementsPatch.model_fields:
        value = getattr(patch, field_name)
        if value is not None:
            updates[field_name] = value

    # 日期范围一旦完整，以日期计算的天数为准（包含首尾两天）。
    start_date, end_date = updates.get("start_date"), updates.get("end_date")
    if start_date and end_date:
        updates["duration_days"] = (end_date - start_date).days + 1

    if updates.get("pace") is None:
        updates["pace"] = "moderate"

    # 去重但保持用户顺序。
    updates["destinations"] = _dedupe(updates["destinations"])
    updates["must_visit"] = _dedupe(updates["must_visit"])
    updates["exclude"] = _dedupe(updates["exclude"])

    return TravelRequirements.model_validate(updates)


def missing_required_fields(requirements: TravelRequirements) -> list[str]:
    missing: list[str] = []
    if not requirements.destinations:
        missing.append("destinations")
    if requirements.traveler_count is None:
        missing.append("traveler_count")
    if requirements.duration_days is None:
        missing.append("duration_or_dates")
    return missing


def normalize_plan_draft(draft: PlanDraft, requirements: TravelRequirements) -> PlanDraft:
    """由代码分配稳定 ID、锁定 requirements，并归一化总预算。"""
    data = draft.model_copy(deep=True)
    data.requirements = requirements

    for day_index, day in enumerate(data.schedule, start=1):
        day.day = day_index
        day.day_id = f"d{day_index}"
        if requirements.start_date is not None:
            day.date = requirements.start_date + timedelta(days=day_index - 1)
        for activity_index, activity in enumerate(day.activities, start=1):
            activity.activity_id = f"d{day_index}_a{activity_index}"
        for trans_index, transport in enumerate(day.transportation, start=1):
            transport.trans_id = f"d{day_index}_t{trans_index}"
        if day.accommodation is not None:
            day.accommodation.acc_id = f"d{day_index}_acc"

    if requirements.origin is None:
        assumption = "本计划按当地行程规划，不包含出发城市到目的地的大交通。"
        if assumption not in data.assumptions:
            data.assumptions.append(assumption)

    return data


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = raw.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
