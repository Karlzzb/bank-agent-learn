"""LLM 结构化输出的工业级解析:JSON 提取 + pydantic 校验。

LLM 输出不可信:可能带代码围栏、前后多余文本、缺字段。
所有需要 LLM 输出 JSON 的节点(路由、偏好提取等)统一走本模块,
失败一律抛 JsonOutputError,由调用方决定降级策略。
"""

import json
import re

from pydantic import BaseModel, ValidationError

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class JsonOutputError(Exception):
    """LLM 输出无法解析/校验为目标 JSON。"""


def extract_json_object(text: str) -> dict:
    """从原始文本中提取第一个完整 JSON 对象。"""
    fenced = _FENCE_RE.search(text)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    if start == -1:
        raise JsonOutputError(f"输出中找不到 JSON 对象:{text[:200]!r}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(candidate[start:])
    except json.JSONDecodeError as exc:
        raise JsonOutputError(f"JSON 解析失败:{exc};原文:{text[:200]!r}") from exc
    if not isinstance(obj, dict):
        raise JsonOutputError(f"JSON 不是对象:{text[:200]!r}")
    return obj


def parse_json_output[T: BaseModel](text: str, schema: type[T]) -> T:
    """提取 JSON 并按 schema 校验;任何失败统一抛 JsonOutputError。"""
    try:
        return schema.model_validate(extract_json_object(text))
    except ValidationError as exc:
        raise JsonOutputError(f"输出校验失败:{exc}") from exc
