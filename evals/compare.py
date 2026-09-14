"""报告对比:python -m evals.compare <old.json> <new.json>

按 case id 对齐两份报告,展示状态翻转与评审分数变化,
回答"这次改动(换模型/改 prompt)让哪些用例变好、哪些变坏"。
"""

import argparse
import json
import sys
from pathlib import Path


def _load(path: str) -> tuple[dict, dict[str, dict]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload["meta"], {c["case_id"]: c for c in payload["cases"]}


def _fmt_meta(meta: dict) -> str:
    return (
        f"{meta.get('model')} @ {meta.get('git_sha')}"
        f"(prompts {meta.get('prompts_sha256_12')},{meta.get('timestamp_utc')})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.compare", description="对比两份评测报告")
    parser.add_argument("old", help="旧报告 JSON 路径")
    parser.add_argument("new", help="新报告 JSON 路径")
    args = parser.parse_args(argv)

    old_meta, old = _load(args.old)
    new_meta, new = _load(args.new)
    print(f"old:{_fmt_meta(old_meta)}")
    print(f"new:{_fmt_meta(new_meta)}")
    print()

    fixed = broken = score_changed = 0
    for case_id in sorted(set(old) | set(new)):
        o, n = old.get(case_id), new.get(case_id)
        if o is None:
            print(f"+ {case_id}:新增用例({'PASS' if n['passed'] else 'FAIL'})")
            continue
        if n is None:
            print(f"- {case_id}:用例已移除")
            continue
        if o["passed"] != n["passed"]:
            if n["passed"]:
                fixed += 1
                print(f"  {case_id}:FAIL -> PASS")
            else:
                broken += 1
                print(f"  {case_id}:PASS -> FAIL:{';'.join(n['failures'])}")
        old_score, new_score = o.get("score"), n.get("score")
        if old_score is not None and new_score is not None and old_score != new_score:
            score_changed += 1
            print(f"  {case_id}:得分 {old_score} -> {new_score}")

    old_passed = sum(1 for c in old.values() if c["passed"])
    new_passed = sum(1 for c in new.values() if c["passed"])
    print()
    print("| 指标 | old | new | 差异 |")
    print("| --- | --- | --- | --- |")
    print(f"| 用例总数 | {len(old)} | {len(new)} | {len(new) - len(old):+d} |")
    print(f"| 通过数 | {old_passed} | {new_passed} | {new_passed - old_passed:+d} |")
    print(f"| 新通过(原失败) | - | - | {fixed} |")
    print(f"| 新失败(原通过) | - | - | {broken} |")
    print(f"| 分数变化 | - | - | {score_changed} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
