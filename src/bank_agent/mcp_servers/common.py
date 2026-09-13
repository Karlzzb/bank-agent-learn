"""MCP Server 公共构造:每个领域一个 FastMCP Server,只挂载本领域工具。

customer_id 是 MCP 工具的服务端参数(E3 起由 token/scope 供给),
Agent 侧封装层负责注入,不出现在 LLM 可见的工具参数里。
"""

import functools
import inspect
from collections.abc import Callable

from fastmcp import FastMCP
from sqlalchemy.engine import Engine

from bank_agent.config import get_settings
from bank_agent.core.db import init_db, make_engine, new_session
from bank_agent.core.repositories import NotFoundError


def register_domain_tool(server: FastMCP, engine: Engine, impl: Callable) -> None:
    """把领域工具实现注册为 MCP 工具:每次调用独立开会话,NotFound 转结构化错误。

    impl 的签名形如 (session, customer_id, ...);session 由本层注入,
    从 MCP 工具 schema 中隐藏。
    """

    @functools.wraps(impl)
    def wrapper(*args, **kwargs):
        with new_session(engine) as session:
            try:
                return impl(session, *args, **kwargs)
            except NotFoundError as exc:
                return {"error": str(exc)}

    sig = inspect.signature(impl)
    wrapper.__signature__ = sig.replace(
        parameters=[p for p in sig.parameters.values() if p.name != "session"]
    )
    server.tool(name=impl.__name__)(wrapper)


def build_server(name: str, db_path: str, register: Callable[[FastMCP, Engine], None]) -> FastMCP:
    engine = make_engine(db_path)
    init_db(engine)
    server = FastMCP(name)
    register(server, engine)
    return server


def serve(create_server: Callable[[str], FastMCP], port: int) -> None:
    settings = get_settings()
    create_server(settings.bank_db_path).run(
        transport="streamable-http", host="127.0.0.1", port=port
    )
