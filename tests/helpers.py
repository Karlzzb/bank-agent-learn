"""测试辅助:认证身份签发 + 预录脚本消息的构造。

route / tool_call 是 ScriptedChatModel 脚本的两种基本条目,各接缝测试共用。
"""

import json

from langchain_core.messages import AIMessage

from bank_agent.auth.scopes import ALL_SCOPES
from bank_agent.auth.tokens import AuthContext, issue_token, verify_token
from bank_agent.config import Settings

_SETTINGS = Settings()


def make_auth(customer_id: str, scopes: frozenset[str] | set[str] | None = None) -> AuthContext:
    """签 token 并验签,得到与生产一致的 AuthContext。"""
    token = issue_token(_SETTINGS, customer_id, scopes if scopes is not None else ALL_SCOPES)
    return verify_token(_SETTINGS, token)


def auth_headers(customer_id: str, scopes: frozenset[str] | set[str] | None = None) -> dict:
    """HTTP 接缝用:Bearer 头。"""
    return {"Authorization": f"Bearer {make_auth(customer_id, scopes).token}"}


def route(target: str, **extra) -> AIMessage:
    """预录一条 Coordinator 的结构化路由输出。"""
    return AIMessage(content=json.dumps({"target": target, **extra}, ensure_ascii=False))


def tool_call(name: str, args: dict, call_id: str = "tc1") -> AIMessage:
    """预录一条领域子图的工具调用。"""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )
