"""图构建:上下文管理 → Coordinator → 领域子图 → 记忆写入,一跳往返,子图异常降级。

结构:START → manage_context → coordinator → (Command) 领域节点 → save_memory → END
                                            (Command) save_memory(clarify 反问)
- manage_context:长会话把最旧消息压缩为摘要(会话内记忆),见 memory/nodes.py。
- save_memory:有触发词时提取跨会话偏好写入 store,其余轮次零成本穿透。
领域节点内调用编译好的子图;子图异常由本层捕获,给用户降级话术并记录日志(E7 起进 Langfuse trace)。
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from bank_agent.graph.coordinator import make_coordinator_node
from bank_agent.graph.subgraphs import build_domain_subgraph
from bank_agent.memory.nodes import (
    format_preferences,
    load_preferences,
    make_context_node,
    make_memory_node,
)
from bank_agent.prompts import DEGRADED_MESSAGE
from bank_agent.state import DOMAINS, BankState

logger = logging.getLogger(__name__)


def make_domain_runner(domain: str, subgraph):
    async def run(state: BankState, config, *, runtime) -> dict:
        # 跨会话偏好在此注入子图输入(私有键 memory_context):办事的是领域子图,
        # 偏好只有到这一层才可执行;Coordinator 只分派,不需要看到偏好。
        memory_context = ""
        store = runtime.store
        if store is not None:
            auth = config["configurable"]["auth"]
            memory_context = format_preferences(await load_preferences(store, auth.customer_id))
        try:
            # config 整体透传:子图运行挂在父 run 下(trace 不碎);
            # metadata 打 agent 标签,Langfuse 里按 observation metadata 归因到领域 Agent
            child_config = dict(config)
            parent_meta = config.get("metadata", {})
            child_config["metadata"] = {
                **parent_meta,
                "agent": domain,
                "langfuse_tags": [*parent_meta.get("langfuse_tags", []), f"agent:{domain}"],
            }
            result = await subgraph.ainvoke(
                {"messages": state["messages"], "tool_steps": 0, "memory_context": memory_context},
                config=child_config,
            )
        except Exception:
            logger.exception("子图 %s 执行异常,返回降级话术", domain)
            return {"messages": [AIMessage(DEGRADED_MESSAGE)]}
        final = result["messages"][-1]
        return {
            "messages": [AIMessage(final.content)] if not isinstance(final, AIMessage) else [final]
        }

    return run


def build_graph(
    model: BaseChatModel,
    checkpointer=None,
    store: BaseStore | None = None,
    *,
    max_history: int,
    keep_recent: int,
):
    """编译完整图。

    checkpointer 缺省内存版(生产经 composition 装配 SQLite,断线续聊);
    store 缺省 None(跨会话偏好读写自动跳过)。
    max_history / keep_recent:会话内摘要阈值与保留最近原文条数,取值唯一来源是
    Settings(composition 装配时传入),此处不设默认值避免多处魔数漂移。
    """
    graph = StateGraph(BankState)
    graph.add_node("manage_context", make_context_node(model, max_history, keep_recent))
    graph.add_node("coordinator", make_coordinator_node(model))
    graph.add_node("save_memory", make_memory_node(model))
    for domain in DOMAINS:
        subgraph = build_domain_subgraph(domain, model)
        graph.add_node(domain, make_domain_runner(domain, subgraph))
        graph.add_edge(domain, "save_memory")
    graph.add_edge(START, "manage_context")
    graph.add_edge("manage_context", "coordinator")
    graph.add_edge("save_memory", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver(), store=store)
