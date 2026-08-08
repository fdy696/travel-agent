"""确定性 Markdown Renderer。

把 Rich PlanDraft 的全部字段固定渲染成完整攻略 Markdown，交还主 Agent 转达给用户。
渲染是纯函数、无 LLM 参与，避免「让主 Agent 总结」造成信息缩水。
"""
from __future__ import annotations

from planning.models import PlanDraft


def render_plan_markdown(plan: PlanDraft) -> str:
    """把 PlanDraft 完整渲染为攻略 Markdown。

    层级约定（纯聊天 Markdown 规整）：
    - H1 仅计划标题；
    - H2 章节（出行基础信息 / 天气参考 / 每日行程 / 城际交通 / …）；
    - H3 Day、城际交通路段、景点、住宿地区、美食分类；
    - H4 Activity、美食店、出行准备子节。
    """
    lines: list[str] = []

    # ── 标题 / 副标题（唯一 H1）──
    lines.append(f"# {plan.title}")
    if plan.subtitle:
        lines.append(f"> {plan.subtitle}")
    lines.append("")

    # ── 出行基础信息 ──
    _render_basic_info(lines, plan)

    # ── 天气参考 ──
    _render_weather(lines, plan)

    # ── 整体思路 ──
    if plan.overview:
        lines.extend(["## 📋 行程规划与路线安排", plan.overview, ""])

    # ── 每日行程 ──
    if plan.schedule:
        lines.append("## 🗓️ 每日行程")
        lines.append("")
        for day in plan.schedule:
            date_part = f" · {day.date.isoformat()}" if day.date else ""
            title_part = f" · {day.title}" if day.title else ""
            lines.append(f"### Day {day.day}:{title_part}{date_part}")
            if day.summary:
                lines.append(day.summary)
            lines.append("")
            _render_activities(lines, day)
            _render_transport(lines, day)
            if day.accommodation:
                acc = day.accommodation
                lines.append("#### 🏨 今日住宿")
                lines.append(f"- 推荐区域：{acc.area}")
                if acc.type:
                    lines.append(f"- 类型：{acc.type}")
                if acc.name:
                    lines.append(f"- 推荐酒店：{acc.name}")
                if acc.estimated_cost:
                    lines.append(f"- 参考价格：{acc.estimated_cost}")
            if day.day_tips:
                lines.extend(["- 💡 当日提示："] + [f"  - {t}" for t in day.day_tips])
            lines.append("")

    # ── 城际交通 ──
    if plan.transportation_guide:
        lines.append("## 🚄 城际交通")
        lines.append("")
        for leg in plan.transportation_guide:
            title = f"{leg.from_location} → {leg.to_location}"
            lines.append(f"### {title}")
            if leg.mode:
                lines.append(f"- 方式：{leg.mode}")
            if leg.duration:
                lines.append(f"- 用时：{leg.duration}")
            if leg.price:
                lines.append(f"- 价格：{leg.price}")
            if leg.departure_station:
                lines.append(f"- 出发站：{leg.departure_station}")
            if leg.arrival_station:
                lines.append(f"- 到达站：{leg.arrival_station}")
            if leg.schedule:
                lines.append(f"- 班次：{leg.schedule}")
            if leg.suggestion:
                lines.append(f"- 建议：{leg.suggestion}")
            lines.append("")

    # ── 美食推荐（按分类分组 + 逛吃路线）──
    _render_food(lines, plan)

    # ── 景点深度攻略 ──
    if plan.attraction_guides:
        lines.append("## 🏛️ 核心景点攻略")
        lines.append("")
        for guide in plan.attraction_guides:
            lines.append(f"### {guide.name}")
            if guide.introduction:
                lines.append(guide.introduction)
            if guide.history:
                lines.append("")
                lines.append(guide.history)
            if guide.highlights:
                lines.extend(["", "**看什么 / 核心看点**"] + [f"- {h}" for h in guide.highlights])
            details = []
            if guide.recommended_duration:
                details.append(f"建议游览：{guide.recommended_duration}")
            if guide.opening_hours:
                details.append(f"开放时间：{guide.opening_hours}")
            if guide.ticket_info:
                details.append(f"门票：{guide.ticket_info}")
            if guide.booking_info:
                details.append(f"预约：{guide.booking_info}")
            if guide.best_visit_time:
                details.append(f"最佳时段：{guide.best_visit_time}")
            if details:
                lines.extend(["", "**实用信息**"] + [f"- {d}" for d in details])
            if guide.photo_spots:
                lines.extend(["", "**📸 拍照位置**"] + [f"- {p}" for p in guide.photo_spots])
            if guide.tips:
                lines.extend(["", "**⚠️ 避坑 / 怎么逛**"] + [f"- {t}" for t in guide.tips])
            lines.append("")

    # ── 住宿建议 ──
    if plan.accommodation_recommendations:
        lines.append("## 🏨 住宿建议")
        lines.append("")
        by_area: dict[str, list] = {}
        order: list[str] = []
        for acc in plan.accommodation_recommendations:
            area = acc.area or "其他"
            if area not in by_area:
                by_area[area] = []
                order.append(area)
            by_area[area].append(acc)
        for area in order:
            lines.append(f"### {area}")
            for acc in by_area[area]:
                parts = [acc.name or "住宿"]
                if acc.type:
                    parts.append(acc.type)
                if acc.price_reference:
                    parts.append(acc.price_reference)
                lines.append(f"- {' · '.join(parts)}")
                if acc.address:
                    lines.append(f"  - 📍 {acc.address}")
                if acc.description:
                    lines.append(f"  - {acc.description}")
                if acc.tips:
                    lines.extend([f"  - {t}" for t in acc.tips])
            lines.append("")

    # ── 预算参考 ──
    if plan.budget_breakdown or plan.budget_total or plan.budget_tips:
        lines.append("## 💰 预算参考")
        lines.append("")
        if plan.budget_breakdown:
            lines.append("| 项目 | 人均预算 |")
            lines.append("| --- | --- |")
            for item in plan.budget_breakdown:
                lines.append(f"| {item.item} | {item.per_person} |")
            lines.append("")
        if plan.budget_total:
            lines.append(f"预计总计：{plan.budget_total}")
            lines.append("")
        if plan.budget_tips:
            lines.extend(["- " + t for t in plan.budget_tips])
            lines.append("")

    # ── 出行准备 ──
    tips_sections = [
        ("🎫 预约", plan.booking_tips),
        ("🚌 交通", plan.transportation_tips),
        ("👕 穿搭", plan.clothing_tips),
        ("📷 拍照", plan.photo_tips),
        ("⚠️ 避坑", plan.warnings),
    ]
    if any(tips for _, tips in tips_sections):
        lines.append("## 🎒 出行准备")
        lines.append("")
        for heading, tips in tips_sections:
            if tips:
                lines.extend([f"#### {heading}"] + [f"- {t}" for t in tips] + [""])

    # ── 假设 / 说明 ──
    if plan.assumptions:
        lines.extend(["## 📝 假设 / 说明"] + [f"- {a}" for a in plan.assumptions])

    return "\n".join(lines).strip() + "\n"


def _render_basic_info(lines: list[str], plan: PlanDraft) -> None:
    req = plan.requirements
    rows: list[str] = []
    if req.start_date or req.end_date:
        time_text = " 至 ".join(x for x in (req.start_date.isoformat() if req.start_date else None,
                                            req.end_date.isoformat() if req.end_date else None) if x)
        rows.append(f"出行时间：{time_text}")
    if req.duration_days:
        rows.append(f"行程天数：{req.duration_days} 天")
    if req.traveler_count:
        rows.append(f"出行人数：{req.traveler_count} 人")
    if req.budget_per_person_cny:
        rows.append(f"预算：人均 {req.budget_per_person_cny} 元")
    if req.destinations:
        rows.append(f"目的地：{'、'.join(req.destinations)}")
    if req.pace:
        rows.append(f"出行节奏：{req.pace}")
    if req.accommodation_preference:
        rows.append(f"住宿倾向：{req.accommodation_preference}")
    if req.notes:
        rows.append(f"出行偏好：{req.notes}")
    if rows:
        lines.extend(["## 📋 出行基础信息", ""])
        lines.extend(f"- {r}" for r in rows)
        lines.append("")


def _render_weather(lines: list[str], plan: PlanDraft) -> None:
    if not (plan.weather_summary or plan.weather_details or plan.weather_tip):
        return
    lines.append("## 🌤️ 天气参考")
    lines.append("")
    if plan.weather_summary:
        lines.append(plan.weather_summary)
    for detail in plan.weather_details:
        month = f"**{detail.month}** " if detail.month else ""
        lines.append(f"- {month}{detail.summary}")
    if plan.weather_tip:
        lines.append("")
        lines.append(f"> {plan.weather_tip}")
    lines.append("")


def _render_food(lines: list[str], plan: PlanDraft) -> None:
    if not (plan.food_recommendations or plan.food_route):
        return
    lines.append("## 🍜 特色美食探店推荐")
    lines.append("")

    # 按 category 分组，保持输入顺序
    groups: dict[str, list] = {}
    order: list[str] = []
    for food in plan.food_recommendations:
        cat = food.category or "其他"
        if cat not in groups:
            groups[cat] = []
            order.append(cat)
        groups[cat].append(food)

    for cat in order:
        lines.append(f"#### {cat}")
        for food in groups[cat]:
            lines.append(f"**{food.name}**")
            if food.area or food.address:
                where = "，".join(x for x in (food.area, food.address) if x)
                lines.append(f"- 📍 {where}")
            if food.recommended_dishes:
                lines.append(f"- 🍴 推荐：{'、'.join(food.recommended_dishes)}")
            if food.price_reference:
                lines.append(f"- 💰 参考价格：{food.price_reference}")
            if food.best_time:
                lines.append(f"- 🕐 最佳：{food.best_time}")
            if food.description:
                lines.append(f"- 💡 {food.description}")
            if food.tips:
                lines.extend(f"- ⚠️ {t}" for t in food.tips)
            lines.append("")

    if plan.food_route:
        lines.extend(["#### 美食逛吃路线参考"] + [f"- {r}" for r in plan.food_route])
        lines.append("")


def _render_activities(lines: list[str], day) -> None:
    for activity in day.activities:
        time_part = ""
        if activity.start_time or activity.end_time:
            time_part = f"{activity.start_time or ''}-{activity.end_time or ''} "
        period = f"[{activity.period}] " if activity.period else ""
        location = f"（{activity.location}）" if activity.location else ""
        lines.append(f"#### {time_part}{period}{activity.title}{location}")
        if activity.description:
            lines.append("")
            lines.append(activity.description)
        if activity.route:
            lines.extend(["", "**推荐路线**"] + [f"- {r}" for r in activity.route])
        if activity.highlights:
            lines.extend(["", "**怎么玩 / 看什么**"] + [f"- {h}" for h in activity.highlights])
        if activity.pois:
            lines.extend(["", "**涉及地点**"])
            for poi in activity.pois:
                address = f"（{poi.address}）" if poi.address else ""
                lines.append(f"- {poi.name}{address}")
        if activity.transportation:
            lines.extend(["", f"**交通** {activity.transportation}"])
        if activity.estimated_cost:
            lines.append(f"**费用** {activity.estimated_cost}")
        if activity.photo_spots:
            lines.extend(["", "**📸 推荐打卡**"] + [f"- {p}" for p in activity.photo_spots])
        if activity.booking_notes:
            lines.extend(["", "**🎫 预约/购票**"] + [f"- {b}" for b in activity.booking_notes])
        if activity.alternatives:
            lines.extend(["", "**备选方案**"] + [f"- {a}" for a in activity.alternatives])
        if activity.tips:
            lines.extend(["", "**💡 小贴士**"] + [f"- {t}" for t in activity.tips])
        lines.append("")


def _render_transport(lines: list[str], day) -> None:
    for transport in day.transportation:
        duration = (
            f"，约 {transport.estimated_duration_minutes} 分钟"
            if transport.estimated_duration_minutes is not None
            else ""
        )
        cost = f"（{transport.estimated_cost}）" if transport.estimated_cost else ""
        lines.append(
            f"- 🚄 交通：{transport.from_location} → {transport.to_location}"
            f"，{transport.mode}{duration}{cost}"
        )
