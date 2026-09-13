"""交易领域 MCP Server:交易明细、结单申请。

运行:python -m bank_agent.mcp_servers.transactions
"""

from fastmcp import FastMCP
from sqlalchemy.engine import Engine

from bank_agent.config import get_settings
from bank_agent.domains.transactions import tools
from bank_agent.mcp_servers.common import build_server, register_domain_tool, serve

IMPLS = [tools.list_transactions, tools.get_transaction_detail, tools.request_statement]


def register(server: FastMCP, engine: Engine) -> None:
    for impl in IMPLS:
        register_domain_tool(server, engine, impl)


def create_server(db_path: str) -> FastMCP:
    return build_server("transactions-mcp", db_path, register)


if __name__ == "__main__":
    serve(create_server, get_settings().mcp_transactions_port)
