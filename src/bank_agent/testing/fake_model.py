"""确定性假 chat model:按脚本依次返回预录的 AIMessage。

用于测试与离线演示:不依赖真实 LLM、不消耗 API 额度。
脚本耗尽仍被调用时报错,让测试暴露意外调用。
received 记录每次调用收到的完整消息列表,供测试断言 LLM 可见内容
(如:token 与真实 PII 不得出现在任何 LLM 输入中)。
"""

from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import Field


class ScriptedChatModel(BaseChatModel):
    script: list[AIMessage]
    calls: int = 0
    received: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Sequence, **kwargs) -> Runnable:
        # 假 model 不做工具绑定,脚本里已预录 tool_calls
        return self

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs
    ) -> ChatResult:
        if self.calls >= len(self.script):
            raise AssertionError(
                f"假 model 脚本已耗尽(共 {len(self.script)} 条),却被第 {self.calls + 1} 次调用"
            )
        self.received.append(list(messages))
        message = self.script[self.calls]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=message)])
