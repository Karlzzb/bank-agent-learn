"""LLM 接入:DeepSeek 经 OpenAI 兼容客户端。provider 抽象保持很薄。"""

from langchain_openai import ChatOpenAI

from bank_agent.config import Settings


def create_chat_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        temperature=0,
    )
