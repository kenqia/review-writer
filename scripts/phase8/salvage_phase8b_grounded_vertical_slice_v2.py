#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.ai_adjudication import _is_within, sha256_file  # noqa: E402
from review_writer.phase8.phase8b_salvage import (  # noqa: E402
    build_issue_reclassification,
    prepare_salvage_run,
    salvage_attempt2,
    validate_salvaged_payload,
)


WORKSPACE_PARENT = REPO_ROOT.parent / "AI_REVIEW_WORKSPACES"
SOURCE_RUN_ID = "phase8b_grounded_vertical_slice_v2_20260714T143932Z"
CLOSURE_RUN_ID = "phase8a_closure_v3_1_1_20260714T120245Z"
V1_RUN_ID = "phase8b_grounded_vertical_slice_20260714T125822Z"
RUN_ID_RE = re.compile(r"^phase8b_grounded_vertical_slice_v2_salvaged_\d{8}T\d{6}Z$")
EXPECTED_HASHES = {
    "attempt2": "47379d2d1b74a281fe203af8d26a0f586a438eebb5c07191b09586c6a767ce37",
    "source_evidence_plan": "d22f8bf5e33eb81d8a55aaced0446f38ce0e375984e3754fc99640076b983764",
    "source_run_manifest": "e4989d774a364d565095b6444588461c936c3712e395fbad69cf43df3bf69b7a",
    "source_validation": "f1fe924a2323eede3bed94d4f62376e83bf0bc649fa9defb1241858a2dd84641",
    "phase8a_final_claims": "c2aae9212fe798f94e1aca3637d6c7ee24e0f6980c89c9c1e6fc870045c80352",
    "phase8a_closure_manifest": "cef91cc2b48fc40f20275e6db1d258d5adae3a295016d52893c2230d81d3a3cd",
    "phase7_claims": "86fbe3c1328b1a836cb410cbcd120520209c3e1d5f728e385064aff98c4de894",
    "vertical_slice_v1_manifest": "00b53fd08a900c59e05f1ad14968edcbecb69448f33e79427d6e951f27b57d9b",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministically salvage the frozen Phase 8B Attempt 2 output.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--workspace-parent", type=Path, default=WORKSPACE_PARENT)
    parser.add_argument("--bibliography-metadata", type=Path, default=REPO_ROOT / "demo_projects/clean_3paper_allene_review/inputs/bibliography_verification_summary.json")
    parser.add_argument("--run-id", default=None)
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _verify_hash(path: Path, expected: str, label: str) -> str:
    if not path.is_file() or sha256_file(path) != expected:
        raise ValueError(f"{label} hash mismatch")
    return expected


def _verify_manifest(root: Path) -> None:
    for line in (root / "HASH_MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", maxsplit=1)
        target = (root / relative).resolve()
        if not _is_within(target, root.resolve()) or not target.is_file() or sha256_file(target) != digest:
            raise ValueError(f"source run manifest entry failed: {relative}")


def _git_value(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *arguments], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git metadata lookup failed")
    return completed.stdout.strip()


def _require_clean_head(repo_root: Path) -> str:
    if _git_value(repo_root, "status", "--porcelain"):
        raise ValueError("salvage generation requires a clean committed worktree")
    return _git_value(repo_root, "rev-parse", "HEAD")


def _load_citation_metadata(path: Path) -> dict[str, dict[str, Any]]:
    rows = _read_json(path).get("papers")
    if not isinstance(rows, list):
        raise ValueError("bibliography metadata lacks papers")
    metadata = {}
    for row in rows:
        paper_id = row.get("candidate_id")
        if paper_id not in {"F3I", "F47A", "P403"}:
            continue
        doi = row.get("doi_draft")
        metadata[paper_id] = {
            "title": row.get("verified_title_draft"),
            "authors": row.get("authors_draft") or [],
            "year": row.get("year_draft"),
            "journal": row.get("journal_draft"),
            "doi": None if doi in (None, "", "unknown") else doi,
        }
    if set(metadata) != {"F3I", "F47A", "P403"}:
        raise ValueError("bibliography metadata does not cover the three paper IDs")
    return metadata


def _run_id_now() -> str:
    return time.strftime("phase8b_grounded_vertical_slice_v2_salvaged_%Y%m%dT%H%M%SZ", time.gmtime())


def main() -> int:
    args = parse_args()
    try:
        repo_root = args.repo_root.resolve()
        workspace_parent = args.workspace_parent.resolve()
        if _is_within(workspace_parent, repo_root):
            raise ValueError("salvage output must remain outside Git")
        repo_head = _require_clean_head(repo_root)
        source_run = workspace_parent / SOURCE_RUN_ID
        closure = workspace_parent / CLOSURE_RUN_ID
        v1 = workspace_parent / V1_RUN_ID
        paths = {
            "attempt2": source_run / "reports/raw_model_response_attempt_2.json",
            "source_evidence_plan": source_run / "planning/section_evidence_plan.json",
            "source_run_manifest": source_run / "HASH_MANIFEST.sha256",
            "source_validation": source_run / "reports/prose_validation.json",
            "phase8a_final_claims": closure / "final/final_reconciled_claims.jsonl",
            "phase8a_closure_manifest": closure / "HASH_MANIFEST.sha256",
            "phase7_claims": repo_root / "local/phase8_evidence/review_queue/phase7_claims.json",
            "vertical_slice_v1_manifest": v1 / "HASH_MANIFEST.sha256",
        }
        input_hashes = {
            key: _verify_hash(paths[key], EXPECTED_HASHES[key], key)
            for key in EXPECTED_HASHES
        }
        input_hashes["bibliography_metadata"] = sha256_file(args.bibliography_metadata)
        _verify_manifest(source_run)
        raw_payload = _read_json(paths["attempt2"])
        final_rows = _read_jsonl(paths["phase8a_final_claims"])
        old_validation = _read_json(paths["source_validation"])
        salvage = salvage_attempt2(raw_payload, final_rows)
        validation = validate_salvaged_payload(salvage["payload"], final_rows)
        reclassification = build_issue_reclassification(old_validation, raw_payload, final_rows)
        run_id = args.run_id or _run_id_now()
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("invalid salvage run ID")
        result = prepare_salvage_run(
            run_root=workspace_parent / run_id,
            original_payload=raw_payload,
            salvage=salvage,
            validation=validation,
            issue_reclassification=reclassification,
            citation_metadata=_load_citation_metadata(args.bibliography_metadata),
            run_manifest={
                "run_id": run_id,
                "source_run_id": SOURCE_RUN_ID,
                "repo_head": repo_head,
                "input_hashes": input_hashes,
                "salvage_mode": "DETERMINISTIC_NO_MODEL_CALL",
            },
        )
        current_hashes = {key: sha256_file(path) for key, path in paths.items()}
        current_hashes["bibliography_metadata"] = sha256_file(args.bibliography_metadata)
        if current_hashes != input_hashes:
            raise RuntimeError("a frozen salvage input changed during generation")
        _verify_manifest(source_run)
        print(
            json.dumps(
                {
                    **result,
                    "blocker_count": validation["blocker_count"],
                    "warning_count": validation["warning_count"],
                    "sentence_count": validation["sentence_count"],
                    "selected_claim_count": validation["selected_claim_count"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if validation["blocker_count"] == 0 else 1
    except Exception as exc:  # noqa: BLE001
        print(f"phase8b-salvage: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
