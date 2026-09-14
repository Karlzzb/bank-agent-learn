"""评测套件自测:随仓库数据集的 scripted 用例全过、失败能判负、报告可写。

整个文件只走 ScriptedChatModel,零真实 LLM 调用;
--real 路径(真实 LLM + 评审)只由人手动跑,不进 pytest。
"""

import json

from evals.dataset import EvalCase, load_bundled
from evals.harness import CaseResult, run_case_scripted
from evals.report import build_meta, write_report


async def test_bundled_scripted_cases_all_pass():
    cases = [c for c in load_bundled() if c.script]
    assert len(cases) == 34  # routing 18 + tool 16;quality 不带 script,仅 --real 跑
    results = [await run_case_scripted(case) for case in cases]
    failed = [r for r in results if not r.passed]
    assert not failed, "\n".join(f"{r.case_id}: {r.failures}" for r in failed)


async def test_harness_marks_wrong_expectation_failed():
    """故意写错期望:route 与 reply_contains 都不匹配,harness 必须判负并给出原因。"""
    case = EvalCase.model_validate(
        {
            "id": "synthetic-fail",
            "kind": "routing",
            "input": "帮我查一下余额",
            "expect": {"route": "transactions", "reply_contains": ["不存在的话术"]},
            "script": [
                {"route": {"target": "accounts", "rationale": "查余额"}},
                {"tool_call": {"name": "query_balance", "args": {}}},
                {"say": "您的余额为 12800.50 元。"},
            ],
        }
    )
    result = await run_case_scripted(case)
    assert not result.passed
    assert any("route" in f for f in result.failures)
    assert any("不存在的话术" in f for f in result.failures)


async def test_harness_marks_wrong_db_expectation_failed():
    """db_equals 断言落库值:期望错误的地址时判负。"""
    case = EvalCase.model_validate(
        {
            "id": "synthetic-db-fail",
            "kind": "tool",
            "input": "把地址改成上海市浦东新区世纪大道 100 号",
            "expect": {
                "db_equals": [
                    {
                        "table": "customer",
                        "id": "C001",
                        "field": "address",
                        "value": "没被改成的地址",
                    }
                ]
            },
            "script": [
                {"route": {"target": "service", "rationale": "改地址"}},
                {
                    "tool_call": {
                        "name": "change_address",
                        "args": {"new_address": "上海市浦东新区世纪大道 100 号"},
                    }
                },
                {"say": "已为您修改联系地址。"},
            ],
        }
    )
    result = await run_case_scripted(case)
    assert not result.passed
    assert any("db:customer" in f for f in result.failures)


def test_report_writes_json_and_markdown(tmp_path):
    results = [CaseResult(case_id="demo", kind="routing", passed=True)]
    json_path, md_path = write_report(results, build_meta("scripted-fake", "ci"), tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"] == {"total": 1, "passed": 1, "failed": 0}
    assert payload["cases"][0]["case_id"] == "demo"
    assert payload["meta"]["model"] == "scripted-fake"
    assert md_path.read_text(encoding="utf-8").startswith("# 评测报告")
