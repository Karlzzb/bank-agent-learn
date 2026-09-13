"""CLI 对话循环:python -m bank_agent.cli

直连组合根(进程内),默认走 MCP 工具提供者,需要先启动三个 MCP Server。
"""

import asyncio

from bank_agent.chat import invoke_chat
from bank_agent.composition import build_production
from bank_agent.core.seed import DEMO_CUSTOMER_ID


async def main() -> None:
    root = build_production()
    thread_id = None
    print(f"银行客服已就绪(客户 {DEMO_CUSTOMER_ID})。输入 quit 退出。")
    while True:
        try:
            message = input("您: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message or message.lower() in {"quit", "exit"}:
            break
        result = await invoke_chat(root, message, thread_id, DEMO_CUSTOMER_ID)
        thread_id = result["thread_id"]
        print(f"客服: {result['reply']}")
    print("再见。")


if __name__ == "__main__":
    asyncio.run(main())
