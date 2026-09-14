"""路由决策的结构化解析:复用统一的 LLM JSON 输出解析。

LLM 输出不可信:可能带代码围栏、前后多余文本、缺字段。
本模块只负责把原始输出解析成 RouteDecision,失败抛 RouteParseError,
由 Coordinator 决定降级策略(不在这里做业务决策)。
"""

from pydantic import BaseModel

from bank_agent.json_output import JsonOutputError, parse_json_output
from bank_agent.state import RouteTarget


class RouteDecision(BaseModel):
    target: RouteTarget
    rationale: str = ""
    question: str | None = None  # 仅 target=clarify 时有意义


class RouteParseError(JsonOutputError):
    """路由输出无法解析。"""


def parse_route_decision(text: str) -> RouteDecision:
    """解析 LLM 的路由输出;失败抛 RouteParseError。"""
    try:
        return parse_json_output(text, RouteDecision)
    except JsonOutputError as exc:
        raise RouteParseError(str(exc)) from exc
