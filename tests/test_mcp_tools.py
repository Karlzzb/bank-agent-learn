"""接缝 2:MCP Server 工具与 mock 银行核心。

对种子 SQLite 库直接断言工具输入输出与写操作落库结果;
MCP Server 经 fastmcp 内存客户端调用(不起进程、不占端口)。
"""

from fastmcp import Client
from sqlmodel import Session

from bank_agent.core.models import Customer, ServiceRequest
from bank_agent.mcp_servers.accounts import create_server as create_accounts_server
from bank_agent.mcp_servers.service import create_server as create_service_server
from bank_agent.mcp_servers.transactions import create_server as create_transactions_server


async def test_query_balance_all_accounts(seeded_db):
    db_path, _ = seeded_db
    async with Client(create_accounts_server(db_path)) as client:
        result = await client.call_tool("query_balance", {"customer_id": "C001"})
    balances = {a["account_id"]: a["balance"] for a in result.data["accounts"]}
    assert balances == {"A001": 12800.50, "A002": 3200.00}


async def test_query_balance_unknown_account_returns_error(seeded_db):
    db_path, _ = seeded_db
    async with Client(create_accounts_server(db_path)) as client:
        result = await client.call_tool(
            "query_balance", {"customer_id": "C001", "account_id": "A999"}
        )
    assert "error" in result.data


async def test_list_transactions(seeded_db):
    db_path, _ = seeded_db
    async with Client(create_transactions_server(db_path)) as client:
        result = await client.call_tool(
            "list_transactions", {"customer_id": "C001", "account_id": "A001", "limit": 2}
        )
    txns = result.data["transactions"]
    assert len(txns) == 2
    assert txns[0]["transaction_id"] == "T001"  # 按时间倒序


async def test_get_transaction_detail(seeded_db):
    db_path, _ = seeded_db
    async with Client(create_transactions_server(db_path)) as client:
        result = await client.call_tool(
            "get_transaction_detail", {"customer_id": "C001", "transaction_id": "T002"}
        )
    assert result.data["counterparty"] == "某公司"
    assert result.data["amount"] == 15000.00


async def test_request_statement_persists_service_request(seeded_db):
    db_path, engine = seeded_db
    async with Client(create_transactions_server(db_path)) as client:
        result = await client.call_tool(
            "request_statement",
            {"customer_id": "C001", "account_id": "A001", "period": "2026-08"},
        )
    assert result.data["status"] == "submitted"
    with Session(engine) as session:
        req = session.get(ServiceRequest, result.data["request_id"])
    assert req is not None
    assert req.kind == "statement"
    assert req.payload == {"account_id": "A001", "period": "2026-08"}


async def test_change_address_persists(seeded_db):
    db_path, engine = seeded_db
    async with Client(create_service_server(db_path)) as client:
        result = await client.call_tool(
            "change_address",
            {"customer_id": "C001", "new_address": "上海市浦东新区世纪大道 100 号"},
        )
    assert result.data["address"] == "上海市浦东新区世纪大道 100 号"
    with Session(engine) as session:
        customer = session.get(Customer, "C001")
    assert customer.address == "上海市浦东新区世纪大道 100 号"


async def test_request_cheque_book_persists(seeded_db):
    db_path, engine = seeded_db
    async with Client(create_service_server(db_path)) as client:
        result = await client.call_tool(
            "request_cheque_book", {"customer_id": "C001", "account_id": "A002"}
        )
    assert result.data["kind"] == "cheque_book"
    with Session(engine) as session:
        req = session.get(ServiceRequest, result.data["request_id"])
    assert req is not None and req.customer_id == "C001"


async def test_update_kyc_persists(seeded_db):
    db_path, engine = seeded_db
    async with Client(create_service_server(db_path)) as client:
        result = await client.call_tool(
            "update_kyc", {"customer_id": "C001", "phone": "13900002222"}
        )
    assert result.data["kyc_status"] == "verified"
    with Session(engine) as session:
        customer = session.get(Customer, "C001")
    assert customer.phone == "13900002222"
    assert customer.kyc_updated_at is not None


async def test_other_customers_account_not_visible(seeded_db):
    db_path, _ = seeded_db
    async with Client(create_accounts_server(db_path)) as client:
        result = await client.call_tool(
            "query_balance", {"customer_id": "C999", "account_id": "A001"}
        )
    assert "error" in result.data


async def test_tool_schemas_hide_session_param(seeded_db):
    """session 由 MCP 层注入,不得出现在工具 schema(经签名反射注入 LLM 可见参数)。"""
    db_path, _ = seeded_db
    for create in (create_accounts_server, create_transactions_server, create_service_server):
        async with Client(create(db_path)) as client:
            tools = await client.list_tools()
        assert tools, create
        for tool in tools:
            assert "session" not in tool.input_schema.get("properties", {}), tool.name
