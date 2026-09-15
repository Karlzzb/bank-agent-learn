"""评测执行引擎:同一套断言路径跑两种模型后端。

- scripted(CI):ScriptedChatModel 按用例 script 预录输出,零 API 消耗。
- real(--real):真实 LLM,由调用方经 root_factory 注入;quality 用例再过 LLM 评审。

工具调用经 RecordingToolProvider 收集而不是读图状态:领域子图以命令式 ainvoke
内嵌执行,子图内部的 tool_call 消息不回写父图状态(已实测验证),
工具提供者接缝是两种后端共用且确定性的观测点。
每个用例用独立临时种子库,保证 db_equals 断言确定且用例间互不污染。
断言失败只收集不抛出,一次跑完整个数据集再汇总。
"""

import json
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from bank_agent.auth.scopes import ALL_SCOPES
from bank_agent.auth.tokens import AuthContext, issue_token, verify_token
from bank_agent.chat import invoke_chat
from bank_agent.composition import CompositionRoot, build_for_test
from bank_agent.config import Settings
from bank_agent.core.db import init_db, make_engine
from bank_agent.core.models import Account, Customer, ServiceRequest
from bank_agent.core.seed import seed
from bank_agent.json_output import JsonOutputError
from bank_agent.testing.fake_model import ScriptedChatModel

from .dataset import EvalCase, ScriptStep
from .judges import judge_reply

RootFactory = Callable[[str], CompositionRoot]


@dataclass
class CaseResult:
    """单条用例结果:passed=False 时 failures 给出全部失败原因。"""

    case_id: str
    kind: Literal["routing", "tool", "quality"]
    passed: bool
    failures: list[str] = field(default_factory=list)
    score: int | None = None
    judge_reason: str | None = None
    judge_error: str | None = None


class RecordingToolProvider:
    """包装任意 ToolProvider:透传工具,同时记录每次调用(LLM 传入的还原前入参)。"""

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[dict[str, Any]] = []

    async def tools_for(self, domain, auth, pii_map):
        tools = await self._inner.tools_for(domain, auth, pii_map)
        return [self._wrap(tool) for tool in tools]

    def _wrap(self, tool) -> StructuredTool:
        async def call(**kwargs):
            self.calls.append({"name": tool.name, "args": kwargs})
            return await tool.ainvoke(kwargs)

        return StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            coroutine=call,
        )


def scripted_model(steps: list[ScriptStep]) -> ScriptedChatModel:
    """把用例 script 编译成 ScriptedChatModel(evals 自携构造器,不 import tests)。"""
    script: list[AIMessage] = []
    for i, step in enumerate(steps):
        if step.route is not None:
            payload: dict[str, Any] = {
                "target": step.route.target,
                "rationale": step.route.rationale,
            }
            if step.route.question is not None:
                payload["question"] = step.route.question
            script.append(AIMessage(content=json.dumps(payload, ensure_ascii=False)))
        elif step.tool_call is not None:
            script.append(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": step.tool_call.name,
                            "args": step.tool_call.args,
                            "id": f"tc{i}",
                            "type": "tool_call",
                        }
                    ],
                )
            )
        elif step.say is not None:
            script.append(AIMessage(content=step.say))
        else:
            raise ValueError(f"脚本第 {i} 步为空:route / tool_call / say 需取其一")
    return ScriptedChatModel(script=script)


async def run_case_scripted(case: EvalCase) -> CaseResult:
    """CI 模式:预录脚本驱动,零真实 LLM。只应用于带 script 的用例。"""
    model = scripted_model(case.script or [])
    return await _run_case(case, lambda db_path: build_for_test(model, db_path), judge_model=None)


async def run_case_real(
    case: EvalCase, root_factory: RootFactory, judge_model: BaseChatModel | None = None
) -> CaseResult:
    """--real 模式:root_factory(db_path) 用真实 model 建组合根(每用例独立种子库)。"""
    return await _run_case(case, root_factory, judge_model)


async def _run_case(
    case: EvalCase, root_factory: RootFactory, judge_model: BaseChatModel | None
) -> CaseResult:
    tmp = tempfile.mkdtemp(prefix=f"bank-eval-{case.id}-")
    try:
        return await _run_case_in(case, root_factory, judge_model, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # 每用例独立种子库,跑完即清理


async def _run_case_in(
    case: EvalCase, root_factory: RootFactory, judge_model: BaseChatModel | None, tmp: str
) -> CaseResult:
    db_path = str(Path(tmp) / "bank.sqlite3")
    engine = make_engine(db_path)
    init_db(engine)
    with Session(engine) as session:
        seed(session)

    root = root_factory(db_path)
    recorder = RecordingToolProvider(root.tool_provider)
    root.tool_provider = recorder

    try:
        result = await invoke_chat(root, case.input, _make_auth(case))
    except Exception as exc:
        return CaseResult(
            case_id=case.id,
            kind=case.kind,
            passed=False,
            failures=[f"执行异常:{type(exc).__name__}: {exc}"],
        )

    failures = _assert_expect(case, result, recorder.calls, root.engine)
    score = reason = error = None
    if case.kind == "quality":
        if judge_model is None:
            failures.append("quality 用例需要评审模型(仅 --real 模式可评)")
        else:
            try:
                verdict = await judge_reply(judge_model, case.rubric, case.input, result["reply"])
                score, reason = verdict.score, verdict.reason
                if verdict.score < case.min_score:
                    failures.append(
                        f"评审得分 {verdict.score} 低于阈值 {case.min_score}:{verdict.reason}"
                    )
            except JsonOutputError as exc:
                error = str(exc)
                failures.append(f"评审输出解析失败:{exc}")
    return CaseResult(
        case_id=case.id,
        kind=case.kind,
        passed=not failures,
        failures=failures,
        score=score,
        judge_reason=reason,
        judge_error=error,
    )


def _make_auth(case: EvalCase) -> AuthContext:
    """签发与生产一致的 AuthContext;scopes 缺省为全量业务 scope。"""
    settings = Settings()
    scopes = ALL_SCOPES if case.scopes is None else frozenset(case.scopes)
    return verify_token(settings, issue_token(settings, case.customer, scopes))


_TABLES = {"customer": Customer, "account": Account, "service_request": ServiceRequest}

_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d)")


def _strip_thousands(text: str) -> str:
    """去掉数字千分位逗号:reply_contains 断言金额数值,不断言 LLM 的格式化风格。"""
    return _THOUSANDS_RE.sub("", text)


def _assert_expect(case: EvalCase, result: dict, calls: list[dict], engine: Engine) -> list[str]:
    expect = case.expect
    failures: list[str] = []
    if expect.route is not None and result["route"] != expect.route:
        failures.append(f"route 期望 {expect.route},实际 {result['route'] or '(空)'}")
    for wanted in expect.tool_calls:
        matches = [c for c in calls if c["name"] == wanted.name]
        if wanted.args_contains:
            matches = [
                c
                for c in matches
                if all(c["args"].get(k) == v for k, v in wanted.args_contains.items())
            ]
        if not matches:
            actual = [(c["name"], c["args"]) for c in calls]
            failures.append(
                f"缺少工具调用 {wanted.name}(args 含 {wanted.args_contains});实际调用:{actual}"
            )
    reply = result["reply"]
    normalized = _strip_thousands(reply)
    for needle in expect.reply_contains:
        if _strip_thousands(needle) not in normalized:
            failures.append(f"reply 应包含 {needle!r};实际回复:{reply!r}")
    for needle in expect.reply_not_contains:
        if _strip_thousands(needle) in normalized:
            failures.append(f"reply 不应包含 {needle!r};实际回复:{reply!r}")
    failures.extend(_db_failures(case, engine))
    return failures


def _db_failures(case: EvalCase, engine: Engine) -> list[str]:
    failures: list[str] = []
    with Session(engine) as session:
        for d in case.expect.db_equals:
            model = _TABLES[d.table]
            if d.id:
                row = session.get(model, d.id)
                if row is None:
                    failures.append(f"db:{d.table} 不存在 id={d.id}")
                    continue
                actual = getattr(row, d.field, None)
                if not _value_eq(actual, d.value):
                    failures.append(
                        f"db:{d.table}[{d.id}].{d.field} 期望 {d.value!r},实际 {actual!r}"
                    )
            else:
                found = any(
                    _value_eq(getattr(row, d.field, None), d.value)
                    for row in session.exec(select(model)).all()
                )
                if not found:
                    failures.append(f"db:{d.table} 不存在 {d.field}=={d.value!r} 的行")
    return failures


def _value_eq(actual: Any, expected: Any) -> bool:
    """宽松相等:先直接比(StrEnum 与 str 互通),再按字符串比(浮点/枚举兜底)。"""
    return bool(actual == expected) or str(actual) == str(expected)
