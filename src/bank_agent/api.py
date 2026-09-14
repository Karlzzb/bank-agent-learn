"""FastAPI HTTP 层:对话接口,Edge 中间件栈 + Bearer 验签两道闸门。

- Edge 栈(edge.py):请求 ID(X-Request-ID)、访问日志、/chat 限流(429)。
- 无 token / token 非法 → 401;token 合法但不含任何业务 scope → 403。
- customer_id 只来自 token,请求体不再接受该字段(用户只能操作自己的账户)。
- 本层只做请求/响应解析,调用契约由 chat.invoke_chat 统一拼装。
- lifespan 负责在进程退出时释放组合根持有的 SQLite 连接(否则进程退不出)。
"""

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from bank_agent.auth.scopes import ALL_SCOPES
from bank_agent.auth.tokens import AuthContext, AuthError, verify_token
from bank_agent.chat import invoke_chat
from bank_agent.composition import CompositionRoot
from bank_agent.edge import install_edge


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None  # 缺省开新会话


class ChatResponse(BaseModel):
    thread_id: str
    reply: str
    route: str


def create_app(root: CompositionRoot) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # uvicorn 只配置自己的 logger;不给 root 装 handler,bank_agent.access 的
        # INFO 访问日志会被默认 WARNING 静默丢弃
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
        yield
        await root.aclose()

    app = FastAPI(title="bank-agent", lifespan=lifespan)
    limiter = install_edge(app)

    async def require_auth(
        request: Request, authorization: str = Header(default="")
    ) -> AuthContext:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="缺少 Bearer token")
        try:
            auth = verify_token(root.settings, token)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        if not auth.scopes & ALL_SCOPES:
            raise HTTPException(status_code=403, detail="token 不含任何业务权限")
        request.state.customer_id = auth.customer_id  # 供访问日志归因
        return auth

    @app.post("/chat", response_model=ChatResponse)
    @limiter.limit(f"{root.settings.rate_limit_per_minute}/minute")
    async def chat(
        request: Request,
        req: ChatRequest,
        auth: Annotated[AuthContext, Depends(require_auth)],
    ) -> ChatResponse:
        result = await invoke_chat(root, req.message, auth, req.thread_id)
        return ChatResponse(**result)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
