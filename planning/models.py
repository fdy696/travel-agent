"""旅游规划领域模型与结构化输出 Schema。"""
from __future__ import annotations

from datetime import date as Date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator


Pace = Literal["relaxed", "moderate", "intense"]
TaskState = Literal["collecting", "processing", "completed", "failed", "cancelled"]
Severity = Literal["low", "medium", "high"]


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
    notes: str | None = None


class ResearchResult(BaseModel):
    """Research Node 的结构化产物。"""

    weather: list[str] = Field(default_factory=list)
    attractions: list[str] = Field(default_factory=list)
    transport: list[str] = Field(default_factory=list)
    accommodation: list[str] = Field(default_factory=list)
    food: list[str] = Field(default_factory=list)
    source_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    partial_failures: list[str] = Field(default_factory=list)

    def has_useful_data(self) -> bool:
        return any(
            (
                self.weather,
                self.attractions,
                self.transport,
                self.accommodation,
                self.food,
                self.source_notes,
            )
        )


class Activity(BaseModel):
    activity_id: str = ""
    start_time: str = Field(description="24小时制 HH:MM")
    end_time: str = Field(description="24小时制 HH:MM")
    title: str
    location: str
    description: str = ""
    estimated_cost_cny_per_person: int = Field(default=0, ge=0)


class Transportation(BaseModel):
    trans_id: str = ""
    from_location: str
    to_location: str
    mode: str
    estimated_duration_minutes: int | None = Field(default=None, ge=0)
    estimated_cost_cny_per_person: int = Field(default=0, ge=0)


class Accommodation(BaseModel):
    acc_id: str = ""
    area: str
    type: str
    name: str | None = None
    estimated_cost_cny_per_room: int = Field(default=0, ge=0)


class DayPlan(BaseModel):
    day_id: str = ""
    day: int = Field(ge=1)
    date: Date | None = None
    city: str
    activities: list[Activity] = Field(default_factory=list)
    transportation: list[Transportation] = Field(default_factory=list)
    accommodation: Accommodation | None = None
    estimated_daily_cost_cny_per_person: int = Field(default=0, ge=0)


class BudgetSummary(BaseModel):
    transportation_cny_per_person: int = Field(default=0, ge=0)
    accommodation_cny_per_person: int = Field(default=0, ge=0)
    food_cny_per_person: int = Field(default=0, ge=0)
    tickets_cny_per_person: int = Field(default=0, ge=0)
    other_cny_per_person: int = Field(default=0, ge=0)
    total_cny_per_person: int = Field(default=0, ge=0)


class PlanDraft(BaseModel):
    """LLM 生成、尚未持久化的计划。"""

    title: str
    requirements: TravelRequirements
    schedule: list[DayPlan]
    budget_summary: BudgetSummary = Field(default_factory=BudgetSummary)
    assumptions: list[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    code: str
    severity: Severity
    target: str | None = None
    message: str


class PlanningTask(BaseModel):
    task_id: str
    user_id: str
    session_id: str
    state: TaskState
    requirements: TravelRequirements = Field(default_factory=TravelRequirements)
    repair_count: int = 0
    delivered_plan_id: str | None = None
    last_error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class PlanDocument(PlanDraft):
    """正式持久化的 PlanVersion 文档。"""

    plan_id: str
    version: int = 1
    parent_version: int | None = None
    user_id: str
    session_id: str
    created_at: datetime


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

    total = sum(day.estimated_daily_cost_cny_per_person for day in data.schedule)
    data.budget_summary.total_cny_per_person = total

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
