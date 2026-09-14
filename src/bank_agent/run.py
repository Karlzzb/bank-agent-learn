"""uvicorn 入口:bank_agent.run:app

模块导入时尚无运行中的事件循环,用 asyncio.run 完成一次性的组合根装配;
checkpointer 之后只在 uvicorn 的事件循环上走异步接口。
"""

import asyncio

from bank_agent.api import create_app
from bank_agent.composition import build_production

app = create_app(asyncio.run(build_production()))
