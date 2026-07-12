#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.ai_adjudication import (
    atomic_write_json,
    atomic_write_jsonl,
    build_anonymous_layer3_inputs,
    deterministic_rule_flags,
    initialize_local_ai_state,
    prepare_ab_workspaces,
    read_jsonl,
    utc_run_id,
    validate_ab_pair,
    validate_layer_output,
    validate_workspace,
    write_coordinator_resume,
)


DEFAULT_EVIDENCE_ROOT = Path("local/phase8_evidence")
DEFAULT_WORKSPACE_PARENT = REPO_ROOT.parent / "AI_REVIEW_WORKSPACES"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline Phase 8 context-isolated AI adjudication coordinator.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-ab", help="Prepare and validate the independent A/B input packages.")
    prepare.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    prepare.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    prepare.add_argument("--workspace-parent", type=Path, default=DEFAULT_WORKSPACE_PARENT)
    prepare.add_argument("--run-id", default=None)
    prepare.add_argument("--pr-number", type=int, default=3)
    prepare.add_argument("--random-seed", type=int, default=80421)

    workspace = subparsers.add_parser("validate-workspace")
    workspace.add_argument("--workspace", type=Path, required=True)
    workspace.add_argument("--role", choices=("layer1", "layer2"), required=True)
    workspace.add_argument("--repo-root", type=Path, default=REPO_ROOT)

    pair = subparsers.add_parser("validate-ab")
    pair.add_argument("--layer1", type=Path, required=True)
    pair.add_argument("--layer2", type=Path, required=True)
    pair.add_argument("--repo-root", type=Path, default=REPO_ROOT)

    output = subparsers.add_parser("validate-output")
    output.add_argument("--workspace", type=Path, required=True)
    output.add_argument("--role", choices=("layer1", "layer2"), required=True)

    rules = subparsers.add_parser("run-rules")
    rules.add_argument("--input", type=Path, required=True)
    rules.add_argument("--output", type=Path, required=True)

    layer3 = subparsers.add_parser("build-anonymous-layer3-input")
    layer3.add_argument("--layer1", type=Path, required=True)
    layer3.add_argument("--layer2", type=Path, required=True)
    layer3.add_argument("--coordinator", type=Path, required=True)
    layer3.add_argument("--random-seed", type=int, default=80421)
    return parser.parse_args()


def git_value(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git metadata lookup failed")
    return result.stdout.strip()


def command_prepare(args: argparse.Namespace) -> dict:
    repo_root = args.repo_root.resolve()
    evidence_root = args.evidence_root
    if not evidence_root.is_absolute():
        evidence_root = repo_root / evidence_root
    result = prepare_ab_workspaces(
        repo_root=repo_root,
        evidence_root=evidence_root,
        workspace_parent=args.workspace_parent,
        run_id=args.run_id or utc_run_id(),
        repo_head=git_value(repo_root, "rev-parse", "HEAD"),
        branch=git_value(repo_root, "branch", "--show-current"),
        pr_number=args.pr_number,
        random_seed=args.random_seed,
    )
    pair = validate_ab_pair(Path(result["layer1_workspace"]), Path(result["layer2_workspace"]), repo_root=repo_root)
    if pair["status"] != "PASS":
        raise RuntimeError("prepared A/B packages failed validation: " + "; ".join(pair["issues"]))
    reconciliation = initialize_local_ai_state(evidence_root, result, random_seed=args.random_seed)
    resume = write_coordinator_resume(
        result,
        human_budget_used=reconciliation["effective_human_decisions"],
        blockers=result["input_blockers"],
    )
    return {**result, "pair_validation": pair, "human_reconciliation": reconciliation, "coordinator_resume": str(resume)}


def command_layer3(args: argparse.Namespace) -> dict:
    report1 = validate_layer_output(args.layer1, "layer1")
    report2 = validate_layer_output(args.layer2, "layer2")
    if report1["status"] != "PASS" or report2["status"] != "PASS":
        raise RuntimeError("A/B outputs must pass validation before anonymous packaging")
    rows1 = read_jsonl(args.layer1 / "output/results.jsonl")
    rows2 = read_jsonl(args.layer2 / "output/results.jsonl")
    package, private = build_anonymous_layer3_inputs(rows1, rows2, random_seed=args.random_seed)
    for row in package:
        row["deterministic_rule_flags"] = deterministic_rule_flags(row["candidate_x"]) + deterministic_rule_flags(row["candidate_y"])
    args.coordinator.mkdir(parents=True, exist_ok=True)
    public_path = args.coordinator / "anonymous_layer3_input.jsonl"
    private_path = args.coordinator / "private_layer_mapping.json"
    atomic_write_jsonl(public_path, package)
    atomic_write_json(private_path, private)
    return {"status": "ANONYMOUS_LAYER3_INPUT_BUILT", "item_count": len(package), "public_input": str(public_path), "private_mapping": str(private_path)}


def main() -> int:
    args = parse_args()
    try:
        if args.command == "prepare-ab":
            result = command_prepare(args)
        elif args.command == "validate-workspace":
            result = validate_workspace(args.workspace, args.role, repo_root=args.repo_root)
        elif args.command == "validate-ab":
            result = validate_ab_pair(args.layer1, args.layer2, repo_root=args.repo_root)
        elif args.command == "validate-output":
            result = validate_layer_output(args.workspace, args.role)
        elif args.command == "run-rules":
            rows = read_jsonl(args.input)
            output = [{"blind_task_id": row.get("blind_task_id"), "rule_flags": deterministic_rule_flags(row)} for row in rows]
            atomic_write_jsonl(args.output, output)
            result = {"status": "RULES_WRITTEN", "item_count": len(output), "output": str(args.output)}
        else:
            result = command_layer3(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.get("status") not in {"FAIL"} else 1
    except Exception as exc:
        print(f"phase8-ai-adjudication: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
