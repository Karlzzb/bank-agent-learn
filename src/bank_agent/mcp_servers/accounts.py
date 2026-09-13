"""账户领域 MCP Server:余额查询。

运行:python -m bank_agent.mcp_servers.accounts
"""

from fastmcp import FastMCP
from sqlalchemy.engine import Engine

from bank_agent.config import get_settings
from bank_agent.domains.accounts import tools
from bank_agent.mcp_servers.common import build_server, register_domain_tool, serve

IMPLS = [tools.query_balance]


def register(server: FastMCP, engine: Engine) -> None:
    for impl in IMPLS:
        register_domain_tool(server, engine, impl)


def create_server(db_path: str) -> FastMCP:
    return build_server("accounts-mcp", db_path, register)


if __name__ == "__main__":
    serve(create_server, get_settings().mcp_accounts_port)
