"""评测报告:JSON(机器可读,供 compare 对比)与 Markdown(人读)双写。

文件名内嵌 UTC 时间戳与 git 短 sha:多次运行互不覆盖,且能回溯代码版本。
prompts 哈希(sha256 前 12 位)让"改 prompt 前后"的对比有据可查。
"""

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import bank_agent.prompts

from .harness import CaseResult


def git_sha() -> str:
    """当前仓库 git 短 sha;不在 git 环境(如打包容器)时记 unknown。"""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def prompts_hash() -> str:
    """prompts.py 内容的 sha256 前 12 位:prompt 变更的指纹。"""
    return hashlib.sha256(Path(bank_agent.prompts.__file__).read_bytes()).hexdigest()[:12]


def build_meta(model: str, mode: str) -> dict:
    """报告元信息:时间戳、git sha、模型名、运行模式、prompts 哈希。"""
    return {
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": git_sha(),
        "model": model,
        "mode": mode,
        "prompts_sha256_12": prompts_hash(),
    }


def summarize(results: list[CaseResult]) -> dict:
    passed = sum(1 for r in results if r.passed)
    return {"total": len(results), "passed": passed, "failed": len(results) - passed}


def write_report(
    results: list[CaseResult], meta: dict, reports_dir: str | Path
) -> tuple[Path, Path]:
    """写出 JSON 与 Markdown 报告,返回两个文件路径。"""
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{stamp}-{meta['git_sha']}"
    json_path = out / f"{stem}.json"
    md_path = out / f"{stem}.md"
    payload = {
        "meta": meta,
        "summary": summarize(results),
        "cases": [asdict(r) for r in results],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(results, meta), encoding="utf-8")
    return json_path, md_path


def _render_markdown(results: list[CaseResult], meta: dict) -> str:
    summary = summarize(results)
    lines = [
        "# 评测报告",
        "",
        f"- 时间(UTC):{meta['timestamp_utc']}",
        f"- git:{meta['git_sha']}",
        f"- 模型:{meta['model']}",
        f"- 模式:{meta['mode']}",
        f"- prompts 哈希:{meta['prompts_sha256_12']}",
        "",
        "## 汇总",
        "",
        "| 总数 | 通过 | 失败 |",
        "| --- | --- | --- |",
        f"| {summary['total']} | {summary['passed']} | {summary['failed']} |",
        "",
        "## 用例明细",
        "",
    ]
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        score = f",得分 {r.score}" if r.score is not None else ""
        detail = f":{';'.join(r.failures)}" if r.failures else ""
        lines.append(f"- [{status}] {r.case_id}({r.kind}{score}){detail}")
    lines.append("")
    return "\n".join(lines)
