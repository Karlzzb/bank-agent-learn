"""Edge 中间件栈:请求 ID、访问日志、限流。

- 每个请求生成 request ID:响应头 X-Request-ID 返回给调用方,访问日志按它串联全链路。
- 访问日志独立 logger(bank_agent.access),含 request ID、方法、路径、状态码、耗时、客户。
- 限流按客户维度:key 从 Bearer token 里不验签解出 sub(仅用于计数分桶,
  鉴权仍由 api 层 verify_token 严格执行);无 token 按来源 IP。单用户刷后端被 429 拦下。
- WAF/DDoS 属基础设施层能力(网关/云厂商),代码不假装实现,见 docs/go-live.md。
"""

import logging
import time
import uuid

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

access_logger = logging.getLogger("bank_agent.access")


def rate_limit_key(request: Request) -> str:
    """限流分桶键:优先按 token 里的 customer_id(不验签,仅分桶),否则按来源 IP。"""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
        except jwt.DecodeError:
            payload = {}
        if sub := payload.get("sub"):
            return f"customer:{sub}"
    return f"ip:{get_remote_address(request)}"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """请求 ID + 访问日志:最外层中间件,兜底覆盖正常响应与异常响应。"""

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        customer_id = getattr(request.state, "customer_id", "-")
        access_logger.info(
            "%s %s %s -> %s %.1fms customer=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            customer_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response


async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "请求过于频繁,请稍后再试"})


def install_edge(app: FastAPI) -> Limiter:
    """装配 Edge 栈:限流器挂 app.state,/chat 端点用 @limiter.limit 声明限速。"""
    limiter = Limiter(key_func=rate_limit_key)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(RequestContextMiddleware)
    return limiter
