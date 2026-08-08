"""规划链路真实冒烟测试（缓存各阶段搜索结果）。

用例：云南大理+丽江 3 日游，2 人，人均 3000，洱海+玉龙雪山，下个月出发。

首次运行 `REAL_DEEPSEEK=1 uv run pytest tests/test_smoke_plan.py -s -q`
会调用真实 DeepSeek / Tavily，并把每个阶段的原始输出缓存到 tests/.cache/。
之后再跑会命中缓存（不烧 API），仍打印各阶段输出，方便反复查看。

断言尽量宽松（真实 LLM 输出有波动），只验证链路完整性和关键信息确实进入最终攻略。
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest

from agent import _build_llm
from planning.intelligence import LLMPlanningIntelligence
from planning.models import (
    PlanDraft,
    TravelRequirements,
    merge_requirements,
    missing_required_fields,
    normalize_plan_draft,
)
from planning.renderer import render_plan_markdown

CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"smoke_{key}.json"


def _load_cache(key: str):
    path = _cache_path(key)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_cache(key: str, payload) -> None:
    _cache_path(key).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _print_stage(title: str, body) -> None:
    print(f"\n{'=' * 24} {title} {'=' * 24}")
    print(body)


USER_MESSAGE = (
    "请规划云南大理和丽江 3 天游，2个人，预算每人3000元，"
    "想去洱海和玉龙雪山，预计下个月出发。"
)


@pytest.mark.real_api
def test_smoke_plan_cached_live():
    """真实链路冒烟：需求抽取 → 研究 → 生成 → 渲染，各阶段缓存可复现。"""
    intelligence = LLMPlanningIntelligence(_build_llm())

    # ── 1. 需求抽取（真实 LLM，缓存）──
    patch = _load_cache("requirements_patch")
    if patch is None:
        import asyncio

        patch = asyncio.run(
            intelligence.extract_requirements(
                user_text=USER_MESSAGE,
                current=TravelRequirements(),
            )
        )
        _save_cache("requirements_patch", patch.model_dump(mode="json"))
    else:
        from planning.models import RequirementsPatch

        patch = RequirementsPatch.model_validate(patch)
    _print_stage("① 需求抽取 RequirementsPatch", patch.model_dump_json(indent=2))

    requirements = merge_requirements(TravelRequirements(), patch)
    missing = missing_required_fields(requirements)
    _print_stage("①b 合并后需求（缺失项）", f"{missing}\n{requirements.model_dump_json(indent=2)}")
    assert not missing, f"需求仍缺失: {missing}"

    # 补上日期（测试固定为下月 1 号起 3 天，避免真实相对日期波动）
    if requirements.start_date is None or requirements.duration_days != 3:
        requirements = requirements.model_copy(
            update={
                "start_date": date(2026, 9, 1),
                "end_date": date(2026, 9, 3),
                "duration_days": 3,
            }
        )

    # ── 2. 研究（真实工具调用，缓存）──
    research = _load_cache("research")
    if research is None:
        import asyncio

        research = asyncio.run(intelligence.research(requirements))
        _save_cache("research", research)
    _print_stage("② Research 研究报告（Markdown）", research)
    assert isinstance(research, str) and research.strip()

    # ── 3. 生成行程（真实 LLM，缓存）──
    draft_data = _load_cache("plan_draft")
    if draft_data is None:
        import asyncio

        draft = asyncio.run(
            intelligence.generate_plan(requirements=requirements, research=research)
        )
        draft = normalize_plan_draft(draft, requirements)
        _save_cache("plan_draft", draft.model_dump(mode="json"))
    else:
        draft = PlanDraft.model_validate(draft_data)
    _print_stage(
        "③ 生成 PlanDraft（部分摘要）",
        _draft_summary(draft),
    )
    assert len(draft.schedule) == 3, f"schedule 应为 3 天，实际 {len(draft.schedule)}"

    # 必须覆盖用户点名的地方（洱海 / 玉龙雪山）
    haystack = json.dumps(draft.model_dump(mode="json"), ensure_ascii=False)
    for must in ("洱海", "玉龙雪山"):
        assert must in haystack, f"生成结果缺少必去项: {must}"

    # ── 4. 确定性渲染（无 LLM，不缓存，直接打印）──
    md = render_plan_markdown(draft)
    _print_stage("④ 最终攻略 Markdown", md)
    assert "#" in md and len(md) > 200


def _draft_summary(draft: PlanDraft) -> str:
    """行程摘要：天/活动数、美食数、景点数、城际交通、预算，便于一眼判断密度。"""
    lines = [f"title: {draft.title}", f"subtitle: {draft.subtitle}"]
    if draft.overview:
        lines.append(f"overview: {draft.overview[:80]}…")
    if draft.weather_summary:
        lines.append(f"weather_summary: {draft.weather_summary[:60]}…")
    for day in draft.schedule:
        act = ", ".join(a.title for a in day.activities)
        lines.append(f"Day {day.day} [{day.city}]: {act}")
    lines.append(f"food_recommendations: {len(draft.food_recommendations)} 项")
    lines.append(f"attraction_guides: {len(draft.attraction_guides)} 项")
    lines.append(f"transportation_guide: {len(draft.transportation_guide)} 段")
    lines.append(f"budget_breakdown: {len(draft.budget_breakdown)} 项, total={draft.budget_total}")
    lines.append(
        f"tips: 预约{len(draft.booking_tips)} 交通{len(draft.transportation_tips)} "
        f"穿搭{len(draft.clothing_tips)} 拍照{len(draft.photo_tips)} 避坑{len(draft.warnings)}"
    )
    return "\n".join(lines)
