"""JWT 签发/验签与 scope 校验:纯单元测试,不起服务。"""

import pytest

from bank_agent.auth.scopes import ALL_SCOPES, check_scope
from bank_agent.auth.tokens import AuthError, issue_token, verify_token
from bank_agent.config import Settings

SETTINGS = Settings()


def test_issue_and_verify_roundtrip():
    token = issue_token(SETTINGS, "C001", {"accounts:read"})
    auth = verify_token(SETTINGS, token)
    assert auth.customer_id == "C001"
    assert auth.scopes == frozenset({"accounts:read"})


def test_verify_rejects_garbage():
    with pytest.raises(AuthError):
        verify_token(SETTINGS, "不是token")


def test_verify_rejects_wrong_secret():
    other = Settings(jwt_secret="another-key-with-enough-length-32bytes")
    token = issue_token(other, "C001", ALL_SCOPES)
    with pytest.raises(AuthError):
        verify_token(SETTINGS, token)


def test_verify_rejects_expired():
    token = issue_token(SETTINGS, "C001", ALL_SCOPES, ttl_seconds=-1)
    with pytest.raises(AuthError):
        verify_token(SETTINGS, token)


def test_check_scope_allows_granted():
    check_scope("query_balance", frozenset({"accounts:read"}))


def test_check_scope_denies_missing():
    with pytest.raises(PermissionError, match="权限不足"):
        check_scope("change_address", frozenset({"accounts:read"}))


def test_unregistered_tool_denied():
    """未登记授权范围的工具一律拒绝(默认deny)。"""
    with pytest.raises(PermissionError):
        check_scope("delete_all_accounts", ALL_SCOPES)
