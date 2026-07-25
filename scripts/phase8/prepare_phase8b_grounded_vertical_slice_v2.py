#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
from review_writer.phase8.phase8b_grounded_revision_v2 import (  # noqa: E402
    build_generation_request,
    build_section_evidence_plan,
    generate_with_bounded_repair,
    prepare_vertical_slice_v2,
)
from review_writer.providers.base import TextGenerationRequest  # noqa: E402
from review_writer.providers.openai_compatible_provider import (  # noqa: E402
    DEFAULT_QWEN_MODEL,
    OpenAICompatibleProvider,
)


WORKSPACE_PARENT = REPO_ROOT.parent / "AI_REVIEW_WORKSPACES"
CLOSURE_RUN_ID = "phase8a_closure_v3_1_1_20260714T120245Z"
V1_RUN_ID = "phase8b_grounded_vertical_slice_20260714T125822Z"
FINAL_CLAIMS_SHA256 = "c2aae9212fe798f94e1aca3637d6c7ee24e0f6980c89c9c1e6fc870045c80352"
CLOSURE_MANIFEST_SHA256 = "cef91cc2b48fc40f20275e6db1d258d5adae3a295016d52893c2230d81d3a3cd"
PHASE7_CLAIMS_SHA256 = "86fbe3c1328b1a836cb410cbcd120520209c3e1d5f728e385064aff98c4de894"
V1_MANIFEST_SHA256 = "00b53fd08a900c59e05f1ad14968edcbecb69448f33e79427d6e951f27b57d9b"
RUN_ID_RE = re.compile(r"^phase8b_grounded_vertical_slice_v2_\d{8}T\d{6}Z$")
MODEL_PRIORITY = ("qwen3.7-max", "qwen3.7-plus")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare one Qwen-backed Phase 8B V2 academic-prose vertical slice.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--workspace-parent", type=Path, default=WORKSPACE_PARENT)
    parser.add_argument("--bibliography-metadata", type=Path, default=REPO_ROOT / "demo_projects/clean_3paper_allene_review/inputs/bibliography_verification_summary.json")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--use-qwen", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--mock-response", type=Path, default=None)
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--max-output-tokens", type=int, default=10000)
    parser.add_argument("--connect-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--first-byte-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--total-timeout-seconds", type=float, default=360.0)
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _verify_hash(path: Path, expected: str, label: str) -> str:
    if not path.is_file() or sha256_file(path) != expected:
        raise ValueError(f"{label} hash mismatch")
    return expected


def _verify_hash_manifest(root: Path) -> None:
    manifest = root / "HASH_MANIFEST.sha256"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", maxsplit=1)
        target = (root / relative).resolve()
        if not _is_within(target, root.resolve()) or not target.is_file() or sha256_file(target) != digest:
            raise ValueError(f"existing V1 manifest entry failed: {relative}")


def _git_value(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *arguments], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git metadata lookup failed")
    return completed.stdout.strip()


def _require_clean_head(repo_root: Path) -> str:
    if _git_value(repo_root, "status", "--porcelain"):
        raise ValueError("V2 real generation requires a clean committed worktree")
    return _git_value(repo_root, "rev-parse", "HEAD")


def _run_id_now() -> str:
    return time.strftime("phase8b_grounded_vertical_slice_v2_%Y%m%dT%H%M%SZ", time.gmtime())


def _load_citation_metadata(path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(path)
    rows = payload.get("papers")
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
            "verification_status": row.get("verification_status"),
        }
    if set(metadata) != {"F3I", "F47A", "P403"}:
        raise ValueError("bibliography metadata does not cover F3I, F47A, and P403")
    return metadata


class QwenJsonProvider:
    def __init__(
        self,
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        connect_timeout_seconds: float,
        first_byte_timeout_seconds: float,
        total_timeout_seconds: float,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.provider = OpenAICompatibleProvider.from_env(
            allow_network=True,
            model=model,
            connect_timeout_seconds=connect_timeout_seconds,
            first_byte_timeout_seconds=first_byte_timeout_seconds,
            total_timeout_seconds=total_timeout_seconds,
        )

    def generate(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("kind") == "repair":
            original = request["original_request"]
            messages = [
                {"role": "system", "content": original["system"]},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "repair_previous_json_against_validator_issues",
                            "original_input": {key: value for key, value in original.items() if key not in {"kind", "system"}},
                            "previous_output": request["previous_output"],
                            "validator_issues": request["validator_issues"],
                            "instruction": request["instruction"],
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ]
        else:
            messages = [
                {"role": "system", "content": request["system"]},
                {
                    "role": "user",
                    "content": json.dumps(
                        {key: value for key, value in request.items() if key not in {"kind", "system"}},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ]
        result = self.provider.generate_text(
            TextGenerationRequest(
                messages=messages,
                model=self.model,
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
                response_format="json_object",
            )
        )
        return {
            "status": result.status,
            "content": result.content,
            "metadata": result.metadata,
            "warnings": result.warnings,
        }


class MockJsonProvider:
    def __init__(self, path: Path) -> None:
        self.content = path.read_text(encoding="utf-8")

    def generate(self, _request: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ok",
            "content": self.content,
            "metadata": {
                "model": "offline-mock",
                "region": "offline",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
        }


def _capability_check() -> tuple[str, dict[str, Any]]:
    provider = OpenAICompatibleProvider.from_env(allow_network=True)
    env = provider._safe_env()
    endpoint = provider._resolve_endpoint(env)
    try:
        from openai import OpenAI
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("OpenAI SDK is required for the authorized Qwen capability check") from exc
    api_key = os.environ.get("DASHSCOPE_API_KEY") or ""
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY is missing")
    page = OpenAI(api_key=api_key, base_url=endpoint["base_url"], timeout=20.0).models.list()
    available = {item.id for item in page.data}
    configured = os.environ.get("BAILIAN_MODEL") or DEFAULT_QWEN_MODEL
    candidates = [*MODEL_PRIORITY, configured]
    selected = next((model for model in candidates if model in available), None)
    if selected is None:
        raise ValueError("none of the allowed Qwen models is available in the configured region")
    return selected, {
        "status": "PASS",
        "query_count": 1,
        "method": "OpenAI-compatible models.list",
        "region": endpoint["region"],
        "selected_model": selected,
        "priority": list(MODEL_PRIORITY),
        "third_party_fallback_used": False,
    }


def main() -> int:
    args = parse_args()
    try:
        repo_root = args.repo_root.resolve()
        workspace_parent = args.workspace_parent.resolve()
        if _is_within(workspace_parent, repo_root):
            raise ValueError("scientific V2 output must remain outside Git")
        if not args.mock_response and not (args.use_qwen and args.allow_network):
            raise ValueError("real generation requires both --use-qwen and --allow-network")
        if args.use_qwen != args.allow_network and not args.mock_response:
            raise ValueError("--use-qwen and --allow-network must be supplied together")
        repo_head = _require_clean_head(repo_root)
        closure = workspace_parent / CLOSURE_RUN_ID
        v1 = workspace_parent / V1_RUN_ID
        final_claims_path = closure / "final/final_reconciled_claims.jsonl"
        closure_manifest_path = closure / "HASH_MANIFEST.sha256"
        phase7_path = repo_root / "local/phase8_evidence/review_queue/phase7_claims.json"
        v1_manifest_path = v1 / "HASH_MANIFEST.sha256"
        input_hashes = {
            "phase8a_final_claims": _verify_hash(final_claims_path, FINAL_CLAIMS_SHA256, "Phase 8A final claims"),
            "phase8a_closure_manifest": _verify_hash(closure_manifest_path, CLOSURE_MANIFEST_SHA256, "Phase 8A closure manifest"),
            "phase7_claims": _verify_hash(phase7_path, PHASE7_CLAIMS_SHA256, "preserved Phase 7 claims"),
            "vertical_slice_v1_manifest": _verify_hash(v1_manifest_path, V1_MANIFEST_SHA256, "existing V1 manifest"),
            "bibliography_metadata": sha256_file(args.bibliography_metadata),
        }
        _verify_hash_manifest(v1)
        final_rows = _read_jsonl(final_claims_path)
        plan = build_section_evidence_plan(final_rows)
        citation_metadata = _load_citation_metadata(args.bibliography_metadata)
        before_section = (v1 / "revision/before_section.md").read_text(encoding="utf-8")
        request = build_generation_request(
            before_section=before_section,
            final_rows=final_rows,
            evidence_plan=plan,
            citation_metadata=citation_metadata,
        )
        if args.mock_response:
            model = "offline-mock"
            capability = {"status": "NOT_USED_OFFLINE_MOCK", "query_count": 0, "region": "offline"}
            provider: Any = MockJsonProvider(args.mock_response)
        else:
            model, capability = _capability_check()
            provider = QwenJsonProvider(
                model=model,
                temperature=args.temperature,
                max_output_tokens=args.max_output_tokens,
                connect_timeout_seconds=args.connect_timeout_seconds,
                first_byte_timeout_seconds=args.first_byte_timeout_seconds,
                total_timeout_seconds=args.total_timeout_seconds,
            )
        generation = generate_with_bounded_repair(provider, request, final_rows, plan, citation_metadata)
        run_id = args.run_id or _run_id_now()
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("invalid V2 run ID")
        run_root = workspace_parent / run_id
        result = prepare_vertical_slice_v2(
            run_root=run_root,
            before_section=before_section,
            final_rows=final_rows,
            evidence_plan=plan,
            citation_metadata=citation_metadata,
            generation=generation,
            run_manifest={
                "run_id": run_id,
                "repo_head": repo_head,
                "input_hashes": input_hashes,
                "model": model,
                "capability_check": capability,
                "generation_parameters": {
                    "temperature": args.temperature,
                    "max_output_tokens": args.max_output_tokens,
                    "response_format": "json_object",
                    "thinking_enabled": False,
                    "search_enabled": False,
                    "maximum_generation_requests": 2,
                },
            },
        )
        current_hashes = {
            "phase8a_final_claims": sha256_file(final_claims_path),
            "phase8a_closure_manifest": sha256_file(closure_manifest_path),
            "phase7_claims": sha256_file(phase7_path),
            "vertical_slice_v1_manifest": sha256_file(v1_manifest_path),
            "bibliography_metadata": sha256_file(args.bibliography_metadata),
        }
        if current_hashes != input_hashes:
            raise RuntimeError("a frozen input changed during V2 generation")
        _verify_hash_manifest(v1)
        print(json.dumps({"status": result["status"], **result}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:  # noqa: BLE001
        print(f"phase8b-grounded-vertical-slice-v2: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
