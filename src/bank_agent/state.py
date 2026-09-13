"""多智能体共享状态模型。

写者与 reducer 规则:
- messages:共享键,所有节点只追加,reducer 为 add_messages。
- route / rationale:唯一写者 Coordinator(每次路由覆盖)。
- pii_map:PII 占位符→真实值映射,唯一写者是调图入口(chat.invoke_chat),
  图内节点不写;工具层经 config 读取同一份映射做还原/脱敏。
子图私有键(如 tool_steps)定义在子图自己的 schema 里,不进入本状态。
防循环兜底不在本状态:一跳由图结构保证,失控循环由调图时的 recursion_limit 兜底。
"""

from typing import Annotated, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

DOMAINS = ("accounts", "transactions", "service")
RouteTarget = Literal["accounts", "transactions", "service", "clarify"]


class BankState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    route: RouteTarget
    rationale: str
    pii_map: dict[str, str]
