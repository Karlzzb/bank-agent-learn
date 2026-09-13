"""图构建:Coordinator + 三个领域子图,一跳往返,子图异常降级。

结构:START → coordinator → (Command) 领域节点 → END
                          (Command) END(clarify 反问)
领域节点内调用编译好的子图;子图异常由本层捕获,给用户降级话术并记录日志(E7 起进 Langfuse trace)。
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from bank_agent.graph.coordinator import make_coordinator_node
from bank_agent.graph.subgraphs import build_domain_subgraph
from bank_agent.prompts import DEGRADED_MESSAGE
from bank_agent.state import DOMAINS, BankState

logger = logging.getLogger(__name__)


def make_domain_runner(domain: str, subgraph):
    async def run(state: BankState, config) -> dict:
        try:
            result = await subgraph.ainvoke(
                {"messages": state["messages"], "tool_steps": 0},
                config={"configurable": config.get("configurable", {})},
            )
        except Exception:
            logger.exception("子图 %s 执行异常,返回降级话术", domain)
            return {"messages": [AIMessage(DEGRADED_MESSAGE)]}
        final = result["messages"][-1]
        return {
            "messages": [AIMessage(final.content)] if not isinstance(final, AIMessage) else [final]
        }

    return run


def build_graph(model: BaseChatModel, checkpointer=None):
    """编译完整图。checkpointer 缺省用内存版(E4 换成 SQLite 持久化)。"""
    graph = StateGraph(BankState)
    graph.add_node("coordinator", make_coordinator_node(model))
    for domain in DOMAINS:
        subgraph = build_domain_subgraph(domain, model)
        graph.add_node(domain, make_domain_runner(domain, subgraph))
        graph.add_edge(domain, END)
    graph.add_edge(START, "coordinator")
    return graph.compile(checkpointer=checkpointer or MemorySaver())
