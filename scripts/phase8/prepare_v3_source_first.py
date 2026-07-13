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

from review_writer.phase8.ai_adjudication import read_json, read_jsonl, sha256_file, verify_manifest
from review_writer.phase8.v2_semantic_inputs import IDENTITY_PROFILES, run_identity_audit
from review_writer.phase8.v3_source_first import (
    build_adversarial_dataset,
    prepare_v3_workspace,
    write_v2_diagnostic_markers,
)


DEFAULT_V2_RUN_ID = "phase8_three_layer_v2_20260712T152616Z"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze diagnostic V2 and prepare a V3 source-first Layer A workspace.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--evidence-root", type=Path, default=Path("local/phase8_evidence"))
    parser.add_argument("--workspace-parent", type=Path, default=REPO_ROOT.parent / "AI_REVIEW_WORKSPACES")
    parser.add_argument("--v2-run", type=Path, default=None)
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
    return time.strftime("phase8_source_first_v3_%Y%m%dT%H%M%SZ", time.gmtime())


def validate_v2_artifacts(v2_run: Path) -> dict[str, object]:
    reports = {}
    for layer_name in ("layer1_extractor", "layer2_verifier"):
        workspace = v2_run / layer_name
        input_report = verify_manifest(workspace)
        if not input_report["valid"]:
            raise ValueError(f"V2 {layer_name} input manifest invalid: {input_report['issues']}")
        output_manifest = read_json(workspace / "output/OUTPUT_MANIFEST.json")
        results = workspace / "output/results.jsonl"
        if output_manifest.get("input_manifest_hash") != sha256_file(workspace / "INPUT_MANIFEST.json"):
            raise ValueError(f"V2 {layer_name} output references the wrong input manifest")
        if output_manifest.get("results_sha256") != sha256_file(results):
            raise ValueError(f"V2 {layer_name} results hash mismatch")
        if output_manifest.get("row_count") != 41 or len(read_jsonl(results)) != 41:
            raise ValueError(f"V2 {layer_name} does not have exactly 41 results")
        checksum = (workspace / "output/OUTPUT_MANIFEST.sha256").read_text(encoding="utf-8").split()[0]
        if checksum != sha256_file(workspace / "output/OUTPUT_MANIFEST.json"):
            raise ValueError(f"V2 {layer_name} output manifest checksum mismatch")
        reports[layer_name] = {"input_manifest_hash": input_report["manifest_hash"], "result_count": 41, "results_hash": sha256_file(results)}
    return reports


def main() -> int:
    args = parse_args()
    try:
        repo_root = args.repo_root.resolve()
        evidence_root = args.evidence_root if args.evidence_root.is_absolute() else repo_root / args.evidence_root
        workspace_parent = args.workspace_parent.resolve()
        v2_run = args.v2_run.resolve() if args.v2_run else workspace_parent / DEFAULT_V2_RUN_ID
        v2_validation = validate_v2_artifacts(v2_run)
        adversarial = build_adversarial_dataset(v2_run)
        audits, _ = run_identity_audit(evidence_root)
        bad_identities = {key: value["status"] for key, value in audits.items() if value["status"] not in {"IDENTITY_VALIDATED_STRONG", "IDENTITY_VALIDATED_PROBABLE"}}
        if bad_identities:
            raise ValueError(f"source identity gate failed: {bad_identities}")
        summary = {
            "v2_status": "READY_TO_FREEZE_AS_DIAGNOSTIC",
            "v2_validation": v2_validation,
            "adversarial_item_count": adversarial["item_count"],
            "aggregate_semantic_distribution": adversarial["aggregate_semantic_distribution"],
            "source_identity_statuses": {key: value["status"] for key, value in audits.items()},
        }
        if args.validate_only:
            print(json.dumps({"status": "PASS", **summary}, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        human_events = read_jsonl(evidence_root / "review_decisions/reviewer_1.jsonl")
        sources = {
            source_id: evidence_root / "sources" / profile["paper_id"] / f"{source_id}.pdf"
            for source_id, profile in IDENTITY_PROFILES.items()
        }
        before = {
            path.relative_to(v2_run).as_posix(): sha256_file(path)
            for layer in ("layer1_extractor", "layer2_verifier")
            for path in (v2_run / layer).rglob("*")
            if path.is_file()
        }
        write_v2_diagnostic_markers(v2_run, artifact_validation=v2_validation)
        after = {relative: sha256_file(v2_run / relative) for relative in before}
        if before != after:
            raise RuntimeError("V2 original A/B task or result artifact changed during freeze")
        result = prepare_v3_workspace(
            repo_root=repo_root,
            workspace_parent=workspace_parent,
            run_id=args.run_id or run_id_now(),
            sources=sources,
            identity_audits=audits,
            human_events=human_events,
            adversarial_dataset=adversarial,
            repo_head=git_value(repo_root, "rev-parse", "HEAD"),
            branch=git_value(repo_root, "branch", "--show-current"),
            pr_number=args.pr_number,
            random_seed=args.random_seed,
        )
        print(json.dumps({"status": "PASS", **summary, **result}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"phase8-v3-source-first: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
