"""Edge 中间件栈:请求 ID、访问日志、限流。

限流用很小的阈值(每分钟 3 次)验证 429 拦截与按客户分桶;
healthz 不限流(探活不能被业务流量挤掉)。
"""

import logging

import httpx
from langchain_core.messages import AIMessage

from bank_agent.api import create_app
from bank_agent.composition import build_for_test
from bank_agent.config import Settings
from bank_agent.testing.fake_model import ScriptedChatModel
from tests.helpers import auth_headers, route, tool_call


def make_client(model: ScriptedChatModel, db_path: str, **settings_overrides) -> httpx.AsyncClient:
    settings = Settings(bank_db_path=db_path, **settings_overrides)
    root = build_for_test(model, db_path, settings=settings)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(root)), base_url="http://test"
    )


def balance_script() -> list[AIMessage]:
    return [
        route("accounts", rationale="查余额"),
        tool_call("query_balance", {}),
        AIMessage(content="您的储蓄账户余额为 12800.50 元。"),
    ]


async def test_request_id_header_on_success_and_error(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=balance_script())
    async with make_client(model, db_path) as client:
        ok = await client.post("/chat", json={"message": "查余额"}, headers=auth_headers("C001"))
        assert ok.status_code == 200
        assert ok.headers["X-Request-ID"]

        unauthorized = await client.post("/chat", json={"message": "查余额"})
        assert unauthorized.status_code == 401
        assert unauthorized.headers["X-Request-ID"]  # 错误响应同样带请求 ID
        assert ok.headers["X-Request-ID"] != unauthorized.headers["X-Request-ID"]


async def test_access_log_contains_request_context(seeded_db, caplog):
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=balance_script())
    with caplog.at_level(logging.INFO, logger="bank_agent.access"):
        async with make_client(model, db_path) as client:
            resp = await client.post(
                "/chat", json={"message": "查余额"}, headers=auth_headers("C001")
            )
    assert resp.status_code == 200
    record = next(r for r in caplog.records if r.name == "bank_agent.access")
    assert resp.headers["X-Request-ID"] in record.getMessage()
    assert "POST /chat -> 200" in record.getMessage()
    assert "customer=C001" in record.getMessage()


async def test_rate_limit_blocks_burst_from_single_customer(seeded_db):
    """单用户刷后端:超过阈值后第 4 次请求被 429 拦下,且换客户不受影响。"""
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=balance_script() * 4)
    async with make_client(model, db_path, rate_limit_per_minute=3) as client:
        headers = auth_headers("C001")
        for _ in range(3):
            resp = await client.post("/chat", json={"message": "查余额"}, headers=headers)
            assert resp.status_code == 200
        blocked = await client.post("/chat", json={"message": "查余额"}, headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "请求过于频繁,请稍后再试"
        assert blocked.headers["X-Request-ID"]

        # 按 customer_id 分桶:C002 的额度独立,不受 C001 刷爆影响
        other = await client.post("/chat", json={"message": "查余额"}, headers=auth_headers("C002"))
        assert other.status_code == 200


async def test_healthz_not_rate_limited(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=[])
    async with make_client(model, db_path, rate_limit_per_minute=1) as client:
        for _ in range(5):
            assert (await client.get("/healthz")).status_code == 200
