"""对话调用入口:config 通道契约的唯一拼装处。

thread_id / customer_id / tool_provider 经 config 注入图(E3 起 token 也走这里);
失控循环由 recursion_limit 兜底,超限给用户降级话术并记录日志。
"""

import logging
import uuid

from langgraph.errors import GraphRecursionError

from bank_agent.composition import CompositionRoot
from bank_agent.core.seed import DEMO_CUSTOMER_ID
from bank_agent.prompts import DEGRADED_MESSAGE

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 25


async def invoke_chat(
    root: CompositionRoot,
    message: str,
    thread_id: str | None = None,
    customer_id: str = DEMO_CUSTOMER_ID,
) -> dict:
    thread_id = thread_id or uuid.uuid4().hex
    config = {
        "recursion_limit": RECURSION_LIMIT,
        "configurable": {
            "thread_id": thread_id,
            "customer_id": customer_id,
            "tool_provider": root.tool_provider,
        },
    }
    try:
        result = await root.graph.ainvoke({"messages": [("user", message)]}, config=config)
    except GraphRecursionError:
        logger.error("图执行超过步数上限 %d,返回降级话术", RECURSION_LIMIT)
        return {"thread_id": thread_id, "reply": DEGRADED_MESSAGE, "route": ""}
    return {
        "thread_id": thread_id,
        "reply": result["messages"][-1].content,
        "route": result.get("route", ""),
    }
