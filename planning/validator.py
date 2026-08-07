"""PlanDraft 的纯代码校验器。"""
from __future__ import annotations

from collections import Counter
from datetime import time, timedelta

from planning.models import PlanDraft, ValidationIssue


def validate_plan(plan: PlanDraft) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    req = plan.requirements

    if req.duration_days is not None and len(plan.schedule) != req.duration_days:
        issues.append(
            ValidationIssue(
                code="DURATION_MISMATCH",
                severity="high",
                target="schedule",
                message=f"计划有 {len(plan.schedule)} 天，但需求是 {req.duration_days} 天。",
            )
        )

    expected_days = list(range(1, len(plan.schedule) + 1))
    actual_days = [day.day for day in plan.schedule]
    if actual_days != expected_days:
        issues.append(
            ValidationIssue(
                code="INVALID_DAY_SEQUENCE",
                severity="high",
                target="schedule",
                message="day 必须从 1 开始连续递增且不重复。",
            )
        )

    _check_dates(plan, issues)
    _check_unique_ids(plan, issues)
    _check_must_visit_and_exclude(plan, issues)
    _check_cross_city_transport(plan, issues)
    _check_budget(plan, issues)
    _check_activity_times(plan, issues)
    return issues



def _check_dates(plan: PlanDraft, issues: list[ValidationIssue]) -> None:
    start = plan.requirements.start_date
    if start is None:
        return

    for index, day in enumerate(plan.schedule):
        expected = start + timedelta(days=index)
        if day.date != expected:
            issues.append(
                ValidationIssue(
                    code="DATE_MISMATCH",
                    severity="high",
                    target=day.day_id or f"day_{index + 1}",
                    message=f"第 {index + 1} 天日期应为 {expected.isoformat()}。",
                )
            )

def _check_unique_ids(plan: PlanDraft, issues: list[ValidationIssue]) -> None:
    values_by_kind: dict[str, list[str]] = {
        "day_id": [],
        "activity_id": [],
        "trans_id": [],
        "acc_id": [],
    }
    for day in plan.schedule:
        values_by_kind["day_id"].append(day.day_id)
        for activity in day.activities:
            values_by_kind["activity_id"].append(activity.activity_id)
        for trans in day.transportation:
            values_by_kind["trans_id"].append(trans.trans_id)
        if day.accommodation:
            values_by_kind["acc_id"].append(day.accommodation.acc_id)

    for kind, values in values_by_kind.items():
        if any(not value for value in values):
            issues.append(
                ValidationIssue(
                    code="MISSING_STABLE_ID",
                    severity="high",
                    target=kind,
                    message=f"存在缺失的 {kind}。",
                )
            )
        duplicates = [value for value, count in Counter(values).items() if value and count > 1]
        if duplicates:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_STABLE_ID",
                    severity="high",
                    target=kind,
                    message=f"{kind} 重复：{', '.join(duplicates)}",
                )
            )


def _searchable_plan_text(plan: PlanDraft) -> str:
    parts: list[str] = [plan.title]
    for day in plan.schedule:
        parts.extend([day.city, day.accommodation.area if day.accommodation else ""])
        if day.accommodation and day.accommodation.name:
            parts.append(day.accommodation.name)
        for activity in day.activities:
            parts.extend([activity.title, activity.location, activity.description])
    return "\n".join(parts).lower()


def _check_must_visit_and_exclude(plan: PlanDraft, issues: list[ValidationIssue]) -> None:
    text = _searchable_plan_text(plan)
    for item in plan.requirements.must_visit:
        if item.lower() not in text:
            issues.append(
                ValidationIssue(
                    code="MISSING_MUST_VISIT",
                    severity="high",
                    target=item,
                    message=f"必去项“{item}”未出现在行程中。",
                )
            )
    for item in plan.requirements.exclude:
        if item.lower() in text:
            issues.append(
                ValidationIssue(
                    code="EXCLUDED_ITEM_PRESENT",
                    severity="high",
                    target=item,
                    message=f"用户明确排除的“{item}”仍出现在行程中。",
                )
            )


def _check_cross_city_transport(plan: PlanDraft, issues: list[ValidationIssue]) -> None:
    for index in range(1, len(plan.schedule)):
        previous = plan.schedule[index - 1]
        current = plan.schedule[index]
        if previous.city == current.city:
            continue
        transports = previous.transportation + current.transportation
        if not transports:
            issues.append(
                ValidationIssue(
                    code="MISSING_INTERCITY_TRANSPORT",
                    severity="high",
                    target=f"day_{previous.day}_to_day_{current.day}",
                    message=f"从 {previous.city} 到 {current.city} 的跨城市移动缺少 transportation。",
                )
            )


def _check_budget(plan: PlanDraft, issues: list[ValidationIssue]) -> None:
    budget = plan.requirements.budget_per_person_cny
    if budget is None:
        return
    total = plan.budget_summary.total_cny_per_person
    allowed = int(budget * 1.15)
    if total > allowed:
        issues.append(
            ValidationIssue(
                code="BUDGET_OVERFLOW",
                severity="high",
                target="budget_summary",
                message=f"预计人均 {total} 元，超过用户预算 {budget} 元的 15% 容差。",
            )
        )


def _to_minutes(value: str) -> int | None:
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.hour * 60 + parsed.minute


def _check_activity_times(plan: PlanDraft, issues: list[ValidationIssue]) -> None:
    for day in plan.schedule:
        slots: list[tuple[int, int, str]] = []
        for activity in day.activities:
            start = _to_minutes(activity.start_time)
            end = _to_minutes(activity.end_time)
            if start is None or end is None or end <= start:
                issues.append(
                    ValidationIssue(
                        code="INVALID_ACTIVITY_TIME",
                        severity="high",
                        target=activity.activity_id,
                        message=f"{activity.title} 的时间必须是合法 HH:MM，且结束时间晚于开始时间。",
                    )
                )
                continue
            slots.append((start, end, activity.activity_id))

        slots.sort()
        for prev, current in zip(slots, slots[1:]):
            if current[0] < prev[1]:
                issues.append(
                    ValidationIssue(
                        code="ACTIVITY_TIME_CONFLICT",
                        severity="high",
                        target=f"{prev[2]} / {current[2]}",
                        message=f"第 {day.day} 天存在活动时间重叠。",
                    )
                )
