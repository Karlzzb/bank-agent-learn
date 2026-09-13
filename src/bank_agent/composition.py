"""组合根:装配图、工具提供者与持久化,是唯一知道"生产 vs 测试" wiring 的地方。

- 生产:真实 ChatOpenAI + McpToolProvider(远程 MCP)。
- 测试/离线:注入 ScriptedChatModel + DirectToolProvider(进程内直连仓储)。
图本身不知道两者的差别;工具提供者在每次调用时经 config 通道传入。
"""

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.engine import Engine

from bank_agent.config import Settings, get_settings
from bank_agent.core.db import init_db, make_engine
from bank_agent.graph.builder import build_graph
from bank_agent.llm import create_chat_model
from bank_agent.tool_providers import DirectToolProvider, McpToolProvider, ToolProvider


@dataclass
class CompositionRoot:
    graph: CompiledStateGraph
    tool_provider: ToolProvider
    engine: Engine
    settings: Settings


def build_production(settings: Settings | None = None) -> CompositionRoot:
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
    return CompositionRoot(
        graph=build_graph(model), tool_provider=provider, engine=engine, settings=settings
    )


def build_for_test(
    model: BaseChatModel, db_path: str, settings: Settings | None = None
) -> CompositionRoot:
    """注入确定性假 model 与进程内工具提供者,不碰真实 LLM 与网络。"""
    settings = settings or Settings(bank_db_path=db_path)
    engine = make_engine(db_path)
    init_db(engine)
    return CompositionRoot(
        graph=build_graph(model),
        tool_provider=DirectToolProvider(engine),
        engine=engine,
        settings=settings,
    )
