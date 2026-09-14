"""组合根:装配图、工具提供者与持久化,是唯一知道"生产 vs 测试" wiring 的地方。

- 生产:真实 ChatOpenAI + McpToolProvider(远程 MCP)
  + SQLite checkpointer(断线续聊)+ SqliteStore(跨会话偏好)。
- 测试/离线:注入 ScriptedChatModel + DirectToolProvider(进程内直连仓储);
  checkpointer 缺省内存版,续聊测试经参数注入 SQLite 版。
图本身不知道两者的差别;工具提供者在每次调用时经 config 通道传入。
"""

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from sqlalchemy.engine import Engine

from bank_agent.config import Settings, get_settings
from bank_agent.core.db import init_db, make_engine
from bank_agent.graph.builder import build_graph
from bank_agent.llm import create_chat_model
from bank_agent.memory import SqliteStore
from bank_agent.memory.checkpointing import aclose_checkpointer, amake_sqlite_checkpointer
from bank_agent.tool_providers import DirectToolProvider, McpToolProvider, ToolProvider


@dataclass
class CompositionRoot:
    graph: CompiledStateGraph
    tool_provider: ToolProvider
    engine: Engine
    settings: Settings
    checkpointer: BaseCheckpointSaver | None = None
    store: BaseStore | None = None

    async def aclose(self) -> None:
        """释放持久化资源(SQLite 连接为非守护线程,不关闭会导致进程退不出)。"""
        await aclose_checkpointer(self.checkpointer)
        close = getattr(self.store, "close", None)
        if close is not None:
            close()


async def build_production(settings: Settings | None = None) -> CompositionRoot:
    """异步装配:checkpointer 须在事件循环内创建(入口见 run.py / cli.py)。"""
    settings = settings or get_settings()
    engine = make_engine(settings.bank_db_path)
    init_db(engine)
    model: BaseChatModel = create_chat_model(settings)
    provider = McpToolProvider(
        {
            "accounts": settings.mcp_accounts_url,
            "transactions": settings.mcp_transactions_url,
            "service": settings.mcp_service_url,
        }
    )
    checkpointer = await amake_sqlite_checkpointer(settings.checkpoint_db_path)
    store = SqliteStore(settings.memory_store_path)
    graph = build_graph(
        model,
        checkpointer=checkpointer,
        store=store,
        max_history=settings.history_max_messages,
        keep_recent=settings.history_keep_recent,
    )
    return CompositionRoot(
        graph=graph,
        tool_provider=provider,
        engine=engine,
        settings=settings,
        checkpointer=checkpointer,
        store=store,
    )


def build_for_test(
    model: BaseChatModel,
    db_path: str,
    settings: Settings | None = None,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
    max_history: int | None = None,
    keep_recent: int | None = None,
) -> CompositionRoot:
    """注入确定性假 model 与进程内工具提供者,不碰真实 LLM 与网络。

    摘要阈值缺省取自 settings(与生产同一来源),需要触发摘要的测试显式传小值。
    """
    settings = settings or Settings(bank_db_path=db_path)
    engine = make_engine(db_path)
    init_db(engine)
    return CompositionRoot(
        graph=build_graph(
            model,
            checkpointer=checkpointer,
            store=store,
            max_history=max_history or settings.history_max_messages,
            keep_recent=keep_recent or settings.history_keep_recent,
        ),
        tool_provider=DirectToolProvider(engine),
        engine=engine,
        settings=settings,
        checkpointer=checkpointer,
        store=store,
    )
