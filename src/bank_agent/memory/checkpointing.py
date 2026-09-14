"""SQLite checkpointer 装配与回收。

AsyncSqliteSaver 须在事件循环内创建(构造时捕获当前 loop,仅供其同步包装方法使用;
本项目只走异步接口 aput/aget_tuple,创建完成后可在任意事件循环中使用)。
连接为非守护线程:进程退出前必须经 aclose_checkpointer 关闭,否则进程退不出。
同步入口(如 uvicorn 模块级装配)用 asyncio.run 包一层调用即可,见 run.py。
"""

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


async def amake_sqlite_checkpointer(path: str) -> AsyncSqliteSaver:
    """在调用方事件循环内创建(测试、CLI、asyncio.run 一次性装配)。"""
    saver = AsyncSqliteSaver(aiosqlite.connect(path))
    await saver.setup()
    return saver


async def aclose_checkpointer(checkpointer: BaseCheckpointSaver | None) -> None:
    """关闭 checkpointer 持有的 SQLite 连接;无连接可关时静默跳过。"""
    conn = getattr(checkpointer, "conn", None)
    if conn is not None:
        await conn.close()
