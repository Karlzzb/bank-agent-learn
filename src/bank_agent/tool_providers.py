"""工具提供者:Agent 侧拿到各领域 LangChain 工具的统一接缝。

- DirectToolProvider:进程内直连仓储实现(测试、CLI 免 MCP 进程场景)。
- McpToolProvider:经 FastMCP Client 远程调用(Streamable HTTP),工具 schema 动态发现。

两种提供者都把 customer_id 从 config 注入到工具调用,
LLM 可见的工具参数里不含 customer_id(E3 起该通道承载 token)。
"""

import inspect
import json
from typing import Any, Protocol

from fastmcp import Client
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field, create_model
from sqlalchemy.engine import Engine

from bank_agent.core.db import new_session
from bank_agent.domains.accounts import tools as accounts_tools
from bank_agent.domains.service import tools as service_tools
from bank_agent.domains.transactions import tools as transactions_tools


class ToolProvider(Protocol):
    async def tools_for(self, domain: str, customer_id: str) -> list[BaseTool]: ...


class DirectToolProvider:
    """进程内直连:把领域工具实现包成 LangChain 工具,注入会话与 customer_id。"""

    def __init__(self, engine: Engine):
        self._engine = engine

    async def tools_for(self, domain: str, customer_id: str) -> list[BaseTool]:
        impls = _DIRECT_IMPLS[domain]
        return [self._wrap(impl, customer_id) for impl in impls]

    def _wrap(self, impl, customer_id: str) -> BaseTool:
        async def call(**kwargs: Any) -> str:
            with new_session(self._engine) as session:
                result = impl(session, customer_id, **kwargs)
            return json.dumps(result, ensure_ascii=False)

        # 参数 schema 从实现函数签名推导,隐藏 session / customer_id
        sig = inspect.signature(impl)
        fields = {}
        for name, param in sig.parameters.items():
            if name in ("session", "customer_id"):
                continue
            annotation = (
                param.annotation if param.annotation is not inspect.Parameter.empty else str
            )
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[name] = (annotation, Field(default=default))
        args_schema = create_model(f"{impl.__name__}_args", **fields)
        return StructuredTool(
            name=impl.__name__,
            description=(impl.__doc__ or "").strip(),
            args_schema=args_schema,
            coroutine=call,
        )


_DIRECT_IMPLS = {
    "accounts": [accounts_tools.query_balance],
    "transactions": [
        transactions_tools.list_transactions,
        transactions_tools.get_transaction_detail,
        transactions_tools.request_statement,
    ],
    "service": [
        service_tools.change_address,
        service_tools.request_cheque_book,
        service_tools.update_kyc,
    ],
}


_JSON_TYPES = {"string": str, "integer": int, "number": float, "boolean": bool}


class McpToolProvider:
    """远程 MCP:动态发现工具 schema,调用时注入 customer_id。"""

    def __init__(self, urls: dict[str, str]):
        self._urls = urls  # domain -> streamable-http URL

    async def tools_for(self, domain: str, customer_id: str) -> list[BaseTool]:
        url = self._urls[domain]
        async with Client(url) as client:
            mcp_tools = await client.list_tools()
        return [self._wrap(url, t, customer_id) for t in mcp_tools]

    def _wrap(self, url: str, mcp_tool, customer_id: str) -> BaseTool:
        async def call(**kwargs: Any) -> str:
            async with Client(url) as client:
                result = await client.call_tool(
                    mcp_tool.name, {**kwargs, "customer_id": customer_id}
                )
            data = result.data if result.data is not None else result.structured_content
            return json.dumps(data, ensure_ascii=False)

        schema = mcp_tool.input_schema or {}
        properties = {k: v for k, v in schema.get("properties", {}).items() if k != "customer_id"}
        required = set(schema.get("required", [])) - {"customer_id"}
        fields = {}
        for name, prop in properties.items():
            py_type = _JSON_TYPES.get(prop.get("type", "string"), str)
            if name in required:
                fields[name] = (py_type, Field(...))
            else:
                fields[name] = (py_type | None, Field(default=None))
        args_schema = create_model(f"{mcp_tool.name}_args", **fields)
        return StructuredTool(
            name=mcp_tool.name,
            description=mcp_tool.description or "",
            args_schema=args_schema,
            coroutine=call,
        )


async def resolve_tools(config: RunnableConfig, domain: str) -> list[BaseTool]:
    """图节点从 config 通道解析工具:provider 与 customer_id 都由调用方注入。"""
    configurable = config.get("configurable", {})
    provider: ToolProvider = configurable["tool_provider"]
    customer_id: str = configurable["customer_id"]
    return await provider.tools_for(domain, customer_id)
