"""MCP Server 公共构造:每个领域一个 FastMCP Server,只挂载本领域工具。

安全边界(即使 LLM 被诱导也动不了越权数据):
- 每个工具调用从 X-Bank-Token 头验签 JWT,取 customer_id 与 scopes
  (fastmcp 4 的 HTTP 传输会剥离 Authorization 头,故内部服务间用专用头);
- 按工具声明的 scope 校验权限,不足则拒绝(ToolError);
- customer_id 只来自 token,不是工具参数,LLM 无法伪造他人身份。
"""

import functools
import inspect
from collections.abc import Callable

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from sqlalchemy.engine import Engine

from bank_agent.auth.scopes import check_scope
from bank_agent.auth.tokens import AuthError, verify_token
from bank_agent.config import get_settings
from bank_agent.core.db import init_db, make_engine, new_session
from bank_agent.core.repositories import NotFoundError

TOKEN_HEADER = "x-bank-token"


def _current_mcp_token() -> str | None:
    """从当前 HTTP 请求取 token;内存传输(测试)下无 HTTP 上下文,返回 None。

    注意:get_http_headers() 只返回合成子集,自定义头必须走原始 request。
    """
    try:
        return get_http_request().headers.get(TOKEN_HEADER)
    except RuntimeError:
        return None


def register_domain_tool(server: FastMCP, engine: Engine, impl: Callable) -> None:
    """把领域工具实现注册为 MCP 工具:验签 + scope 校验 + 注入会话与 customer_id。

    impl 的签名形如 (session, customer_id, ...);两者都由本层注入,
    从 MCP 工具 schema 中隐藏,LLM 不可见也不可伪造。
    """

    @functools.wraps(impl)
    def wrapper(*args, **kwargs):
        token = _current_mcp_token()
        if token is None:
            raise ToolError("缺少 token")
        try:
            auth = verify_token(get_settings(), token)
        except AuthError as exc:
            raise ToolError("token 无效或已过期") from exc
        try:
            check_scope(impl.__name__, auth.scopes)
        except PermissionError as exc:
            raise ToolError(str(exc)) from exc
        with new_session(engine) as session:
            try:
                return impl(session, auth.customer_id, *args, **kwargs)
            except NotFoundError as exc:
                return {"error": str(exc)}

    sig = inspect.signature(impl)
    wrapper.__signature__ = sig.replace(
        parameters=[p for p in sig.parameters.values() if p.name not in ("session", "customer_id")]
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
