"""Deterministic currency conversion using a current FX reference rate.

事实价格仍以当地货币为准；本模块只提供辅助换算，不负责旅行价格 Research。
"""
from __future__ import annotations

import json
from decimal import Decimal

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from config import get_settings


_CURRENCY_ALIASES = {
    "人民币": "CNY",
    "人民币元": "CNY",
    "元": "CNY",
    "日元": "JPY",
    "日币": "JPY",
    "美元": "USD",
    "欧元": "EUR",
    "英镑": "GBP",
    "韩元": "KRW",
    "泰铢": "THB",
    "新加坡元": "SGD",
    "新币": "SGD",
    "港币": "HKD",
    "港元": "HKD",
    "澳元": "AUD",
}

# 仅用于 APP_ENV=test 的确定性测试数据；不代表真实市场汇率。
_TEST_RATES: dict[tuple[str, str], Decimal] = {
    ("JPY", "CNY"): Decimal("0.05"),
    ("USD", "CNY"): Decimal("7.00"),
    ("EUR", "CNY"): Decimal("8.00"),
}


class CurrencyAmount(BaseModel):
    name: str = Field(description="金额名称，如 人均总预算")
    amount_min: float = Field(ge=0, description="原币种金额或区间下限")
    amount_max: float | None = Field(default=None, ge=0, description="区间上限；固定金额可省略")


class CurrencyInput(BaseModel):
    from_currency: str = Field(description="原币种，优先 ISO 4217，如 JPY")
    to_currency: str = Field(default="CNY", description="目标币种，默认 CNY")
    amounts: list[CurrencyAmount] = Field(min_length=1, description="需要使用同一当前汇率换算的金额列表")


def normalize_currency(value: str) -> str:
    raw = value.strip()
    iso = _CURRENCY_ALIASES.get(raw, raw.upper())
    if len(iso) != 3 or not iso.isalpha():
        raise ValueError(f"无法识别币种：{value}；请使用 ISO 4217 代码，如 JPY / CNY / USD")
    return iso


def _number(value: Decimal) -> int | float:
    normalized = value.quantize(Decimal("0.01"))
    if normalized == normalized.to_integral():
        return int(normalized)
    return float(normalized)


def get_exchange_rate(*, base: str, quote: str) -> tuple[Decimal, str, str]:
    """返回 rate、rate_date、source。"""
    if base == quote:
        return Decimal("1"), "same-currency", "identity"

    settings = get_settings()
    if settings.APP_ENV == "test":
        rate = _TEST_RATES.get((base, quote), Decimal("1"))
        return rate, "test", "fake-test-rate"

    url = f"{settings.FX_BASE_URL.rstrip('/')}/rate/{base}/{quote}"
    response = httpx.get(url, timeout=10.0)
    response.raise_for_status()
    payload = response.json()

    response_base = str(payload.get("base") or "").upper()
    response_quote = str(payload.get("quote") or "").upper()
    if response_base != base or response_quote != quote:
        raise RuntimeError(f"汇率响应币种不匹配：{response_base}/{response_quote}")

    rate = Decimal(str(payload["rate"]))
    return rate, str(payload.get("date") or "unknown"), "frankfurter"


def convert_currency_data(
    *,
    from_currency: str,
    to_currency: str,
    amounts: list[CurrencyAmount],
) -> dict:
    """使用同一条当前参考汇率批量换算金额。"""
    base = normalize_currency(from_currency)
    quote = normalize_currency(to_currency)
    rate, rate_date, source = get_exchange_rate(base=base, quote=quote)

    converted: list[dict] = []
    for item in amounts:
        amount_min = Decimal(str(item.amount_min))
        amount_max = Decimal(str(item.amount_max if item.amount_max is not None else item.amount_min))
        if amount_max < amount_min:
            raise ValueError(f"{item.name} 的 amount_max 不能小于 amount_min")
        converted.append(
            {
                "name": item.name,
                "from_min": _number(amount_min),
                "from_max": _number(amount_max),
                "to_min": _number(amount_min * rate),
                "to_max": _number(amount_max * rate),
            }
        )

    return {
        "from_currency": base,
        "to_currency": quote,
        "rate": _number(rate),
        "rate_date": rate_date,
        "source": source,
        "amounts": converted,
    }


@tool("convert_currency", args_schema=CurrencyInput)
def convert_currency(
    from_currency: str,
    to_currency: str,
    amounts: list[CurrencyAmount],
) -> str:
    """按当前参考汇率批量换算金额。

    用于把已经确认的当地货币价格转换成辅助参考币种；不得用换算结果替代当地事实价格。
    同一预算模块需要换算多个金额时，应一次传入，确保使用同一汇率。
    """
    try:
        normalized_amounts = [
            item if isinstance(item, CurrencyAmount) else CurrencyAmount.model_validate(item)
            for item in amounts
        ]
        data = convert_currency_data(
            from_currency=from_currency,
            to_currency=to_currency,
            amounts=normalized_amounts,
        )
    except Exception as exc:
        return f"汇率换算暂时失败：{type(exc).__name__}: {exc}"
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def current_fx_provider_name() -> str:
    """供 CLI / diagnostics 显示当前汇率策略，不触发网络请求。"""
    return "fake-test-rate" if get_settings().APP_ENV == "test" else "frankfurter"
