"""FastAPI HTTP 层:对话接口。

认证暂缺(E3 补 Bearer 验签);Edge 中间件栈在 E9 收尾。
本层只做请求/响应解析,调用契约由 chat.invoke_chat 统一拼装。
"""

from fastapi import FastAPI
from pydantic import BaseModel

from bank_agent.chat import invoke_chat
from bank_agent.composition import CompositionRoot
from bank_agent.core.seed import DEMO_CUSTOMER_ID


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None  # 缺省开新会话
    customer_id: str = DEMO_CUSTOMER_ID  # E3 起由 token 供给


class ChatResponse(BaseModel):
    thread_id: str
    reply: str
    route: str


def create_app(root: CompositionRoot) -> FastAPI:
    app = FastAPI(title="bank-agent")

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        result = await invoke_chat(root, req.message, req.thread_id, req.customer_id)
        return ChatResponse(**result)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
