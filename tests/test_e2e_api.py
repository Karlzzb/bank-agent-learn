"""接缝 1:FastAPI HTTP 层端到端。

组合根注入确定性假 chat model(预录路由决策与工具调用序列),
经 HTTP 驱动完整图:认证 → 路由 → 子图 → 工具 → mock 银行 → 响应。
覆盖:多轮对话、一次对话连续办理多业务、clarify 反问、解析失败兜底、子图异常降级、
认证 401 / 授权 403、越权与跨用户隔离、PII 入站脱敏与出站回填。
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
from tests.helpers import auth_headers


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


def llm_visible_text(model: ScriptedChatModel) -> str:
    """历次调用中 LLM 可见的全部文本(prompt 消息 + 工具结果)。"""
    return "\n".join(str(m.content) for call in model.received for m in call)


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
    headers = auth_headers("C001")
    async with make_client(model, db_path) as client:
        resp1 = await client.post("/chat", json={"message": "帮我查一下余额"}, headers=headers)
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
            headers=headers,
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
        resp = await client.post("/chat", json={"message": "你好"}, headers=auth_headers("C001"))
    body = resp.json()
    assert body["route"] == "clarify"
    assert body["reply"] == "请问您要办理哪类业务?"


async def test_unparseable_route_output_falls_back_to_clarify(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=[AIMessage(content="这不是 JSON 输出")])
    async with make_client(model, db_path) as client:
        resp = await client.post(
            "/chat", json={"message": "随便说点啥"}, headers=auth_headers("C001")
        )
    body = resp.json()
    assert body["route"] == "clarify"
    assert body["reply"] == CLARIFY_FALLBACK


class _FailingProvider:
    async def tools_for(self, domain: str, auth, pii_map):
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
        resp = await client.post("/chat", json={"message": "查余额"}, headers=auth_headers("C001"))
    body = resp.json()
    assert body["reply"] == DEGRADED_MESSAGE


async def test_tool_loop_stops_at_max_steps(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(
        script=[route("accounts", rationale="查余额")]
        + [tool_call("query_balance", {}, call_id=f"tc{i}") for i in range(6)]
    )
    async with make_client(model, db_path) as client:
        resp = await client.post("/chat", json={"message": "查余额"}, headers=auth_headers("C001"))
    assert resp.json()["reply"] == DEGRADED_MESSAGE


async def test_all_six_businesses_in_one_thread(seeded_db):
    """六个业务全部经 HTTP 对话完成(同一会话 5 轮,覆盖 >4 轮连续办理)。

    第 4 轮用户报出手机号:入站即脱敏为 [PHONE_1],LLM 只看到占位符;
    工具层还原真实值落库;最终回复回填真实号码,脱敏对用户透明。
    """
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
            # 4. KYC 更新(LLM 只见过占位符,工具入参只能是占位符)
            route("service", rationale="更新手机号"),
            tool_call("update_kyc", {"phone": "[PHONE_1]"}),
            AIMessage(content="手机号已更新为 [PHONE_1]。"),
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
        ("把我的手机号更新为 13911112222", "service", "13911112222"),  # 回复里看到真实号码
        ("T002 那笔交易是什么", "transactions", "15000.00"),
    ]
    async with make_client(model, db_path) as client:
        thread_id = None
        for message, expected_route, expected_in_reply in turns:
            payload = {"message": message}
            if thread_id:
                payload["thread_id"] = thread_id
            body = (await client.post("/chat", json=payload, headers=auth_headers("C001"))).json()
            assert body["route"] == expected_route, message
            assert expected_in_reply in body["reply"], message
            thread_id = body["thread_id"]

    # 写操作真实落库:占位符在工具层被还原为真实手机号
    with Session(engine) as session:
        assert session.get(Customer, "C001").phone == "13911112222"
        kinds = set(session.exec(select(ServiceRequest.kind)).all())
    assert kinds == {"statement", "cheque_book"}

    # LLM 可见内容中只有占位符,没有真实手机号
    visible = llm_visible_text(model)
    assert "13911112222" not in visible
    assert "[PHONE_1]" in visible


async def test_missing_token_returns_401(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=[])
    async with make_client(model, db_path) as client:
        resp = await client.post("/chat", json={"message": "查余额"})
    assert resp.status_code == 401


async def test_invalid_token_returns_401(seeded_db):
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=[])
    async with make_client(model, db_path) as client:
        resp = await client.post(
            "/chat",
            json={"message": "查余额"},
            headers={"Authorization": "Bearer forged-token"},
        )
    assert resp.status_code == 401


async def test_token_without_scopes_returns_403(seeded_db):
    """token 合法(认证通过)但不含任何业务 scope → 403。"""
    db_path, _ = seeded_db
    model = ScriptedChatModel(script=[])
    async with make_client(model, db_path) as client:
        resp = await client.post(
            "/chat", json={"message": "查余额"}, headers=auth_headers("C001", set())
        )
    assert resp.status_code == 403


async def test_token_never_visible_to_llm(seeded_db):
    """token 不出现在任何 LLM 输入(prompt 消息、工具结果)中。"""
    db_path, _ = seeded_db
    model = ScriptedChatModel(
        script=[
            route("accounts", rationale="查余额"),
            tool_call("query_balance", {}),
            AIMessage(content="您的余额为 12800.50 元。"),
        ]
    )
    headers = auth_headers("C001")
    token = headers["Authorization"].removeprefix("Bearer ")
    async with make_client(model, db_path) as client:
        resp = await client.post("/chat", json={"message": "查余额"}, headers=headers)
    assert resp.status_code == 200
    assert token not in llm_visible_text(model)


async def test_customer_a_cannot_read_customer_b_account(seeded_db):
    """C002 的 token 即使被诱导调用 C001 的账户,也查不到任何数据。"""
    db_path, _ = seeded_db
    model = ScriptedChatModel(
        script=[
            route("accounts", rationale="查余额"),
            tool_call("query_balance", {"account_id": "A001"}),  # A001 属于 C001
            AIMessage(content="未找到该账户。"),
        ]
    )
    async with make_client(model, db_path) as client:
        resp = await client.post(
            "/chat", json={"message": "查一下 A001 的余额"}, headers=auth_headers("C002")
        )
    body = resp.json()
    assert "12800.50" not in body["reply"]
    # 工具返回的错误也进入了 LLM 上下文,同样不得含他人数据
    assert "12800.50" not in llm_visible_text(model)


async def test_induced_over_scope_tool_call_is_blocked(seeded_db):
    """LLM 被诱导发起越权调用:token 只有读权限,工具层拦下写操作,落库不变。"""
    db_path, engine = seeded_db
    model = ScriptedChatModel(
        script=[
            route("service", rationale="改地址"),
            tool_call("change_address", {"new_address": "北京市海淀区中关村 1 号"}),
            AIMessage(content="抱歉,该操作未被授权。"),
        ]
    )
    headers = auth_headers("C001", {"accounts:read", "transactions:read"})
    async with make_client(model, db_path) as client:
        resp = await client.post(
            "/chat", json={"message": "把地址改成北京市海淀区中关村 1 号"}, headers=headers
        )
    assert resp.status_code == 200
    assert resp.json()["reply"] == "抱歉,该操作未被授权。"
    with Session(engine) as session:
        assert session.get(Customer, "C001").address == "北京市朝阳区建国路 1 号"


async def test_pii_in_user_message_masked_end_to_end(seeded_db):
    """手机号/身份证/姓名入站即脱敏;LLM 全程只见占位符;回复回填真实值。"""
    db_path, engine = seeded_db
    model = ScriptedChatModel(
        script=[
            route("service", rationale="更新证件号"),
            tool_call("update_kyc", {"id_number": "[ID_CARD_1]"}),
            AIMessage(content="[NAME_1] 您好,证件号 [ID_CARD_1] 已更新。"),
        ]
    )
    async with make_client(model, db_path) as client:
        resp = await client.post(
            "/chat",
            json={"message": "我是张三,把证件号更新为 110101199001011234,手机 13800001111"},
            headers=auth_headers("C001"),
        )
    body = resp.json()
    # 出站回填:用户看到的仍是真实值
    assert "110101199001011234" in body["reply"]
    assert "张三" in body["reply"]
    # LLM 可见内容:占位符在,真实值不在
    visible = llm_visible_text(model)
    assert "[ID_CARD_1]" in visible and "[NAME_1]" in visible and "[PHONE_1]" in visible
    assert "110101199001011234" not in visible
    assert "13800001111" not in visible
    assert "张三" not in visible
    # 工具层还原真实值落库
    with Session(engine) as session:
        assert session.get(Customer, "C001").id_number == "110101199001011234"


async def test_pii_map_persists_across_turns(seeded_db):
    """会话映射经 checkpointer 持久化:同一真实值跨轮复用同一占位符,不重复编号。"""
    db_path, _ = seeded_db
    model = ScriptedChatModel(
        script=[
            route("clarify", rationale="收到手机号", question="已记录您的手机号。"),
            route("clarify", rationale="再次确认", question="确认是同一号码。"),
        ]
    )
    headers = auth_headers("C001")
    async with make_client(model, db_path) as client:
        body1 = (
            await client.post(
                "/chat", json={"message": "我的手机号是 13800001111"}, headers=headers
            )
        ).json()
        await client.post(
            "/chat",
            json={"message": "再确认一下 13800001111", "thread_id": body1["thread_id"]},
            headers=headers,
        )
    # 两轮下来 LLM 只见过 [PHONE_1],真实号码零泄漏,且没有产生 [PHONE_2]
    visible = llm_visible_text(model)
    assert "13800001111" not in visible
    assert "[PHONE_2]" not in visible
    assert "再确认一下 [PHONE_1]" in visible


async def test_tool_result_pii_masked_before_llm(seeded_db):
    """工具结果中的卡号/账号在返回给 LLM 前脱敏,回复再回填。"""
    db_path, _ = seeded_db
    model = ScriptedChatModel(
        script=[
            route("accounts", rationale="查余额"),
            tool_call("query_balance", {}),
            AIMessage(content="您的储蓄账户 [CARD_1] 余额为 12800.50 元。"),
        ]
    )
    async with make_client(model, db_path) as client:
        resp = await client.post("/chat", json={"message": "查余额"}, headers=auth_headers("C001"))
    body = resp.json()
    assert "6222020200112233" in body["reply"]  # 回填真实账号
    visible = llm_visible_text(model)
    assert "6222020200112233" not in visible  # LLM 只见占位符
    assert "[CARD_1]" in visible
