#!/usr/bin/env python3
"""Thin, offline CLI for the authoritative vertical review projection."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.project.vertical_review import (  # noqa: E402
    VerticalReviewError,
    apply_risk_decisions,
    benchmark_metrics,
    build_risk_packet,
    build_writer_packet,
    initialize_review,
    register_study,
)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _print_summary(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")),
        file=stream,
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
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
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _decision_counts(projection: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "approved_claim_count": sum(row.get("decision") == "APPROVED" for row in projection),
        "blocked_claim_count": sum(row.get("decision") == "BLOCKED" for row in projection),
        "human_required_claim_count": sum(
            row.get("decision") == "HUMAN_REQUIRED" for row in projection
        ),
    }


def _prepare_status(project: Path, study_id: str) -> dict[str, Any]:
    benchmark_metrics(project)
    if not study_id.strip():
        raise VerticalReviewError("STUDY_ID_INVALID", "study_id must be nonempty")
    manifest_path = project / "00_discovery" / "acquisition_manifest.json"
    if not manifest_path.is_file():
        return {
            "command": "prepare-study",
            "reason_code": "ACQUISITION_MANIFEST_MISSING",
            "status": "NOT_READY",
            "study_id": study_id,
        }
    manifest = _load_json(manifest_path)
    downloads = manifest.get("downloads") if isinstance(manifest, dict) else None
    if not isinstance(downloads, list):
        raise VerticalReviewError(
            "ACQUISITION_MANIFEST_INVALID",
            "acquisition manifest requires a downloads list",
        )
    declared = [
        row
        for row in downloads
        if isinstance(row, dict) and row.get("study_id") == study_id
    ]
    if not declared:
        reason = "STUDY_NOT_DECLARED"
    else:
        reason = "TASK3_JOB_STATE_CONTRACT_UNDEFINED"
    return {
        "command": "prepare-study",
        "reason_code": reason,
        "status": "NOT_READY",
        "study_id": study_id,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline vertical review projection.")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--review-root", type=Path, required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--brief", type=Path, required=True)

    prepare = commands.add_parser("prepare-study")
    prepare.add_argument("--project-dir", type=Path, required=True)
    prepare.add_argument("--study-id", required=True)

    batch = commands.add_parser("prepare-batch")
    batch.add_argument("--project-dir", type=Path, required=True)
    batch.add_argument("--study-ids-file", type=Path, required=True)

    register = commands.add_parser("register-study")
    register.add_argument("--project-dir", type=Path, required=True)
    register.add_argument("--candidate", type=Path, required=True)
    register.add_argument("--r0-report", type=Path, required=True)
    register.add_argument("--reviewer", type=Path, required=True)

    risk = commands.add_parser("build-risk-packet")
    risk.add_argument("--project-dir", type=Path, required=True)

    apply = commands.add_parser("apply-risk-decisions")
    apply.add_argument("--project-dir", type=Path, required=True)
    apply.add_argument("--decisions", type=Path, required=True)

    writer = commands.add_parser("build-writer-packet")
    writer.add_argument("--project-dir", type=Path, required=True)

    metrics = commands.add_parser("metrics")
    metrics.add_argument("--project-dir", type=Path, required=True)
    metrics.add_argument("--output", type=Path, required=True)
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "init":
        project = initialize_review(args.review_root, args.project_id, _load_json(args.brief))
        _print_summary(
            {"command": "init", "project_dir": str(project), "status": "INITIALIZED"}
        )
        return 0
    if args.command == "prepare-study":
        summary = _prepare_status(args.project_dir, args.study_id)
        _print_summary(summary)
        return 0 if summary["status"] == "READY" else 3
    if args.command == "prepare-batch":
        study_ids = [line.strip() for line in args.study_ids_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not study_ids or len(study_ids) != len(set(study_ids)):
            raise VerticalReviewError(
                "STUDY_IDS_INVALID",
                "study IDs must be nonempty and unique",
            )
        studies = [_prepare_status(args.project_dir, study_id) for study_id in study_ids]
        ready_count = sum(row["status"] == "READY" for row in studies)
        summary = {
            "command": "prepare-batch",
            "not_ready_count": len(studies) - ready_count,
            "ready_count": ready_count,
            "status": "READY" if ready_count == len(studies) else "NOT_READY",
            "studies": [
                {
                    "reason_code": row["reason_code"],
                    "status": row["status"],
                    "study_id": row["study_id"],
                }
                for row in studies
            ],
        }
        _print_summary(summary)
        return 0 if summary["status"] == "READY" else 3
    if args.command == "register-study":
        result = register_study(
            args.project_dir,
            _load_json(args.candidate),
            _load_json(args.r0_report),
            _load_json(args.reviewer),
        )
        summary = {
            "command": "register-study",
            "status": "REGISTERED",
            "study_id": result["study_id"],
            **_decision_counts(result["claim_projection"]),
        }
        _print_summary(summary)
        return 0
    if args.command == "build-risk-packet":
        packet = build_risk_packet(args.project_dir)
        _print_summary(
            {
                "command": "build-risk-packet",
                "human_required_count": packet["human_required_count"],
                "low_risk_sample_count": packet["low_risk_sample_count"],
                "status": "BUILT",
                "target_count": packet["target_count"],
            }
        )
        return 0
    if args.command == "apply-risk-decisions":
        projection = apply_risk_decisions(args.project_dir, _load_json(args.decisions))
        _print_summary(
            {
                "command": "apply-risk-decisions",
                "status": "APPLIED",
                **_decision_counts(projection),
            }
        )
        return 0
    if args.command == "build-writer-packet":
        packet = build_writer_packet(args.project_dir)
        _print_summary(
            {
                "approved_claim_count": packet["approved_claim_count"],
                "blocked_count": packet["blocked_count"],
                "command": "build-writer-packet",
                "human_required_count": packet["human_required_count"],
                "status": "BUILT",
            }
        )
        return 0
    if args.command == "metrics":
        project = args.project_dir.resolve()
        output = args.output.resolve()
        try:
            output.relative_to(project)
        except ValueError:
            pass
        else:
            raise VerticalReviewError(
                "METRICS_OUTPUT_INSIDE_PROJECT",
                "metrics output must remain outside project persistence",
            )
        metrics = benchmark_metrics(args.project_dir)
        _atomic_write_json(args.output, metrics)
        _print_summary({"command": "metrics", "status": "WRITTEN", **metrics})
        return 0
    raise VerticalReviewError("COMMAND_INVALID", "unsupported command")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except VerticalReviewError as exc:
        _print_summary(
            {"command": args.command, "error_code": exc.code, "status": "ERROR"},
            stream=sys.stderr,
        )
        return 2
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        _print_summary(
            {"command": args.command, "error_code": "INPUT_OR_IO_INVALID", "status": "ERROR"},
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
