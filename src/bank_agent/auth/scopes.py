"""scope 定义:每个工具声明所需 scope,两个接缝(HTTP/MCP)共用同一张表。

授权模型:token 携带 scope 集合;MCP 侧每个工具调用校验所需 scope,
即使 LLM 被诱导发起越权调用,也在工具层被拦下。
"""

# 全部业务 scope;mock IdP 默认给演示客户签全量
ALL_SCOPES = frozenset(
    {
        "accounts:read",
        "transactions:read",
        "transactions:write",
        "service:write",
    }
)

# 工具名 -> 所需 scope(唯一事实来源,Direct 提供者与 MCP Server 共用)
TOOL_SCOPES = {
    "query_balance": "accounts:read",
    "list_transactions": "transactions:read",
    "get_transaction_detail": "transactions:read",
    "request_statement": "transactions:write",
    "change_address": "service:write",
    "request_cheque_book": "service:write",
    "update_kyc": "service:write",
}


def required_scope(tool_name: str) -> str:
    """查工具所需 scope;未登记的工具按最高敏感级别拒绝(不在表内即不可调用)。"""
    try:
        return TOOL_SCOPES[tool_name]
    except KeyError as exc:
        raise PermissionError(f"工具未登记授权范围,拒绝调用:{tool_name}") from exc


def check_scope(tool_name: str, granted: frozenset[str]) -> None:
    """校验 scope,不足抛 PermissionError(由调用层转成 403/工具错误)。"""
    need = required_scope(tool_name)
    if need not in granted:
        raise PermissionError(f"权限不足:{tool_name} 需要 {need}")
