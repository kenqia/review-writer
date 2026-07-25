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

from review_writer.phase8.phase8b_grounded_revision import prepare_grounded_vertical_slice  # noqa: E402


WORKSPACE_PARENT = REPO_ROOT.parent / "AI_REVIEW_WORKSPACES"
CLOSURE_RUN_ID = "phase8a_closure_v3_1_1_20260714T120245Z"
FINAL_CLAIMS_SHA256 = "c2aae9212fe798f94e1aca3637d6c7ee24e0f6980c89c9c1e6fc870045c80352"
CLOSURE_MANIFEST_SHA256 = "cef91cc2b48fc40f20275e6db1d258d5adae3a295016d52893c2230d81d3a3cd"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare one offline Phase 8B grounded-review vertical slice.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--workspace-parent", type=Path, default=WORKSPACE_PARENT)
    parser.add_argument("--phase7-claims", type=Path, default=REPO_ROOT / "local/phase8_evidence/review_queue/phase7_claims.json")
    parser.add_argument("--expected-phase7-claims-sha256", required=True)
    parser.add_argument("--run-id", default=None)
    return parser.parse_args()


def git_value(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git metadata lookup failed")
    return completed.stdout.strip()


def require_clean_head(repo_root: Path) -> str:
    if git_value(repo_root, "status", "--porcelain"):
        raise ValueError("Phase 8B vertical-slice generation requires a clean committed worktree")
    return git_value(repo_root, "rev-parse", "HEAD")


def run_id_now() -> str:
    return time.strftime("phase8b_grounded_vertical_slice_%Y%m%dT%H%M%SZ", time.gmtime())


def main() -> int:
    args = parse_args()
    try:
        repo_root = args.repo_root.resolve()
        parent = args.workspace_parent.resolve()
        closure = parent / CLOSURE_RUN_ID
        result = prepare_grounded_vertical_slice(
            repo_root=repo_root,
            output_parent=parent,
            run_id=args.run_id or run_id_now(),
            final_claims_path=closure / "final/final_reconciled_claims.jsonl",
            closure_manifest_path=closure / "HASH_MANIFEST.sha256",
            phase7_claims_path=args.phase7_claims,
            expected_final_claims_sha256=FINAL_CLAIMS_SHA256,
            expected_closure_manifest_sha256=CLOSURE_MANIFEST_SHA256,
            expected_phase7_claims_sha256=args.expected_phase7_claims_sha256,
            repo_head=require_clean_head(repo_root),
        )
        print(json.dumps({"status": "PASS", **result}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"phase8b-grounded-vertical-slice: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
