"""对话调用入口:config 通道契约的唯一拼装处,PII 脱敏/回填的唯一边界。

- token(auth)经 config 传入图,绝不进入 prompt 或 LLM 可见的工具参数。
- 入站:用户消息按会话 pii_map 脱敏后才进图;映射随 state 持久化(checkpointer)。
- 出站:最终回复按 pii_map 回填真实值,脱敏对用户透明。
- 失控循环由 recursion_limit 兜底,超限给用户降级话术并记录日志。
"""

import logging
import uuid

from langgraph.errors import GraphRecursionError

from bank_agent.auth.tokens import AuthContext
from bank_agent.composition import CompositionRoot
from bank_agent.pii import mask_text, rehydrate
from bank_agent.prompts import DEGRADED_MESSAGE

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 25


async def invoke_chat(
    root: CompositionRoot,
    message: str,
    auth: AuthContext,
    thread_id: str | None = None,
) -> dict:
    thread_id = thread_id or uuid.uuid4().hex

    # 续聊:取出既有会话的 PII 映射,保证同一会话占位符编号稳定
    prior = await root.graph.aget_state({"configurable": {"thread_id": thread_id}})
    pii_map: dict[str, str] = dict(prior.values.get("pii_map", {}))

    masked = mask_text(message, pii_map)
    config = {
        "recursion_limit": RECURSION_LIMIT,
        "configurable": {
            "thread_id": thread_id,
            "auth": auth,
            "tool_provider": root.tool_provider,
            "pii_map": pii_map,  # 工具层共享同一份映射:还原入参、脱敏结果
        },
    }
    try:
        result = await root.graph.ainvoke(
            {"messages": [("user", masked)], "pii_map": pii_map}, config=config
        )
    except GraphRecursionError:
        logger.error("图执行超过步数上限 %d,返回降级话术", RECURSION_LIMIT)
        return {"thread_id": thread_id, "reply": DEGRADED_MESSAGE, "route": ""}
    return {
        "thread_id": thread_id,
        "reply": rehydrate(result["messages"][-1].content, pii_map),
        "route": result.get("route", ""),
    }
