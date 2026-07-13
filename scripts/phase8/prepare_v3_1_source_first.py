#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.ai_adjudication import atomic_write_json, read_jsonl, sha256_file
from review_writer.phase8.v2_semantic_inputs import IDENTITY_PROFILES, run_identity_audit
from review_writer.phase8.v3_1_source_first import inspect_source_metadata, prepare_v3_1_workspaces


OLD_V3_RUN_ID = "phase8_source_first_v3_20260713T103618Z"
OLD_V3_FILE_COUNT = 22
OLD_V3_AGGREGATE_SHA256 = "296a3ae2dddd337a640ccc070db75cbccf20bd736b45354f50193498b55582ab"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare isolated V3.1 scientific and calibration Layer A workspaces.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--evidence-root", type=Path, default=Path("local/phase8_evidence"))
    parser.add_argument("--workspace-parent", type=Path, default=REPO_ROOT.parent / "AI_REVIEW_WORKSPACES")
    parser.add_argument("--old-v3-run", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--random-seed", type=int, default=80423)
    parser.add_argument("--pr-number", type=int, default=3)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def git_value(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git metadata lookup failed")
    return completed.stdout.strip()


def run_id_now() -> str:
    return time.strftime("phase8_source_first_v3_1_%Y%m%dT%H%M%SZ", time.gmtime())


def aggregate_tree_hash(root: Path) -> tuple[int, str]:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rows.append(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n")
    return len(rows), hashlib.sha256("".join(rows).encode()).hexdigest()


def instruction_sources(repo_root: Path) -> list[dict[str, str]]:
    candidates = [Path.home() / ".codex/AGENTS.md", repo_root / "AGENTS.md", repo_root / "templates/phase8_source_first_v3_1/AGENTS.override.md"]
    result = []
    for path in candidates:
        if not path.exists():
            continue
        resolved = path.resolve()
        result.append({"configured_path": str(path), "resolved_path": str(resolved), "sha256": sha256_file(resolved)})
    return result


def main() -> int:
    args = parse_args()
    try:
        repo_root = args.repo_root.resolve()
        evidence_root = args.evidence_root if args.evidence_root.is_absolute() else repo_root / args.evidence_root
        workspace_parent = args.workspace_parent.resolve()
        old_v3_run = args.old_v3_run.resolve() if args.old_v3_run else workspace_parent / OLD_V3_RUN_ID
        old_count_before, old_hash_before = aggregate_tree_hash(old_v3_run)
        if (old_count_before, old_hash_before) != (OLD_V3_FILE_COUNT, OLD_V3_AGGREGATE_SHA256):
            raise ValueError(f"frozen V3 integrity mismatch: files={old_count_before} hash={old_hash_before}")
        audits, _ = run_identity_audit(evidence_root)
        bad = {source_id: audit["status"] for source_id, audit in audits.items() if audit["status"] not in {"IDENTITY_VALIDATED_STRONG", "IDENTITY_VALIDATED_PROBABLE"}}
        if bad:
            raise ValueError(f"source identity gate failed: {bad}")
        sources = {
            source_id: evidence_root / "sources" / profile["paper_id"] / f"{source_id}.pdf"
            for source_id, profile in IDENTITY_PROFILES.items()
        }
        metadata = inspect_source_metadata(sources)
        summary = {
            "source_identity_statuses": {source_id: audits[source_id]["status"] for source_id in sorted(audits)},
            "source_page_counts": {source_id: metadata[source_id]["page_count"] for source_id in sorted(metadata)},
            "old_v3_file_count": old_count_before,
            "old_v3_aggregate_sha256": old_hash_before,
        }
        if args.validate_only:
            print(json.dumps({"status": "PASS", **summary}, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        result = prepare_v3_1_workspaces(
            repo_root=repo_root,
            workspace_parent=workspace_parent,
            run_id=args.run_id or run_id_now(),
            sources=sources,
            identity_audits=audits,
            human_events=read_jsonl(evidence_root / "review_decisions/reviewer_1.jsonl"),
            repo_head=git_value(repo_root, "rev-parse", "HEAD"),
            branch=git_value(repo_root, "branch", "--show-current"),
            pr_number=args.pr_number,
            random_seed=args.random_seed,
            instruction_sources=instruction_sources(repo_root),
        )
        old_count_after, old_hash_after = aggregate_tree_hash(old_v3_run)
        if (old_count_after, old_hash_after) != (old_count_before, old_hash_before):
            raise RuntimeError("frozen V3 run changed during V3.1 preparation")
        atomic_write_json(
            Path(result["run_root"]) / "coordinator/OLD_V3_INTEGRITY.json",
            {
                "old_run_id": OLD_V3_RUN_ID,
                "file_count_before": old_count_before,
                "file_count_after": old_count_after,
                "aggregate_sha256_before": old_hash_before,
                "aggregate_sha256_after": old_hash_after,
                "unchanged": True,
            },
        )
        print(json.dumps({"status": "PASS", **summary, **result}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"phase8-v3.1-source-first: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
