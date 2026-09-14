"""LLM 接入:DeepSeek 经 OpenAI 兼容客户端。provider 抽象保持很薄。"""

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from bank_agent.config import Settings


def create_chat_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        temperature=0,
    )


def content_text(message: AIMessage) -> str:
    """取出模型输出的纯文本(content 可能是结构化分块列表,统一压成 str)。"""
    content = message.content
    return content if isinstance(content, str) else str(content)
