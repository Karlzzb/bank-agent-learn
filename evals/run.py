"""评测入口:python -m evals.run

默认 CI 模式:只跑带 script 的确定性用例(ScriptedChatModel,零 API 消耗)。
--real 跑全量用例(真实 LLM,含 quality 评审),消耗 API 额度,只由人手动触发。
有失败用例时进程退出码为 1,供 CI 门禁使用。
"""

import argparse
import asyncio
import sys

from bank_agent.composition import build_for_test
from bank_agent.config import get_settings
from bank_agent.llm import create_chat_model

from .dataset import load_bundled
from .harness import CaseResult, run_case_real, run_case_scripted
from .report import build_meta, write_report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="evals.run", description="银行客服评测套件")
    parser.add_argument("--real", action="store_true", help="用真实 LLM 跑全量用例(消耗 API 额度)")
    parser.add_argument("--kinds", default="", help="按 kind 过滤,逗号分隔,如 routing,tool")
    parser.add_argument("--reports-dir", default="evals/reports", help="报告输出目录")
    parser.add_argument(
        "--concurrency", type=int, default=5, help="--real 模式并发用例数(每用例独立种子库)"
    )
    return parser.parse_args(argv)


async def _run_all(args: argparse.Namespace) -> tuple[list[CaseResult], dict]:
    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()} or None
    cases = load_bundled(kinds=kinds)
    if args.real:
        settings = get_settings()
        model = create_chat_model(settings)
        # 用例间零共享状态(各自临时种子库),可安全并发;semaphore 限制 API 并发
        sem = asyncio.Semaphore(args.concurrency)

        async def run_one_case(case):
            async with sem:
                return await run_case_real(
                    case, lambda db_path: build_for_test(model, db_path), judge_model=model
                )

        results = list(await asyncio.gather(*(run_one_case(c) for c in cases)))
        meta = build_meta(settings.llm_model, "real")
    else:
        scripted = [c for c in cases if c.script]
        results = [await run_case_scripted(case) for case in scripted]
        meta = build_meta("scripted-fake", "ci")
    return results, meta


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results, meta = asyncio.run(_run_all(args))
    json_path, md_path = write_report(results, meta, args.reports_dir)
    failed = [r for r in results if not r.passed]
    print(f"共 {len(results)} 条,通过 {len(results) - len(failed)},失败 {len(failed)}")
    for r in failed:
        print(f"FAIL {r.case_id}: {';'.join(r.failures)}")
    print(f"报告:{json_path} / {md_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
