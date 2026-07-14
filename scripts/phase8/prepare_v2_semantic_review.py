#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.ai_adjudication import atomic_write_json, atomic_write_text, read_json, read_jsonl
from review_writer.phase8.v2_semantic_inputs import (
    build_v2_semantic_state,
    prepare_v2_workspaces,
    run_identity_audit,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Phase 8 semantic inputs and prepare context-isolated V2 A/B workspaces.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--evidence-root", type=Path, default=Path("local/phase8_evidence"))
    parser.add_argument("--workspace-parent", type=Path, default=REPO_ROOT.parent / "AI_REVIEW_WORKSPACES")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--random-seed", type=int, default=80422)
    parser.add_argument("--pr-number", type=int, default=3)
    return parser.parse_args()


def git_value(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git metadata lookup failed")
    return result.stdout.strip()


def run_id_now() -> str:
    return time.strftime("phase8_three_layer_v2_%Y%m%dT%H%M%SZ", time.gmtime())


def write_local_reports(evidence_root: Path, audits: dict, semantic_state: dict) -> None:
    atomic_write_json(evidence_root / "inventories/source_identity_audit_v2.local.json", {"schema_version": "2.0", "items": list(audits.values())})
    atomic_write_json(evidence_root / "review_queue/v2_active_tasks.local.json", {"schema_version": "2.0", "items": semantic_state["active_tasks"]})
    atomic_write_json(evidence_root / "review_queue/v2_non_adjudicated_statuses.local.json", {"schema_version": "2.0", "items": semantic_state["exclusions"]})
    atomic_write_json(evidence_root / "ai_adjudication/v2_hidden_calibration.private.json", semantic_state["hidden_calibration"])
    report = {
        "schema_version": "2.0",
        "status": semantic_state["preflight"]["status"],
        "active_task_count": len(semantic_state["active_tasks"]),
        "exclusion_counts": semantic_state["exclusion_counts"],
        "mode_counts": semantic_state["mode_counts"],
        "locator_quality_counts": semantic_state["locator_quality_counts"],
        "identity_status_counts": _counts(row["status"] for row in audits.values()),
        "gates": semantic_state["preflight"]["gates"],
        "hidden_calibration_present": semantic_state["hidden_calibration"] is not None,
        "hidden_calibration_publicly_exposed": False,
    }
    atomic_write_json(evidence_root / "reports/v2_semantic_preflight.json", report)
    lines = [
        "# Phase 8 V2 Semantic Preflight",
        "",
        f"- status: `{report['status']}`",
        f"- active tasks: `{report['active_task_count']}`",
        f"- exclusions: `{report['exclusion_counts']}`",
        f"- modes: `{report['mode_counts']}`",
        f"- locator quality: `{report['locator_quality_counts']}`",
        f"- identity status: `{report['identity_status_counts']}`",
        "- hidden calibration: coordinator-private only",
        "",
    ]
    atomic_write_text(evidence_root / "reports/v2_semantic_preflight.md", "\n".join(lines))


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def main() -> int:
    args = parse_args()
    try:
        repo_root = args.repo_root.resolve()
        evidence_root = args.evidence_root
        if not evidence_root.is_absolute():
            evidence_root = repo_root / evidence_root
        audits, pages = run_identity_audit(evidence_root)
        p403_main = audits["P403_MAIN"]
        p403_si = audits["P403_SI"]
        repair = {
            "schema_version": "2.0",
            "P403_MAIN": {key: p403_main.get(key) for key in ("status", "sha256", "detected_dois", "matched_evidence")},
            "P403_SI": {key: p403_si.get(key) for key in ("status", "sha256", "detected_dois", "matched_evidence")},
            "target_doi_family": "10.1021/acscatal.5c05571",
            "source_repair_status": "SOURCE_REPAIR_READY" if p403_main["status"] in {"IDENTITY_VALIDATED_STRONG", "IDENTITY_VALIDATED_PROBABLE"} else "SOURCE_REPAIR_WAITING_FOR_USER",
        }
        atomic_write_json(evidence_root / "reports/p403_source_repair_v2.json", repair)
        if repair["source_repair_status"] != "SOURCE_REPAIR_READY":
            print(json.dumps(repair, ensure_ascii=False, indent=2, sort_keys=True))
            return 2
        core = read_json(evidence_root / "review_queue/core_review_queue.json")["items"]
        human = read_jsonl(evidence_root / "review_decisions/reviewer_1.jsonl")
        semantic_state = build_v2_semantic_state(
            core_items=core,
            human_events=human,
            source_pages=pages,
            identity_audits=audits,
            random_seed=args.random_seed,
        )
        write_local_reports(evidence_root, audits, semantic_state)
        if semantic_state["preflight"]["status"] != "PASS":
            print(json.dumps({"status": "V2_PREFLIGHT_FAILED", **semantic_state["preflight"]}, ensure_ascii=False, indent=2, sort_keys=True))
            return 1
        result = prepare_v2_workspaces(
            repo_root=repo_root,
            evidence_root=evidence_root,
            workspace_parent=args.workspace_parent,
            run_id=args.run_id or run_id_now(),
            semantic_state=semantic_state,
            identity_audits=audits,
            repo_head=git_value(repo_root, "rev-parse", "HEAD"),
            branch=git_value(repo_root, "branch", "--show-current"),
            pr_number=args.pr_number,
            random_seed=args.random_seed,
        )
        print(json.dumps({**result, "identity_statuses": {key: value["status"] for key, value in audits.items()}, "exclusion_counts": semantic_state["exclusion_counts"], "hidden_calibration": "PRIVATE_NOT_PACKAGED"}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"phase8-v2-semantic-inputs: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
