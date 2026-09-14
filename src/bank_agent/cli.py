"""CLI 对话循环:python -m bank_agent.cli [thread_id]

直连组合根(进程内),默认走 MCP 工具提供者,需要先启动三个 MCP Server。
演示身份用 mock IdP 现场签发的 token(与 HTTP 路径同一套认证契约)。
传入 thread_id 可继续既有会话(断线续聊);退出时会打印本次会话 ID 供下次使用。
"""

import asyncio
import sys

from bank_agent.auth.scopes import ALL_SCOPES
from bank_agent.auth.tokens import issue_token, verify_token
from bank_agent.chat import invoke_chat
from bank_agent.composition import build_production
from bank_agent.core.seed import DEMO_CUSTOMER_ID


async def main() -> None:
    root = await build_production()
    token = issue_token(root.settings, DEMO_CUSTOMER_ID, ALL_SCOPES)
    auth = verify_token(root.settings, token)
    thread_id = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"银行客服已就绪(客户 {DEMO_CUSTOMER_ID})。输入 quit 退出。")
    if thread_id:
        print(f"继续会话:{thread_id}")
    try:
        while True:
            try:
                message = input("您: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not message or message.lower() in {"quit", "exit"}:
                break
            result = await invoke_chat(root, message, auth, thread_id)
            thread_id = result["thread_id"]
            print(f"客服: {result['reply']}")
    finally:
        await root.aclose()
    print(f"再见。本次会话 ID:{thread_id}(下次可用 python -m bank_agent.cli {thread_id} 续聊)")


if __name__ == "__main__":
    asyncio.run(main())
