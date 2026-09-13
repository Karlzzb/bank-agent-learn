"""测试认证辅助:按测试所需身份与权限签 token(与生产同一套签发/验签代码)。"""

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
