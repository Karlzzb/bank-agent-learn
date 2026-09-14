"""评测数据集:JSONL 用例的 schema 与加载。

用例即数据:路由/工具断言用确定性的 expect 表达,话术质量用 rubric 交给 LLM 评审。
script 字段是 CI 模式的预录模型脚本(与 tests 的 ScriptedChatModel 同款思路),
让零 API 消耗的 CI 也能走完整断言路径;不带 script 的用例只在 --real 模式运行。
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCallExpect(BaseModel):
    """期望出现的一次工具调用;args_contains 为子集匹配(给出的键值都相等即命中)。"""

    name: str
    args_contains: dict[str, Any] | None = None


class DbEquals(BaseModel):
    """落库断言。id 为空串时表示"存在任一行满足 field==value"(自增 id 不可预知时用)。"""

    table: Literal["customer", "account", "service_request"]
    id: str
    field: str
    value: Any


class Expect(BaseModel):
    """确定性断言集合,全部可选;给出即断言。"""

    route: str | None = None
    tool_calls: list[ToolCallExpect] = Field(default_factory=list)
    reply_contains: list[str] = Field(default_factory=list)
    reply_not_contains: list[str] = Field(default_factory=list)
    db_equals: list[DbEquals] = Field(default_factory=list)


class RouteStep(BaseModel):
    """预录一条 Coordinator 的结构化路由输出。"""

    target: str
    rationale: str = ""
    question: str | None = None


class ToolCallStep(BaseModel):
    """预录一条领域子图的工具调用。"""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ScriptStep(BaseModel):
    """预录脚本的一步:路由决策 / 工具调用 / 直接回复,三者取其一。"""

    route: RouteStep | None = None
    tool_call: ToolCallStep | None = None
    say: str | None = None


class EvalCase(BaseModel):
    """一条评测用例。scopes 为 None 时签全量业务 scope(与演示客户默认一致)。"""

    id: str
    kind: Literal["routing", "tool", "quality"]
    customer: str = "C001"
    input: str
    scopes: list[str] | None = None
    expect: Expect = Field(default_factory=Expect)
    rubric: str = ""  # quality 专属:评分标准
    min_score: int = 4  # quality 专属:评审通过阈值(1-5)
    script: list[ScriptStep] | None = None  # CI 模式预录脚本;缺省则仅 --real 运行
    note: str = ""  # 边界用例的取舍说明,供读报告的人理解断言依据


def load_dataset(path: str | Path) -> list[EvalCase]:
    """加载 JSONL 数据集:每行一个用例,空行跳过。"""
    cases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(EvalCase.model_validate(json.loads(line)))
    return cases


def load_bundled(kinds: set[str] | None = None) -> list[EvalCase]:
    """加载随仓库分发的全部数据集(evals/datasets),可按 kind 过滤。"""
    base = Path(__file__).parent / "datasets"
    cases: list[EvalCase] = []
    for name in ("routing.jsonl", "tools.jsonl", "quality.jsonl"):
        cases.extend(load_dataset(base / name))
    if kinds:
        cases = [c for c in cases if c.kind in kinds]
    return cases
