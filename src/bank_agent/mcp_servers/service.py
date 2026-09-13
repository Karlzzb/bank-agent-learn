"""服务领域 MCP Server:改地址、支票簿申请、KYC 更新。

运行:python -m bank_agent.mcp_servers.service
"""

from fastmcp import FastMCP
from sqlalchemy.engine import Engine

from bank_agent.config import get_settings
from bank_agent.domains.service import tools
from bank_agent.mcp_servers.common import build_server, register_domain_tool, serve

IMPLS = [tools.change_address, tools.request_cheque_book, tools.update_kyc]


def register(server: FastMCP, engine: Engine) -> None:
    for impl in IMPLS:
        register_domain_tool(server, engine, impl)


def create_server(db_path: str) -> FastMCP:
    return build_server("service-mcp", db_path, register)


if __name__ == "__main__":
    serve(create_server, get_settings().mcp_service_port)
