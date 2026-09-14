"""接缝 1 端到端:会话与记忆(E4/E5)。

- 断线续聊:SQLite checkpointer 落盘,"进程重启"(新组合根 + 新 checkpointer 实例)
  后凭同一 thread_id 续聊,上下文完整。
- 会话内记忆:消息数超阈值后最旧段被压缩为摘要;外部可观察行为 =
  后续轮次 LLM 输入里摘要可见、被修剪的原文不可见、消息总数有界。
- 跨会话长期记忆:用户偏好写入 LangGraph store,新会话 Coordinator 的 prompt 中生效。
- 共享状态写者/reducer 规则与子图私有键隔离。

全部本地确定性运行,不依赖真实 LLM。
"""

import httpx
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore

from bank_agent.api import create_app
from bank_agent.composition import build_for_test
from bank_agent.memory import SqliteStore
from bank_agent.memory.checkpointing import amake_sqlite_checkpointer
from bank_agent.testing.fake_model import ScriptedChatModel
from tests.helpers import auth_headers, route, tool_call


def make_client(root) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(root)), base_url="http://test"
    )


def llm_visible_text(model: ScriptedChatModel) -> str:
    return "\n".join(str(m.content) for call in model.received for m in call)


async def test_resume_after_process_restart(seeded_db, tmp_path):
    """进程重启后凭同一 thread_id 续聊:第二轮的 LLM 输入里能看到第一轮完整上下文。"""
    db_path, _ = seeded_db
    checkpoint_path = str(tmp_path / "checkpoints.sqlite3")
    model = ScriptedChatModel(
        script=[
            route("accounts", rationale="用户要查余额"),
            tool_call("query_balance", {}),
            AIMessage(content="您的储蓄账户余额为 12800.50 元。"),
            route("clarify", rationale="用户追问刚才的内容", question="您刚才查询了储蓄账户余额。"),
        ]
    )
    headers = auth_headers("C001")

    # 第一个"进程":第一轮对话后关闭(模拟进程退出)
    root1 = build_for_test(
        model, db_path, checkpointer=await amake_sqlite_checkpointer(checkpoint_path)
    )
    async with make_client(root1) as client:
        body1 = (
            await client.post("/chat", json={"message": "帮我查一下余额"}, headers=headers)
        ).json()
    assert body1["route"] == "accounts"
    await root1.aclose()

    # 第二个"进程":同一 checkpoint 文件 + 新 checkpointer 实例,凭 thread_id 续聊
    root2 = build_for_test(
        model, db_path, checkpointer=await amake_sqlite_checkpointer(checkpoint_path)
    )
    async with make_client(root2) as client:
        body2 = (
            await client.post(
                "/chat",
                json={"message": "我刚才问了什么", "thread_id": body1["thread_id"]},
                headers=headers,
            )
        ).json()
    await root2.aclose()

    assert body2["thread_id"] == body1["thread_id"]
    assert body2["reply"] == "您刚才查询了储蓄账户余额。"
    # 上下文完整:重启后的路由调用能看到第一轮的用户消息与客服答复
    second_round = model.received[-1]
    visible = "\n".join(str(m.content) for m in second_round)
    assert "帮我查一下余额" in visible
    assert "12800.50" in visible


async def test_long_conversation_summarized_without_losing_context(seeded_db):
    """长会话触发摘要后:消息总数有界,被修剪的原文退出 LLM 视野,摘要持续可见。"""
    db_path, _ = seeded_db
    model = ScriptedChatModel(
        script=[
            route("clarify", rationale="寒暄", question="您好,请问要办理什么业务?"),
            route("clarify", rationale="继续寒暄", question="我在,您请说。"),
            # 第 3 轮:消息数超阈值,先做一次摘要,再路由
            AIMessage(content="用户两轮寒暄,尚未办理具体业务。"),
            route("clarify", rationale="仍未明确", question="请问具体要办哪件事?"),
            # 第 4 轮:带着摘要继续正常办理业务
            route("accounts", rationale="用户要查余额"),
            tool_call("query_balance", {}),
            AIMessage(content="您的储蓄账户余额为 12800.50 元。"),
        ]
    )
    root = build_for_test(model, db_path, max_history=4, keep_recent=2)
    headers = auth_headers("C001")
    async with make_client(root) as client:
        body1 = (await client.post("/chat", json={"message": "你好"}, headers=headers)).json()
        thread_id = body1["thread_id"]
        await client.post(
            "/chat", json={"message": "再说点别的", "thread_id": thread_id}, headers=headers
        )
        await client.post(
            "/chat", json={"message": "我还没想好", "thread_id": thread_id}, headers=headers
        )
        body4 = (
            await client.post(
                "/chat",
                json={"message": "我账户里还有多少钱", "thread_id": thread_id},
                headers=headers,
            )
        ).json()

    # 摘要生效:最后一次路由的 LLM 输入里摘要可见,被修剪的寒暄原文不可见
    last_route_call = "\n".join(str(m.content) for m in model.received[-3])
    assert "用户两轮寒暄" in last_route_call
    assert "再说点别的" not in last_route_call
    # 关键上下文不丢:摘要之后业务照常办理成功
    assert body4["route"] == "accounts"
    assert "12800.50" in body4["reply"]
    # 消息总数有界(摘要 + 保留的最近原文 + 本轮新增)
    state = await root.graph.aget_state({"configurable": {"thread_id": thread_id}})
    assert len(state.values["messages"]) <= 4 + 2


async def test_cross_session_preference_applies_in_new_thread(seeded_db, tmp_path):
    """会话 1 记住"常用账户 A002";"重启"后的全新会话直接按偏好办理(生产同款 SqliteStore)。"""
    db_path, _ = seeded_db
    store_path = str(tmp_path / "memory.sqlite3")
    model = ScriptedChatModel(
        script=[
            route("clarify", rationale="用户要求记住偏好", question="好的,已为您记住。"),
            AIMessage(content='{"items": {"常用账户": "A002"}}'),  # 偏好提取调用
            route("accounts", rationale="用户查常用账户余额"),
            tool_call("query_balance", {"account_id": "A002"}),
            AIMessage(content="您的活期账户 A002 余额为 3200.00 元。"),
            AIMessage(content='{"items": {}}'),  # 会话 2 也含触发词,再次提取但无新增
        ]
    )
    headers = auth_headers("C001")

    # 第一个"进程":写入偏好后关闭 store
    store1 = SqliteStore(store_path)
    root1 = build_for_test(model, db_path, store=store1)
    async with make_client(root1) as client:
        await client.post("/chat", json={"message": "记住我的常用账户是 A002"}, headers=headers)
    store1.close()

    # 第二个"进程":同一 store 文件,全新会话(不带 thread_id)偏好应生效
    store2 = SqliteStore(store_path)
    root2 = build_for_test(model, db_path, store=store2)
    async with make_client(root2) as client:
        body = (
            await client.post("/chat", json={"message": "查一下我常用账户的余额"}, headers=headers)
        ).json()
    store2.close()

    assert body["route"] == "accounts"
    assert "3200.00" in body["reply"]
    # 偏好确实经 store 落盘,且按客户命名空间隔离
    reader = SqliteStore(store_path)
    items = await reader.asearch(("profiles", "C001"))
    reader.close()
    assert {i.key: i.value["value"] for i in items} == {"常用账户": "A002"}
    # 新会话的领域子图(真正办事的一层)prompt 里注入了偏好
    domain_call = "\n".join(str(m.content) for m in model.received[3])
    assert "已知用户偏好" in domain_call and "A002" in domain_call


async def test_placeholder_preference_never_reaches_store(seeded_db):
    """PII 占位符是会话作用域:含占位符的提取结果丢弃,不污染跨会话 store。"""
    db_path, _ = seeded_db
    store = InMemoryStore()
    model = ScriptedChatModel(
        script=[
            route("clarify", rationale="用户要求记号码", question="好的。"),
            # 提取输入是脱敏文本,LLM 只能给出占位符;该结果必须被拦下
            AIMessage(content='{"items": {"联系号码": "[PHONE_1]"}}'),
        ]
    )
    root = build_for_test(model, db_path, store=store)
    async with make_client(root) as client:
        resp = await client.post(
            "/chat", json={"message": "记住我的手机号 13800001111"}, headers=auth_headers("C001")
        )
    assert resp.status_code == 200
    assert await store.asearch(("profiles", "C001")) == []


async def test_no_extra_llm_call_without_trigger_words(seeded_db):
    """无触发词的轮次不发起偏好提取调用:LLM 调用数与脚本严格一致(脚本耗尽即报错)。"""
    db_path, _ = seeded_db
    store = InMemoryStore()
    model = ScriptedChatModel(
        script=[
            route("accounts", rationale="查余额"),
            tool_call("query_balance", {}),
            AIMessage(content="您的储蓄账户余额为 12800.50 元。"),
        ]
    )
    root = build_for_test(model, db_path, store=store)
    async with make_client(root) as client:
        resp = await client.post("/chat", json={"message": "查余额"}, headers=auth_headers("C001"))
    assert resp.status_code == 200
    assert model.calls == 3  # 路由 + 工具调用 + 答复,没有第 4 次提取调用
    assert await store.asearch(("profiles", "C001")) == []


async def test_shared_state_writer_rules_and_private_key_isolation(seeded_db):
    """共享键只含约定四项;messages 只追加;route/rationale 被最新路由覆盖;tool_steps 不泄漏。"""
    db_path, _ = seeded_db
    model = ScriptedChatModel(
        script=[
            route("accounts", rationale="用户要查余额"),
            tool_call("query_balance", {}),
            AIMessage(content="您的储蓄账户余额为 12800.50 元。"),
            route("clarify", rationale="意图不明", question="请问还要办理什么?"),
        ]
    )
    root = build_for_test(model, db_path)
    headers = auth_headers("C001")
    async with make_client(root) as client:
        body1 = (await client.post("/chat", json={"message": "查余额"}, headers=headers)).json()
        await client.post(
            "/chat",
            json={"message": "嗯", "thread_id": body1["thread_id"]},
            headers=headers,
        )

    state = await root.graph.aget_state({"configurable": {"thread_id": body1["thread_id"]}})
    # 共享键集合恰为约定四项:子图私有键(tool_steps)不泄漏到父图
    assert set(state.values) == {"messages", "route", "rationale", "pii_map"}
    # messages 只追加:两轮 = 用户+答复各两条
    assert len(state.values["messages"]) == 4
    # route/rationale 唯一写者是 Coordinator,保留最新一次路由
    assert state.values["route"] == "clarify"
    assert state.values["rationale"] == "意图不明"
