"""JWT 签发与验签:mock IdP 用本地固定密钥(HS256),token 携带 customer_id 与 scopes。

token 只走两条通道:HTTP Authorization 头(入站)与 LangGraph config(图内传递),
绝不进入 prompt 或 LLM 可见的工具参数。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import jwt

from bank_agent.config import Settings

ALGORITHM = "HS256"


class AuthError(Exception):
    """token 缺失、非法或过期(HTTP 层转 401)。"""


@dataclass(frozen=True)
class AuthContext:
    """一次请求的认证结果:经 config 通道在图内传递。"""

    customer_id: str
    scopes: frozenset[str]
    token: str = field(repr=False)  # 原始 token,供 MCP 客户端回传服务端验签;不打印


def issue_token(
    settings: Settings,
    customer_id: str,
    scopes: frozenset[str] | set[str],
    ttl_seconds: int | None = None,
) -> str:
    """mock IdP 签发 token。本地固定密钥,仅供开发/教学,不代表生产 IdP 形态。"""
    ttl = ttl_seconds if ttl_seconds is not None else settings.jwt_ttl_seconds
    now = datetime.now(UTC)
    payload = {
        "sub": customer_id,
        "scopes": sorted(scopes),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def verify_token(settings: Settings, token: str) -> AuthContext:
    """验签并还原认证上下文;任何失败统一抛 AuthError(不泄露失败细节)。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return AuthContext(
            customer_id=str(payload["sub"]),
            scopes=frozenset(payload.get("scopes", [])),
            token=token,
        )
    except (jwt.PyJWTError, KeyError, TypeError) as exc:
        raise AuthError("token 无效或已过期") from exc
