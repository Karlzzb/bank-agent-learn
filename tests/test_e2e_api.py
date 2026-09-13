"""接缝 1:FastAPI HTTP 层端到端。

组合根注入确定性假 chat model(预录路由决策与工具调用序列),
经 HTTP 驱动完整图:路由 → 子图 → 工具 → mock 银行 → 响应。
覆盖:多轮对话、一次对话连续办理多业务、clarify 反问、解析失败兜底、子图异常降级。
真实落库直接对种子 SQLite 断言。
"""

import json

import httpx
from langchain_core.messages import AIMessage
from sqlmodel import Session, select

from bank_agent.api import create_app
from bank_agent.composition import build_for_test
from bank_agent.core.models import Customer, ServiceRequest
from bank_agent.prompts import CLARIFY_FALLBACK, DEGRADED_MESSAGE
from bank_agent.testing.fake_model import ScriptedChatModel


def route(target: str, **extra) -> AIMessage:
    return AIMessage(content=json.dumps({"target": target, **extra}, ensure_ascii=False))


def tool_call(name: str, args: dict, call_id: str = "tc1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def make_client(model: ScriptedChatModel, db_path: str) -> httpx.AsyncClient:
    root = build_for_test(model, db_path)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(root)), base_url="http://test"
    )


async def test_balance_then_change_address_in_one_thread(seeded_db):
    db_path, engine = seeded_db
    model = ScriptedChatModel(
        script=[
            route("accounts", rationale="用户要查余额"),
            tool_call("query_balance", {}),
            AIMessage(content="您的储蓄账户余额为 12800.50 元。"),
            route("service", rationale="用户要改地址"),
            tool_call("change_address", {"new_address": "上海市浦东新区世纪大道 100 号"}),
            AIMessage(content="已为您修改联系地址。"),
        ]
    )
    async with make_client(model, db_path) as client:
        resp1 = await client.post("/chat", json={"message": "帮我查一下余额"})
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert body1["route"] == "accounts"
        assert "12800.50" in body1["reply"]

        resp2 = await client.post(
            "/chat",
            json={
                "message": "把地址改成上海市浦东新区世纪大道 100 号",
                "thread_id": body1["thread_id"],
            },
        )
        body2 = resp2.json()
        assert body2["thread_id"] == body1["thread_id"]
        assert body2["route"] == "service"
        assert "已为您修改联系地址" in body2["reply"]

    # 写操作真实落库:改地址后再查确实变了
    with Session(engine) as session:
        assert session.get(Customer, "C001").address == "上海市浦东新区世纪大道 100 号"


async def test_clarify_is_first_class_route(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(
        script=[route("clarify", rationale="意图不明", question="请问您要办理哪类业务?")]
    )
    async with make_client(model, db_path) as client:
        resp = await client.post("/chat", json={"message": "你好"})
    body = resp.json()
    assert body["route"] == "clarify"
    assert body["reply"] == "请问您要办理哪类业务?"


async def test_unparseable_route_output_falls_back_to_clarify(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=[AIMessage(content="这不是 JSON 输出")])
    async with make_client(model, db_path) as client:
        resp = await client.post("/chat", json={"message": "随便说点啥"})
    body = resp.json()
    assert body["route"] == "clarify"
    assert body["reply"] == CLARIFY_FALLBACK


class _FailingProvider:
    async def tools_for(self, domain: str, customer_id: str):
        raise RuntimeError("MCP 连接失败")


async def test_subgraph_failure_returns_degraded_message(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=[route("accounts", rationale="查余额")])
    root = build_for_test(model, db_path)
    root.tool_provider = _FailingProvider()  # 模拟 MCP 层整体故障
    app = create_app(root)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/chat", json={"message": "查余额"})
    body = resp.json()
    assert body["reply"] == DEGRADED_MESSAGE


async def test_tool_loop_stops_at_max_steps(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(
        script=[route("accounts", rationale="查余额")]
        + [tool_call("query_balance", {}, call_id=f"tc{i}") for i in range(6)]
    )
    async with make_client(model, db_path) as client:
        resp = await client.post("/chat", json={"message": "查余额"})
    assert resp.json()["reply"] == DEGRADED_MESSAGE


async def test_all_six_businesses_in_one_thread(seeded_db):
    """六个业务全部经 HTTP 对话完成(同一会话 5 轮,覆盖 >4 轮连续办理)。"""
    db_path, engine = seeded_db
    model = ScriptedChatModel(
        script=[
            # 1. 交易明细
            route("transactions", rationale="查交易"),
            tool_call("list_transactions", {"account_id": "A001", "limit": 3}),
            AIMessage(content="最近交易:星巴克 -58.00 元,工资入账 15000.00 元。"),
            # 2. 结单申请
            route("transactions", rationale="申请结单"),
            tool_call("request_statement", {"account_id": "A001", "period": "2026-08"}),
            AIMessage(content="已为您提交 2026-08 结单申请。"),
            # 3. 支票簿申请
            route("service", rationale="申请支票簿"),
            tool_call("request_cheque_book", {"account_id": "A002"}),
            AIMessage(content="支票簿申请已提交。"),
            # 4. KYC 更新
            route("service", rationale="更新手机号"),
            tool_call("update_kyc", {"phone": "13911112222"}),
            AIMessage(content="手机号已更新。"),
            # 5. 单笔交易明细(第 5 轮,回归:多轮对话不应被步数兜底误杀)
            route("transactions", rationale="查单笔交易"),
            tool_call("get_transaction_detail", {"transaction_id": "T002"}),
            AIMessage(content="该笔交易为某公司工资入账 15000.00 元。"),
        ]
    )
    turns = [
        ("看看我 A001 账户最近的交易", "transactions", "星巴克"),
        ("帮我申请 A001 今年 8 月的结单", "transactions", "结单"),
        ("给 A002 申请一个支票簿", "service", "支票簿"),
        ("把我的手机号更新为 13911112222", "service", "手机号"),
        ("T002 那笔交易是什么", "transactions", "15000.00"),
    ]
    async with make_client(model, db_path) as client:
        thread_id = None
        for message, expected_route, expected_in_reply in turns:
            payload = {"message": message}
            if thread_id:
                payload["thread_id"] = thread_id
            body = (await client.post("/chat", json=payload)).json()
            assert body["route"] == expected_route, message
            assert expected_in_reply in body["reply"], message
            thread_id = body["thread_id"]

    # 写操作真实落库
    with Session(engine) as session:
        assert session.get(Customer, "C001").phone == "13911112222"
        kinds = set(session.exec(select(ServiceRequest.kind)).all())
    assert kinds == {"statement", "cheque_book"}
