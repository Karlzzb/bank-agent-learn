"""LLM-as-judge:话术质量评审,仅 --real 模式调用。

质量维度无法规则化断言,交给评审模型按数据集给出的 rubric 打分。
评审输出同样不可信,解析复用项目统一的 parse_json_output;
解析失败由调用方记为 judge_error 且该用例不算通过(不粉饰绿灯)。
"""

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from bank_agent.json_output import parse_json_output
from bank_agent.llm import content_text

JUDGE_PROMPT = """\
你是银行客服对话的质量评审,只依据评分标准打分,不自行添加标准。
评分标准:{rubric}
用户问题:{question}
客服回复:{reply}
只输出 JSON,不要输出其他内容:
{{"score": 1-5 的整数, "reason": "一句中文理由"}}"""


class JudgeVerdict(BaseModel):
    """评审结论:score 1-5,reason 一句中文。"""

    score: int = Field(ge=1, le=5)
    reason: str


async def judge_reply(model: BaseChatModel, rubric: str, question: str, reply: str) -> JudgeVerdict:
    """评审一条回复;输出无法解析时抛 JsonOutputError,由调用方记为 judge_error。"""
    response = await model.ainvoke(
        JUDGE_PROMPT.format(rubric=rubric, question=question, reply=reply)
    )
    return parse_json_output(content_text(response), JudgeVerdict)
