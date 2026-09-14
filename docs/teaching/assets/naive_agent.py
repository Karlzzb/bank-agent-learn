"""E1 演示脚本:天真的单 Agent —— 一个 Agent 挂满全部领域的银行工具。

配套教案:docs/teaching/E1-单Agent挂满工具的失败.md

用法(在 tag e1 检出状态下演示):
    git checkout e1
    make run                                  # 终端 1:拉起 3 个 MCP Server + API
    python docs/teaching/assets/naive_agent.py --probe   # 终端 2:零 LLM 消耗,自检工具发现
    python docs/teaching/assets/naive_agent.py           # 真实 LLM,逐题演示失败

本脚本刻意不 import bank_agent 包:它代表"还没有任何架构"的天真实现,
直接连三个 MCP Server,把发现的全部工具一股脑挂给一个 ReAct Agent。
在 e1 之后的 tag 上演示时,服务端要求 X-Bank-Token 头,用环境变量传入:
    BANK_DEMO_TOKEN=$(python -m bank_agent.auth.idp C001) python docs/teaching/assets/naive_agent.py
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

MCP_URLS = {
    "accounts": "http://127.0.0.1:8101/mcp",
    "transactions": "http://127.0.0.1:8102/mcp",
    "service": "http://127.0.0.1:8103/mcp",
}
TOKEN_HEADER = "x-bank-token"  # e3 起服务端要求的专用头;e1 时代还没有这堵墙

NAIVE_SYSTEM_PROMPT = (
    "你是银行客服助手,正在为客户 C001 服务。"
    "客户的问题都用工具解决;工具需要 customer_id 参数时,填入当前客户编号。"
)

# 演示题:刻意选跨领域、易混淆的请求,放大"工具过多"的失败模式
DEMO_QUESTIONS = [
    "帮我看看余额,顺便把最近那笔房租的明细调出来",  # 跨 accounts/transactions
    "上周那笔 320 块 5 的消费是在哪刷的?顺便给我开个结单",  # 明细 + 结单两种工具
    "把地址改到上海市浦东新区世纪大道 1 号,再帮我申请一本支票簿",  # 连续两个写操作
    "帮我查查 C002 的余额",  # e1 没有授权边界:LLM 会直接查别人账户
]

_JSON_TYPES = {"string": str, "integer": int, "number": float, "boolean": bool}


def load_env_file(path: Path = Path(".env")) -> None:
    """极简 .env 加载:只为让本脚本脱离 bank_agent 包独立运行。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def make_client(url: str) -> Client:
    token = os.environ.get("BANK_DEMO_TOKEN", "")
    headers = {TOKEN_HEADER: token} if token else None
    return Client(StreamableHttpTransport(url, headers=headers))


def wrap_tool(url: str, mcp_tool) -> StructuredTool:
    """把一个远程 MCP 工具包成 LangChain 工具(每次调用新建连接,够演示用)。"""

    async def call(**kwargs: Any) -> str:
        async with make_client(url) as client:
            result = await client.call_tool(mcp_tool.name, kwargs)
        data = result.data if result.data is not None else result.structured_content
        return json.dumps(data, ensure_ascii=False, default=str)

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


async def discover_all_tools() -> tuple[list[StructuredTool], int]:
    """连全部 MCP Server,把发现的工具全部挂上来;返回工具列表与 schema 总字符数。"""
    tools: list[StructuredTool] = []
    schema_chars = 0
    for domain, url in MCP_URLS.items():
        async with make_client(url) as client:
            mcp_tools = await client.list_tools()
        for mcp_tool in mcp_tools:
            schema_chars += len(json.dumps(mcp_tool.input_schema or {}, ensure_ascii=False))
            schema_chars += len(mcp_tool.description or "")
            tools.append(wrap_tool(url, mcp_tool))
        print(f"[{domain}] 发现 {len(mcp_tools)} 个工具:{[t.name for t in mcp_tools]}")
    return tools, schema_chars


async def probe() -> None:
    """零 LLM 自检:工具发现 + 一次直接调用,验证环境与脚本可用。"""
    tools, schema_chars = await discover_all_tools()
    print(f"\n共挂载 {len(tools)} 个工具,system prompt 前的工具 schema 已占 {schema_chars} 字符")
    balance = next(t for t in tools if t.name == "query_balance")
    args = {"customer_id": "C001"} if "customer_id" in balance.args else {}
    print(f"\n直接调用 query_balance({args}):")
    print(await balance.ainvoke(args))


def print_transcript(messages) -> None:
    """把 Agent 的每一次工具调用与最终回复打印出来,方便镜头前逐条点评。"""
    for message in messages:
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            for call in tool_calls:
                args = json.dumps(call["args"], ensure_ascii=False)
                print(f"  → 调用工具 {call['name']}({args})")
        if message.type == "tool":
            print(f"  ← 工具返回 {str(message.content)[:200]}")
    print(f"最终回复:{messages[-1].content}\n")


async def run_demo(questions: list[str]) -> None:
    if not os.environ.get("LLM_API_KEY"):
        sys.exit("请先在 .env 填入 LLM_API_KEY(或 export LLM_API_KEY=...)")
    from langchain_openai import ChatOpenAI

    try:
        from langchain.agents import create_agent

        def build_agent(model, tools):
            return create_agent(model, tools, system_prompt=NAIVE_SYSTEM_PROMPT)
    except ImportError:  # langchain 0.x:退回 langgraph.prebuilt
        from langgraph.prebuilt import create_react_agent

        def build_agent(model, tools):
            return create_react_agent(model, tools, prompt=NAIVE_SYSTEM_PROMPT)

    tools, schema_chars = await discover_all_tools()
    print(f"\n一个 Agent 挂满 {len(tools)} 个工具,工具 schema 共 {schema_chars} 字符\n")

    model = ChatOpenAI(
        model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
        api_key=os.environ["LLM_API_KEY"],
    )
    agent = build_agent(model, tools)
    for question in questions:
        print(f"用户:{question}")
        result = await agent.ainvoke({"messages": [("user", question)]})
        print_transcript(result["messages"])


def main() -> None:
    parser = argparse.ArgumentParser(description="E1 天真单 Agent 演示")
    parser.add_argument("--probe", action="store_true", help="只做工具发现与自检,不调 LLM")
    parser.add_argument("questions", nargs="*", help="自定义演示问题(默认用内置四题)")
    args = parser.parse_args()
    load_env_file()
    if args.probe:
        asyncio.run(probe())
    else:
        asyncio.run(run_demo(args.questions or DEMO_QUESTIONS))


if __name__ == "__main__":
    main()
