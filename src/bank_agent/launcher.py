"""一键拉起全部进程:Langfuse(docker compose)+ 3 个 MCP Server + API。

用法:python -m bank_agent.launcher(或 make run)
先确保种子数据:python -m bank_agent.core.seed
Langfuse 起不来(无 docker / 首次拉镜像慢)不阻塞对话功能,仅警告;
LAUNCH_LANGFUSE=false 可关闭。Ctrl+C 停止全部进程(含 docker compose 栈)。
"""

import shutil
import signal
import subprocess
import sys
from pathlib import Path

from bank_agent.config import get_settings

PYTHON = sys.executable
COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def start_langfuse(enabled: bool) -> bool:
    """docker compose 拉起 Langfuse 全栈;不可用仅警告并返回 False。"""
    if not enabled:
        print("LAUNCH_LANGFUSE=false,跳过 Langfuse 启动")
        return False
    if shutil.which("docker") is None:
        print("警告:未检测到 docker,跳过 Langfuse(可观测性关闭,对话功能不受影响)")
        return False
    result = subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"], check=False)
    if result.returncode != 0:
        print("警告:docker compose 启动 Langfuse 失败,可观测性关闭,对话功能不受影响")
        return False
    print("Langfuse 已启动(首次需拉取镜像,就绪稍慢):http://localhost:3000")
    return True


def stop_langfuse(running: bool) -> None:
    if running:
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "stop"], check=False)


def main() -> None:
    settings = get_settings()
    langfuse_running = start_langfuse(settings.launch_langfuse)
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
        stop_langfuse(langfuse_running)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    for p in processes:
        p.wait()


if __name__ == "__main__":
    main()
