"""Deterministic travel budget calculator.

不保存任何城市价格，不做旅行判断；只对 Main 已选定的价格项目做确定性汇总。
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class BudgetItem(BaseModel):
    name: str = Field(description="预算项目名称，如 东京→京都新干线")
    category: str = Field(description="分类，如 transport / hotel / food / ticket")
    amount_min: float = Field(ge=0, description="单价或区间下限，必须使用 currency 指定的币种")
    amount_max: float | None = Field(default=None, ge=0, description="区间上限；固定价格可省略")
    quantity: float = Field(default=1, gt=0, description="数量，如住宿晚数、餐饮天数")
    per_person: bool = Field(
        default=False,
        description="单价是否为每人价格；true 时自动乘以 people",
    )


class BudgetInput(BaseModel):
    currency: str = Field(description="ISO 4217 币种代码，如 JPY / CNY / USD")
    people: int = Field(default=1, ge=1, description="旅行人数")
    items: list[BudgetItem] = Field(min_length=1, description="最终采用方案的预算项目")


def _decimal(value: float | int) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"无效金额：{value}") from exc


def _number(value: Decimal) -> int | float:
    normalized = value.quantize(Decimal("0.01"))
    if normalized == normalized.to_integral():
        return int(normalized)
    return float(normalized)


def calculate_budget_data(
    *,
    currency: str,
    people: int,
    items: list[BudgetItem],
) -> dict:
    """纯函数：汇总预算并返回结构化数据。"""
    iso_currency = currency.strip().upper()
    if len(iso_currency) != 3 or not iso_currency.isalpha():
        raise ValueError("currency 必须使用 3 位 ISO 4217 代码，例如 JPY / CNY / USD")

    group_min = Decimal("0")
    group_max = Decimal("0")
    categories: dict[str, dict[str, Decimal]] = {}
    normalized_items: list[dict] = []

    for item in items:
        unit_min = _decimal(item.amount_min)
        unit_max = _decimal(item.amount_max if item.amount_max is not None else item.amount_min)
        if unit_max < unit_min:
            raise ValueError(f"{item.name} 的 amount_max 不能小于 amount_min")

        multiplier = _decimal(item.quantity)
        if item.per_person:
            multiplier *= Decimal(people)

        line_min = unit_min * multiplier
        line_max = unit_max * multiplier
        group_min += line_min
        group_max += line_max

        bucket = categories.setdefault(
            item.category,
            {"min": Decimal("0"), "max": Decimal("0")},
        )
        bucket["min"] += line_min
        bucket["max"] += line_max

        normalized_items.append(
            {
                "name": item.name,
                "category": item.category,
                "group_min": _number(line_min),
                "group_max": _number(line_max),
            }
        )

    people_decimal = Decimal(people)
    return {
        "currency": iso_currency,
        "people": people,
        "group_total": {
            "min": _number(group_min),
            "max": _number(group_max),
        },
        "per_person_total": {
            "min": _number(group_min / people_decimal),
            "max": _number(group_max / people_decimal),
        },
        "categories": {
            category: {
                "min": _number(values["min"]),
                "max": _number(values["max"]),
            }
            for category, values in categories.items()
        },
        "items": normalized_items,
    }


@tool("calculate_budget", args_schema=BudgetInput)
def calculate_budget(
    currency: str,
    people: int,
    items: list[BudgetItem],
) -> str:
    """对已确定的旅行价格项目做预算汇总。

    只计算 Main 最终采用的方案；不要把未采用的备选交通、酒店或 Pass 混入 items。
    Tool 不提供任何城市价格，也不判断哪个旅行方案更好。
    """
    normalized_items = [
        item if isinstance(item, BudgetItem) else BudgetItem.model_validate(item)
        for item in items
    ]
    data = calculate_budget_data(
        currency=currency,
        people=people,
        items=normalized_items,
    )
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
