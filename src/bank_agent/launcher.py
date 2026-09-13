"""一键拉起全部进程:API + 3 个 MCP Server。

用法:python -m bank_agent.launcher(或 make run)
先确保种子数据:python -m bank_agent.core.seed
"""

import signal
import subprocess
import sys

from bank_agent.config import get_settings

PYTHON = sys.executable


def main() -> None:
    settings = get_settings()
    commands = [
        [PYTHON, "-m", "bank_agent.mcp_servers.accounts"],
        [PYTHON, "-m", "bank_agent.mcp_servers.transactions"],
        [PYTHON, "-m", "bank_agent.mcp_servers.service"],
        [
            PYTHON,
            "-m",
            "uvicorn",
            "bank_agent.run:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(settings.api_port),
        ],
    ]
    processes = [subprocess.Popen(cmd) for cmd in commands]
    print("已启动:3 个 MCP Server + API(Ctrl+C 全部停止)")

    def shutdown(*_):
        for p in processes:
            p.terminate()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    for p in processes:
        p.wait()


if __name__ == "__main__":
    main()
