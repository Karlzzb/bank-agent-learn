"""Langfuse 可观测性:trace 接入与归因维度,未配置时全程无侵入降级。

- 启用条件:settings 配齐 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY;
  否则 configure 不建客户端,trace_config 返回空 dict,图照常运行(测试与离线场景零依赖)。
- 接入方式:Langfuse SDK v3 单例 + langchain CallbackHandler,经图调用 config 注入;
  一次对话的全部节点、LLM 调用、工具调用收进同一条 trace。
- 归因维度(成本用 Langfuse 原生价格表,DeepSeek 单价已在默认价格表,不自建计数器):
  会话 → langfuse_session_id = thread_id;用户 → langfuse_user_id = customer_id;
  Agent → 领域子图调用的 metadata.agent(见 graph/builder.py)与各节点名。
- 进程退出前 flush,避免内存队列里的 trace 丢失。
"""

import logging

from langfuse import Langfuse

from bank_agent.config import Settings

logger = logging.getLogger(__name__)

# 模块级单例:Langfuse SDK 本身即单例设计,这里只记"是否已启用"与客户端引用
_client: Langfuse | None = None


def configure(settings: Settings) -> bool:
    """初始化 Langfuse 单例。返回是否启用;未配 key 时不建客户端、不留副作用。"""
    global _client
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.info("未配置 Langfuse key,可观测性接入关闭(系统照常运行)")
        return False
    _client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
    )
    logger.info("Langfuse 已启用:%s", settings.langfuse_base_url)
    return True


def trace_config(thread_id: str, customer_id: str) -> dict:
    """并入图调用 config 的片段:callback + 归因 metadata;未启用时为空 dict。"""
    if _client is None:
        return {}
    # 延迟 import:langfuse.langchain 依赖 langchain 包,未启用时不引入
    from langfuse.langchain import CallbackHandler

    return {
        "callbacks": [CallbackHandler()],
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_user_id": customer_id,
            "langfuse_tags": ["bank-agent", "chat"],
        },
    }


def flush() -> None:
    """进程退出前冲刷事件队列;未启用时为空操作。"""
    if _client is not None:
        _client.flush()
