"""路由决策的结构化解析:工业级 JSON 提取 + pydantic 校验。

LLM 输出不可信:可能带代码围栏、前后多余文本、缺字段。
本模块负责把原始输出解析成 RouteDecision,失败抛 RouteParseError,
由 Coordinator 决定降级策略(不在这里做业务决策)。
"""

import json
import re

from pydantic import BaseModel, ValidationError

from bank_agent.state import RouteTarget

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class RouteDecision(BaseModel):
    target: RouteTarget
    rationale: str = ""
    question: str | None = None  # 仅 target=clarify 时有意义


class RouteParseError(Exception):
    """路由输出无法解析。"""


def _extract_json(text: str) -> dict:
    """从原始文本中提取第一个完整 JSON 对象。"""
    fenced = _FENCE_RE.search(text)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    if start == -1:
        raise RouteParseError(f"输出中找不到 JSON 对象:{text[:200]!r}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(candidate[start:])
    except json.JSONDecodeError as exc:
        raise RouteParseError(f"JSON 解析失败:{exc};原文:{text[:200]!r}") from exc
    if not isinstance(obj, dict):
        raise RouteParseError(f"JSON 不是对象:{text[:200]!r}")
    return obj


def parse_route_decision(text: str) -> RouteDecision:
    """解析 LLM 的路由输出;失败抛 RouteParseError。"""
    try:
        return RouteDecision.model_validate(_extract_json(text))
    except ValidationError as exc:
        raise RouteParseError(f"路由决策校验失败:{exc}") from exc
