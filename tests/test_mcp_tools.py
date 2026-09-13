"""接缝 2:MCP Server 工具与 mock 银行核心。

对种子 SQLite 库直接断言工具输入输出与写操作落库结果;
MCP Server 经 fastmcp 内存客户端调用(不起进程、不占端口)。
内存传输没有 HTTP 头,测试通过 monkeypatch _current_mcp_token 注入调用方身份,
其余认证/授权逻辑与生产路径完全一致。
"""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlmodel import Session

from bank_agent.core.models import Customer, ServiceRequest
from bank_agent.mcp_servers import common
from bank_agent.mcp_servers.accounts import create_server as create_accounts_server
from bank_agent.mcp_servers.service import create_server as create_service_server
from bank_agent.mcp_servers.transactions import create_server as create_transactions_server
from tests.helpers import make_auth


def as_customer(monkeypatch, customer_id: str, scopes=None) -> None:
    """以指定客户身份调用 MCP 工具(等价于 HTTP 请求带对应 Bearer token)。"""
    auth = make_auth(customer_id, scopes)
    monkeypatch.setattr(common, "_current_mcp_token", lambda: auth.token)


async def test_query_balance_all_accounts(seeded_db, monkeypatch):
    db_path, _ = seeded_db
    as_customer(monkeypatch, "C001")
    async with Client(create_accounts_server(db_path)) as client:
        result = await client.call_tool("query_balance", {})
    balances = {a["account_id"]: a["balance"] for a in result.data["accounts"]}
    assert balances == {"A001": 12800.50, "A002": 3200.00}


async def test_query_balance_unknown_account_returns_error(seeded_db, monkeypatch):
    db_path, _ = seeded_db
    as_customer(monkeypatch, "C001")
    async with Client(create_accounts_server(db_path)) as client:
        result = await client.call_tool("query_balance", {"account_id": "A999"})
    assert "error" in result.data


async def test_list_transactions(seeded_db, monkeypatch):
    db_path, _ = seeded_db
    as_customer(monkeypatch, "C001")
    async with Client(create_transactions_server(db_path)) as client:
        result = await client.call_tool("list_transactions", {"account_id": "A001", "limit": 2})
    txns = result.data["transactions"]
    assert len(txns) == 2
    assert txns[0]["transaction_id"] == "T001"  # 按时间倒序


async def test_get_transaction_detail(seeded_db, monkeypatch):
    db_path, _ = seeded_db
    as_customer(monkeypatch, "C001")
    async with Client(create_transactions_server(db_path)) as client:
        result = await client.call_tool("get_transaction_detail", {"transaction_id": "T002"})
    assert result.data["counterparty"] == "某公司"
    assert result.data["amount"] == 15000.00


async def test_request_statement_persists_service_request(seeded_db, monkeypatch):
    db_path, engine = seeded_db
    as_customer(monkeypatch, "C001")
    async with Client(create_transactions_server(db_path)) as client:
        result = await client.call_tool(
            "request_statement", {"account_id": "A001", "period": "2026-08"}
        )
    assert result.data["status"] == "submitted"
    with Session(engine) as session:
        req = session.get(ServiceRequest, result.data["request_id"])
    assert req is not None
    assert req.kind == "statement"
    assert req.payload == {"account_id": "A001", "period": "2026-08"}


async def test_change_address_persists(seeded_db, monkeypatch):
    db_path, engine = seeded_db
    as_customer(monkeypatch, "C001")
    async with Client(create_service_server(db_path)) as client:
        result = await client.call_tool(
            "change_address", {"new_address": "上海市浦东新区世纪大道 100 号"}
        )
    assert result.data["address"] == "上海市浦东新区世纪大道 100 号"
    with Session(engine) as session:
        customer = session.get(Customer, "C001")
    assert customer.address == "上海市浦东新区世纪大道 100 号"


async def test_request_cheque_book_persists(seeded_db, monkeypatch):
    db_path, engine = seeded_db
    as_customer(monkeypatch, "C001")
    async with Client(create_service_server(db_path)) as client:
        result = await client.call_tool("request_cheque_book", {"account_id": "A002"})
    assert result.data["kind"] == "cheque_book"
    with Session(engine) as session:
        req = session.get(ServiceRequest, result.data["request_id"])
    assert req is not None and req.customer_id == "C001"


async def test_update_kyc_persists(seeded_db, monkeypatch):
    db_path, engine = seeded_db
    as_customer(monkeypatch, "C001")
    async with Client(create_service_server(db_path)) as client:
        result = await client.call_tool("update_kyc", {"phone": "13900002222"})
    assert result.data["kyc_status"] == "verified"
    with Session(engine) as session:
        customer = session.get(Customer, "C001")
    assert customer.phone == "13900002222"
    assert customer.kyc_updated_at is not None


async def test_other_customers_account_not_visible(seeded_db, monkeypatch):
    """C002 的 token 查 C001 的账户:按"不存在"处理,不泄露他人账户存在性。"""
    db_path, _ = seeded_db
    as_customer(monkeypatch, "C002")
    async with Client(create_accounts_server(db_path)) as client:
        result = await client.call_tool("query_balance", {"account_id": "A001"})
    assert "error" in result.data


async def test_missing_token_rejected(seeded_db, monkeypatch):
    """无 token 的调用被 MCP 侧直接拒绝。"""
    db_path, _ = seeded_db
    monkeypatch.setattr(common, "_current_mcp_token", lambda: None)
    async with Client(create_accounts_server(db_path)) as client:
        with pytest.raises(ToolError):
            await client.call_tool("query_balance", {})


async def test_invalid_token_rejected(seeded_db, monkeypatch):
    db_path, _ = seeded_db
    monkeypatch.setattr(common, "_current_mcp_token", lambda: "不是合法token")
    async with Client(create_accounts_server(db_path)) as client:
        with pytest.raises(ToolError):
            await client.call_tool("query_balance", {})


async def test_insufficient_scope_rejected(seeded_db, monkeypatch):
    """恶意/异常调用:token 只有 accounts:read,试图改地址,被 MCP 侧 scope 校验拦下。"""
    db_path, engine = seeded_db
    as_customer(monkeypatch, "C001", {"accounts:read"})
    async with Client(create_service_server(db_path)) as client:
        with pytest.raises(ToolError, match="权限不足"):
            await client.call_tool("change_address", {"new_address": "北京市海淀区中关村 1 号"})
    with Session(engine) as session:
        assert session.get(Customer, "C001").address == "北京市朝阳区建国路 1 号"


async def test_tool_schemas_hide_injected_params(seeded_db):
    """session / customer_id 由 MCP 层注入,不得出现在 LLM 可见的工具 schema。"""
    db_path, _ = seeded_db
    for create in (create_accounts_server, create_transactions_server, create_service_server):
        async with Client(create(db_path)) as client:
            tools = await client.list_tools()
        assert tools, create
        for tool in tools:
            properties = tool.input_schema.get("properties", {})
            assert "session" not in properties, tool.name
            assert "customer_id" not in properties, tool.name
