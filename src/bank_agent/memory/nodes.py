"""会话记忆节点:会话内摘要压缩 + 跨会话偏好读写(LangGraph store)。

- manage_context:消息数超阈值时,把最旧的一段交给 LLM 压缩成摘要;
  摘要原位替换最早一条消息(位置不变,LLM 看到的顺序正确),其余旧消息移除。
  切口对齐到 HumanMessage 边界,避免 AIMessage(tool_calls)与 ToolMessage 被拆开。
- save_memory:用户消息含触发词时,用 LLM 提取偏好写入 store(命名空间按客户隔离)。
  输入是已脱敏文本;含 PII 占位符的提取结果一律丢弃——占位符是会话作用域标记,
  落到跨会话 store 里既无意义也无法回填。
- load_preferences / format_preferences:由父图的领域 runner 在调子图前调用,
  偏好渲染成 system 文本经子图私有键 memory_context 注入(见 graph/builder.py)。
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from bank_agent.auth.tokens import AuthContext
from bank_agent.json_output import JsonOutputError, parse_json_output
from bank_agent.pii import contains_placeholder
from bank_agent.prompts import MEMORY_EXTRACT_PROMPT, SUMMARY_PROMPT
from bank_agent.state import BankState

logger = logging.getLogger(__name__)

# 用户消息含任一触发词才调用 LLM 提取偏好,其余轮次零额外成本
MEMORY_TRIGGER_WORDS = ("记住", "常用", "默认", "以后", "偏好")


def profile_namespace(customer_id: str) -> tuple[str, str]:
    """长期记忆的命名空间:按客户隔离,跨会话共享。"""
    return ("profiles", customer_id)


class _PreferenceExtraction(BaseModel):
    preferences: dict[str, str] = Field(default_factory=dict, validation_alias="items")


def _content_text(response: AIMessage) -> str:
    content = response.content
    return content if isinstance(content, str) else str(content)


def make_context_node(model: BaseChatModel, max_messages: int, keep_recent: int):
    async def manage_context(state: BankState, config) -> dict:
        messages = state["messages"]
        if len(messages) <= max_messages:
            return {}
        cut = len(messages) - keep_recent
        while cut < len(messages) and not isinstance(messages[cut], HumanMessage):
            cut += 1
        if cut == 0 or cut >= len(messages):
            return {}  # 找不到安全切口:本轮不压缩,等下一轮
        old = messages[:cut]
        response = await model.ainvoke([SystemMessage(SUMMARY_PROMPT), *old])
        head, *tail = old
        logger.info(
            "会话消息数 %d 超阈值 %d,最旧 %d 条压缩为摘要", len(messages), max_messages, len(old)
        )
        return {
            "messages": [
                SystemMessage(f"【前情摘要】{_content_text(response)}", id=head.id),
                *[RemoveMessage(id=m.id) for m in tail],
            ]
        }

    return manage_context


def make_memory_node(model: BaseChatModel):
    async def save_memory(state: BankState, config, *, runtime: Runtime) -> dict:
        store: BaseStore | None = runtime.store
        if store is None:
            return {}
        user_text = next(
            (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), ""
        )
        if not isinstance(user_text, str) or not any(w in user_text for w in MEMORY_TRIGGER_WORDS):
            return {}
        response = await model.ainvoke(
            [SystemMessage(MEMORY_EXTRACT_PROMPT), HumanMessage(user_text)]
        )
        try:
            extracted = parse_json_output(_content_text(response), _PreferenceExtraction)
        except JsonOutputError:
            logger.warning("偏好提取输出解析失败,跳过;原始输出:%r", _content_text(response)[:500])
            return {}
        # 占位符是会话级映射,跨会话无意义:含占位符的条目丢弃,不污染 store
        items = {
            k: v
            for k, v in extracted.preferences.items()
            if not contains_placeholder(k) and not contains_placeholder(v)
        }
        dropped = len(extracted.preferences) - len(items)
        if dropped:
            logger.info("丢弃 %d 条含 PII 占位符的偏好提取结果", dropped)
        if not items:
            return {}
        auth: AuthContext = config["configurable"]["auth"]
        for key, value in items.items():
            await store.aput(profile_namespace(auth.customer_id), key, {"value": value})
        logger.info("已记住用户 %s 的 %d 条偏好", auth.customer_id, len(items))
        return {}

    return save_memory


async def load_preferences(store: BaseStore, customer_id: str) -> dict[str, str]:
    """读出某客户的全部长期偏好(键→值)。"""
    items = await store.asearch(profile_namespace(customer_id))
    return {item.key: str(item.value.get("value", "")) for item in items}


def format_preferences(preferences: dict[str, str]) -> str:
    """偏好渲染为注入 prompt 的一行 system 文本;无偏好返回空串。"""
    if not preferences:
        return ""
    text = ";".join(f"{k}:{v}" for k, v in preferences.items())
    return f"已知用户偏好:{text}(办理业务时可直接使用,无需用户重复说明)"
