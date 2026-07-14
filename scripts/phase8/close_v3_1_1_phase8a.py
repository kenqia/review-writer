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

from review_writer.phase8.v3_1_1_closure import prepare_phase8a_closure  # noqa: E402


WORKSPACE_PARENT = REPO_ROOT.parent / "AI_REVIEW_WORKSPACES"
RECONCILIATION_RUN_ID = "phase8_final_reconciliation_v3_1_1_20260714T103554Z"
LAYER_A_RUN_ID = "phase8_source_first_v3_1_1_20260713T150606Z"
LAYER_B_RUN_ID = "phase8_exact_claim_layer_b_v3_1_1_20260714T055239Z"
RECONCILIATION_MANIFEST_SHA256 = "c62f219d6bda0329d72fcb4b2a2426e7b4a127d24e045370ace8b147e25a7a58"
LAYER_A_RESULTS_SHA256 = "94757ac4bf7517655633a5b14f23ccc80ed36f3a817e5d16e5889046a03c17da"
LAYER_A_INPUT_MANIFEST_HASH = "013b4ef4af792afe824a74bc6d40e050ea3fd97b83ad3925fc1327f697219715"
LAYER_B_RESULTS_SHA256 = "45fc079357bb013d92d60bdcb38b7237a0a4713d166737c6cc6670e73618ec68"
LAYER_B_OUTPUT_MANIFEST_SHA256 = "989f5dd1bdd6f167b757ffc24bc25ab05470c9fc69c0bdba673950ed021db73e"
LAYER_B_INPUT_MANIFEST_HASH = "aeb3b5f012a66f821bff109b9108843f6d52b076d2c99eda468068d443c68508"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply four confirmed human spot checks and close Phase 8A.")
    parser.add_argument("--confirmed-response", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--workspace-parent", type=Path, default=WORKSPACE_PARENT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--decision-time-utc", default=None)
    return parser.parse_args()


def git_value(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git metadata lookup failed")
    return completed.stdout.strip()


def require_pushed_clean_head(repo_root: Path) -> str:
    if git_value(repo_root, "status", "--porcelain"):
        raise ValueError("Phase 8A closure requires a clean committed worktree")
    head = git_value(repo_root, "rev-parse", "HEAD")
    if head != git_value(repo_root, "rev-parse", "@{upstream}"):
        raise ValueError("Phase 8A closure requires HEAD to equal its pushed upstream")
    return head


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_id_now() -> str:
    return time.strftime("phase8a_closure_v3_1_1_%Y%m%dT%H%M%SZ", time.gmtime())


def main() -> int:
    args = parse_args()
    try:
        repo_root = args.repo_root.resolve()
        parent = args.workspace_parent.resolve()
        result = prepare_phase8a_closure(
            repo_root=repo_root,
            output_parent=parent,
            run_id=args.run_id or run_id_now(),
            reconciliation_run=parent / RECONCILIATION_RUN_ID,
            layer_a_workspace=parent / LAYER_A_RUN_ID / "layerA_inventory",
            layer_b_workspace=parent / LAYER_B_RUN_ID / "layerB_exact_claim_verifier",
            confirmed_response_path=args.confirmed_response,
            decision_time_utc=args.decision_time_utc or utc_now(),
            coordinator_repo_head=require_pushed_clean_head(repo_root),
            expected_reconciliation_manifest_sha256=RECONCILIATION_MANIFEST_SHA256,
            expected_layer_a_results_sha256=LAYER_A_RESULTS_SHA256,
            expected_layer_a_input_manifest_hash=LAYER_A_INPUT_MANIFEST_HASH,
            expected_layer_b_results_sha256=LAYER_B_RESULTS_SHA256,
            expected_layer_b_output_manifest_sha256=LAYER_B_OUTPUT_MANIFEST_SHA256,
            expected_layer_b_input_manifest_hash=LAYER_B_INPUT_MANIFEST_HASH,
            previous_human_budget_used=6,
        )
        print(json.dumps({"status": "PASS", **result}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"phase8-v3.1.1-closure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
