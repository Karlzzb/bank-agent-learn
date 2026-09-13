"""Coordinator 节点:结构化路由,clarify 是一等路由目标。

只做路由,不直接回答业务问题;Coordinator ↔ 子 Agent 一跳往返由图结构保证
(coordinator → 领域节点 → END,无回边);失控循环由调图时的 recursion_limit 兜底。
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import Command

from bank_agent.prompts import CLARIFY_FALLBACK, COORDINATOR_PROMPT
from bank_agent.routing import RouteDecision, RouteParseError, parse_route_decision
from bank_agent.state import BankState

logger = logging.getLogger(__name__)


def make_coordinator_node(model: BaseChatModel):
    async def coordinator(state: BankState, config) -> Command:
        response = await model.ainvoke([SystemMessage(COORDINATOR_PROMPT), *state["messages"]])
        raw = response.content if isinstance(response.content, str) else str(response.content)
        try:
            decision = parse_route_decision(raw)
        except RouteParseError:
            logger.warning("路由输出解析失败,降级为 clarify;原始输出:%r", raw[:500])
            decision = RouteDecision(target="clarify", rationale="路由输出无法解析")

        update: dict = {"route": decision.target, "rationale": decision.rationale}
        if decision.target == "clarify":
            question = decision.question or CLARIFY_FALLBACK
            update["messages"] = [AIMessage(question)]
            return Command(goto=END, update=update)
        return Command(goto=decision.target, update=update)

    return coordinator
