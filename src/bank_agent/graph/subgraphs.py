"""领域子图:各自完整的 ReAct 循环,独立 system prompt,独立工具集。

tool_steps / memory_context 是子图私有键,不泄漏到父图状态。
工具集在节点内从 config 通道解析(tool_provider + customer_id),不进 prompt。
"""

import json
import logging
from typing import Annotated

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from bank_agent.prompts import DEGRADED_MESSAGE, DOMAIN_PROMPTS
from bank_agent.tool_providers import resolve_tools

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 5


class DomainState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_steps: int  # 私有键:仅本子图读写
    memory_context: str  # 私有键:跨会话偏好注入文本,由父图 runner 写入


def build_domain_subgraph(domain: str, model: BaseChatModel):
    async def agent(state: DomainState, config) -> dict:
        tools = await resolve_tools(config, domain)
        bound = model.bind_tools(tools)
        prompt = [SystemMessage(DOMAIN_PROMPTS[domain])]
        if state.get("memory_context"):
            prompt.append(SystemMessage(state["memory_context"]))
        response = await bound.ainvoke([*prompt, *state["messages"]])
        return {"messages": [response]}

    async def call_tools(state: DomainState, config) -> dict:
        tools = {t.name: t for t in await resolve_tools(config, domain)}
        last = state["messages"][-1]
        results = []
        for call in last.tool_calls:
            tool = tools.get(call["name"])
            if tool is None:
                content = json.dumps({"error": f"未知工具:{call['name']}"}, ensure_ascii=False)
            else:
                try:
                    content = await tool.ainvoke(call["args"])
                except Exception as exc:
                    logger.warning("工具 %s 调用失败:%s", call["name"], exc)
                    content = json.dumps({"error": f"工具调用失败:{exc}"}, ensure_ascii=False)
            results.append(ToolMessage(content=str(content), tool_call_id=call["id"]))
        return {"messages": results, "tool_steps": state.get("tool_steps", 0) + 1}

    def should_continue(state: DomainState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END
        if state.get("tool_steps", 0) >= MAX_TOOL_STEPS:
            return "give_up"
        return "call_tools"

    async def give_up(state: DomainState) -> dict:
        logger.warning("子图 %s 工具步数超过上限 %d", domain, MAX_TOOL_STEPS)
        return {"messages": [AIMessage(DEGRADED_MESSAGE)]}

    graph = StateGraph(DomainState)
    graph.add_node("agent", agent)
    graph.add_node("call_tools", call_tools)
    graph.add_node("give_up", give_up)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", should_continue, {"call_tools": "call_tools", "give_up": "give_up", END: END}
    )
    graph.add_edge("call_tools", "agent")
    graph.add_edge("give_up", END)
    return graph.compile()
