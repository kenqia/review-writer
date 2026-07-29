#!/usr/bin/env python3
"""Validate or build an offline evidence-bound review benchmark report."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.evaluation.review_benchmark import (  # noqa: E402
    BenchmarkError,
    evaluate_review,
    validate_report,
)
from review_writer.evaluation.standard_corpus import (  # noqa: E402
    StandardCorpusError,
    load_standard_corpus,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an offline review benchmark report.")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--standards", type=Path)
    parser.add_argument(
        "--release-level",
        choices=("SELF_REVIEWED_DRAFT", "EXPERT_REVIEWED_RELEASE"),
    )
    parser.add_argument("--scores", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def _read_json(path: Path, code: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise BenchmarkError(code)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkError(code) from exc


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _summary(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")),
        file=stream,
    )


def _run(args: argparse.Namespace) -> int:
    if args.report is not None:
        report = validate_report(_read_json(args.report, "BENCHMARK_REPORT_INVALID"))
        if (
            args.project is None
            or args.standards is None
            or any(value is not None for value in (args.release_level, args.scores, args.output))
        ):
            raise BenchmarkError("BENCHMARK_ARGUMENTS_INVALID")
        score_input = _read_json(
            args.project.resolve() / "06_evaluation/review_benchmark_scores.json",
            "BENCHMARK_SCORE_INPUT_MISSING",
        )
        if not isinstance(score_input, dict):
            raise BenchmarkError("BENCHMARK_SCORES_INVALID")
        canonical = evaluate_review(
            args.project.resolve(),
            score_input.get("rubric", score_input),
            hard_fails=score_input.get("hard_fails", []),
            release_level=report["release_level"],
            standard_corpus=load_standard_corpus(args.standards),
        )
        comparable_report = {key: value for key, value in report.items() if key != "evaluated_at"}
        comparable_canonical = {key: value for key, value in canonical.items() if key != "evaluated_at"}
        if comparable_report != comparable_canonical:
            raise BenchmarkError("BENCHMARK_REPORT_MISMATCH")
        _summary(
            {
                "score": canonical["score"],
                "status": canonical["status"],
                "reason_code": "REPORT_CANONICAL_MATCH",
            }
        )
        return 0 if canonical["status"] != "fail" else 3
    if args.project is None or args.standards is None or args.release_level is None:
        raise BenchmarkError("BENCHMARK_ARGUMENTS_INVALID")
    project = args.project.resolve()
    scores_path = args.scores or project / "06_evaluation/review_benchmark_scores.json"
    output = args.output or project / "06_evaluation/review_benchmark_report.json"
    score_input = _read_json(scores_path, "BENCHMARK_SCORE_INPUT_MISSING")
    if not isinstance(score_input, dict):
        raise BenchmarkError("BENCHMARK_SCORES_INVALID")
    report = evaluate_review(
        project,
        score_input.get("rubric", score_input),
        hard_fails=score_input.get("hard_fails", []),
        release_level=args.release_level,
        standard_corpus=load_standard_corpus(args.standards),
    )
    _atomic_json(output, report)
    _summary(
        {
            "score": report["score"],
            "status": report["status"],
            "reason_code": "REPORT_WRITTEN",
        }
    )
    return 0 if report["status"] != "fail" else 3


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (BenchmarkError, StandardCorpusError) as exc:
        _summary({"error_code": exc.code, "status": "ERROR"}, stream=sys.stderr)
        return 2
    except (OSError, TypeError, ValueError):
        _summary({"error_code": "BENCHMARK_INPUT_OR_IO_INVALID", "status": "ERROR"}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
