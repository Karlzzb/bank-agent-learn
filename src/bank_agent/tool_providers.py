"""工具提供者:Agent 侧拿到各领域 LangChain 工具的统一接缝。

- DirectToolProvider:进程内直连仓储实现(测试、CLI 免 MCP 进程场景)。
- McpToolProvider:经 FastMCP Client 远程调用(Streamable HTTP),工具 schema 动态发现。

两种提供者遵守同一条安全契约:
- auth(含 token 与 customer_id)从 config 通道注入,不出现在 LLM 可见的工具参数里;
- 每次调用先做 scope 校验(MCP 侧服务端还会再校验一次,双层防线);
- LLM 给出的占位符入参在此还原为真实值(不经 LLM),工具结果中的真实值
  在返回给 LLM 前脱敏为占位符。
"""

import inspect
import json
from typing import Any, Protocol

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field, create_model
from sqlalchemy.engine import Engine

from bank_agent.auth.scopes import check_scope
from bank_agent.auth.tokens import AuthContext
from bank_agent.core.db import new_session
from bank_agent.domains.accounts import tools as accounts_tools
from bank_agent.domains.service import tools as service_tools
from bank_agent.domains.transactions import tools as transactions_tools
from bank_agent.mcp_servers.common import TOKEN_HEADER
from bank_agent.pii import mask_text, rehydrate


class ToolProvider(Protocol):
    async def tools_for(
        self, domain: str, auth: AuthContext, pii_map: dict[str, str]
    ) -> list[BaseTool]: ...


def _rehydrate_value(value: Any, pii_map: dict[str, str]) -> Any:
    """递归还原:字符串中的占位符替换为真实值,嵌套结构逐层下钻。"""
    if isinstance(value, str):
        return rehydrate(value, pii_map)
    if isinstance(value, dict):
        return {k: _rehydrate_value(v, pii_map) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rehydrate_value(v, pii_map) for v in value]
    return value


def _rehydrate_args(kwargs: dict[str, Any], pii_map: dict[str, str]) -> dict[str, Any]:
    """LLM 只看到占位符,真实入参在工具层还原。"""
    return {k: _rehydrate_value(v, pii_map) for k, v in kwargs.items()}


def _mask_result(result: Any, pii_map: dict[str, str]) -> str:
    """工具结果中的真实值脱敏后才允许进入 LLM 上下文。"""
    return mask_text(json.dumps(result, ensure_ascii=False), pii_map)


def _scope_denied(tool_name: str, auth: AuthContext) -> str | None:
    """Agent 侧 scope 校验(MCP 侧服务端还有第二道);越权返回错误 JSON,否则 None。"""
    try:
        check_scope(tool_name, auth.scopes)
    except PermissionError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return None


class DirectToolProvider:
    """进程内直连:把领域工具实现包成 LangChain 工具,注入会话与 auth。"""

    def __init__(self, engine: Engine):
        self._engine = engine

    async def tools_for(
        self, domain: str, auth: AuthContext, pii_map: dict[str, str]
    ) -> list[BaseTool]:
        impls = _DIRECT_IMPLS[domain]
        return [self._wrap(impl, auth, pii_map) for impl in impls]

    def _wrap(self, impl, auth: AuthContext, pii_map: dict[str, str]) -> BaseTool:
        async def call(**kwargs: Any) -> str:
            if denied := _scope_denied(impl.__name__, auth):
                return denied
            args = _rehydrate_args(kwargs, pii_map)
            with new_session(self._engine) as session:
                result = impl(session, auth.customer_id, **args)
            return _mask_result(result, pii_map)

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
    """远程 MCP:动态发现工具 schema;token 走 X-Bank-Token 头,不进工具参数。

    fastmcp 4 的 HTTP 传输会剥离 Authorization 头,内部服务间改用专用头传递。
    """

    def __init__(self, urls: dict[str, str]):
        self._urls = urls  # domain -> streamable-http URL

    def _client(self, url: str, auth: AuthContext) -> Client:
        transport = StreamableHttpTransport(url, headers={TOKEN_HEADER: auth.token})
        return Client(transport)

    async def tools_for(
        self, domain: str, auth: AuthContext, pii_map: dict[str, str]
    ) -> list[BaseTool]:
        url = self._urls[domain]
        async with self._client(url, auth) as client:
            mcp_tools = await client.list_tools()
        return [self._wrap(url, t, auth, pii_map) for t in mcp_tools]

    def _wrap(self, url: str, mcp_tool, auth: AuthContext, pii_map: dict[str, str]) -> BaseTool:
        async def call(**kwargs: Any) -> str:
            if denied := _scope_denied(mcp_tool.name, auth):
                return denied
            args = _rehydrate_args(kwargs, pii_map)
            async with self._client(url, auth) as client:
                result = await client.call_tool(mcp_tool.name, args)
            data = result.data if result.data is not None else result.structured_content
            return _mask_result(data, pii_map)

        schema = mcp_tool.input_schema or {}
        fields = {}
        for name, prop in schema.get("properties", {}).items():
            py_type = _JSON_TYPES.get(prop.get("type", "string"), str)
            if name in set(schema.get("required", [])):
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
    """图节点从 config 通道解析工具:provider、auth、pii_map 都由调用方注入。"""
    configurable = config.get("configurable", {})
    provider: ToolProvider = configurable["tool_provider"]
    return await provider.tools_for(domain, configurable["auth"], configurable.get("pii_map", {}))
