"""DeepSeek JSON-mode 调用的共享机制。

planning 与 modification 两个 Intelligence 模块共用同一套：
- schema 序列化
- JSON 调用 + 空 content 重试
- Schema Parse
- Parse 失败时的 Format Repair（只改格式不改语义）

避免同一机制在两处重复实现导致行为漂移。
"""
from __future__ import annotations

import json
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)

PLAN_FORMAT_REPAIR_SYSTEM_PROMPT = """你是 JSON 格式修复器。

上一次模型输出无法解析为符合目标 Schema 的 JSON。请只修正格式问题
（字段名、类型、缺失必填项、非法枚举等），把内容整理成一份严格符合
给定 JSON Schema 的完整 JSON 对象，不要改变内容的语义。"""


def schema_text(model: type[BaseModel]) -> str:
    """把 Pydantic 模型序列化成 JSON Schema 文本（用于注入 prompt）。"""
    return json.dumps(model.model_json_schema(), ensure_ascii=False)


async def invoke_json(model: BaseChatModel, messages) -> object:
    """JSON mode 偶发返回空 content；重试一次，其他异常直接抛给上层。"""
    result = await model.ainvoke(messages)
    if result is not None:
        return result
    result = await model.ainvoke(messages)
    if result is None:
        raise RuntimeError("JSON mode returned empty content twice")
    return result


def parse_model(value: object, model: type[M]) -> M:
    """把 JSON mode 返回值强制转成目标 Pydantic 模型。"""
    if isinstance(value, model):
        return value
    if isinstance(value, dict) and "parsed" in value:
        value = value["parsed"]
    return model.model_validate(value)


async def structured_generate(
    model: BaseChatModel,
    *,
    model_type: type[M],
    schema: str,
    system: str,
    user: str,
    repair_context: str,
) -> M:
    """按 JSON Schema 生成并解析；失败时 Format Repair 一次。

    Args:
        model_type: 目标 Pydantic 模型
        schema: 该模型的 JSON Schema 文本（应已拼进 user 内容）
        system: 生成阶段的系统提示
        user: 生成阶段的用户内容
        repair_context: Format Repair 时给模型的关键上下文（requirements/当前行程等）
    """
    result = await invoke_json(
        model,
        [SystemMessage(content=system), HumanMessage(content=user)],
    )
    try:
        return parse_model(result, model_type)
    except Exception:
        # 只修格式：让模型按同一 Schema 重新输出，不介入业务语义。
        repaired = await invoke_json(
            model,
            [
                SystemMessage(content=PLAN_FORMAT_REPAIR_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"之前的输出无法解析为合法 {model_type.__name__}。\n"
                        f"{repair_context}\n"
                        f"原输出：{result}\n"
                        f"请严格按此 JSON Schema 重新输出：{schema}"
                    )
                ),
            ],
        )
        return parse_model(repaired, model_type)
