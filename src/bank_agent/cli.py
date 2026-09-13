"""CLI 对话循环:python -m bank_agent.cli

直连组合根(进程内),默认走 MCP 工具提供者,需要先启动三个 MCP Server。
演示身份用 mock IdP 现场签发的 token(与 HTTP 路径同一套认证契约)。
"""

import asyncio

from bank_agent.auth.scopes import ALL_SCOPES
from bank_agent.auth.tokens import issue_token, verify_token
from bank_agent.chat import invoke_chat
from bank_agent.composition import build_production
from bank_agent.core.seed import DEMO_CUSTOMER_ID


async def main() -> None:
    root = build_production()
    token = issue_token(root.settings, DEMO_CUSTOMER_ID, ALL_SCOPES)
    auth = verify_token(root.settings, token)
    thread_id = None
    print(f"银行客服已就绪(客户 {DEMO_CUSTOMER_ID})。输入 quit 退出。")
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
    print("再见。")


if __name__ == "__main__":
    asyncio.run(main())
