#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.delivery.finished_review import (  # noqa: E402
    EXPECTED_CLOSURE_MANIFEST_SHA256,
    EXPECTED_FINAL_CLAIMS_SHA256,
    authorize_finished_review_model,
    build_finished_review_plan,
    generate_finished_review_with_bounded_repair,
    load_hash_bound_bibliography,
    render_final_review,
    verify_frozen_inputs,
    write_failed_generation_diagnostic,
    write_finished_review_package,
)
from review_writer.docx_links import inspect_docx_citation_links  # noqa: E402
from review_writer.phase8.ai_adjudication import sha256_file  # noqa: E402
from review_writer.providers import OpenAICompatibleProvider, TextGenerationRequest  # noqa: E402


CLOSURE_RUN_ID = "phase8a_closure_v3_1_1_20260714T120245Z"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _select_model(requested_model: str) -> tuple[str, dict[str, Any]]:
    probe = OpenAICompatibleProvider.from_env(allow_network=True)
    env = probe._safe_env()
    endpoint = probe._resolve_endpoint(env)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("the explicit Qwen run requires the openai package") from exc
    api_key = os.environ.get("DASHSCOPE_API_KEY") or ""
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY is missing")
    models = OpenAI(api_key=api_key, base_url=endpoint["base_url"], timeout=20.0).models.list()
    available = {item.id for item in models.data}
    authorization = authorize_finished_review_model(requested_model, available)
    return requested_model, {
        "status": "PASS",
        "query_count": 1,
        "method": "OpenAI-compatible models.list",
        "selected_model": requested_model,
        "authorization": authorization,
        "region": endpoint["region"],
        "endpoint_class": "Alibaba Cloud OpenAI-compatible dedicated workspace endpoint",
        "base_url": "redacted",
    }


class QwenJsonProvider:
    def __init__(self, model: str, args: argparse.Namespace) -> None:
        self.model = model
        self.provider = OpenAICompatibleProvider.from_env(
            allow_network=True,
            model=model,
            connect_timeout_seconds=args.connect_timeout_seconds,
            first_byte_timeout_seconds=args.first_byte_timeout_seconds,
            total_timeout_seconds=args.total_timeout_seconds,
        )
        self.temperature = args.temperature
        self.max_output_tokens = args.max_output_tokens

    def generate(self, request: dict[str, Any]) -> dict[str, Any]:
        system = (
            "You are writing a bounded chemistry mini-review from a closed structured evidence ledger. "
            "Return one JSON object only. Never use outside knowledge, invent a fact, expose hidden reasoning, "
            "or include citation markers in sentence text."
        )
        result = self.provider.generate_text(
            TextGenerationRequest(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(request, ensure_ascii=False, separators=(",", ":"))},
                ],
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


class FileJsonProvider:
    def __init__(self, path: Path) -> None:
        self.content = path.read_text(encoding="utf-8")

    def generate(self, _request: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ok",
            "content": self.content,
            "metadata": {"model": "offline-mock", "region": "offline", "usage": {"total_tokens": 0}},
            "warnings": [],
        }


def _export_docx(markdown: str, python_executable: Path, repo_root: Path) -> tuple[Path, dict[str, Any], tempfile.TemporaryDirectory[str]]:
    temporary = tempfile.TemporaryDirectory(prefix="finished-review-docx-")
    root = Path(temporary.name)
    markdown_path = root / "final_review.md"
    docx_path = root / "final_review.docx"
    markdown_path.write_text(markdown, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    result = subprocess.run(
        [
            str(python_executable),
            str(repo_root / "skills/review-export-docx/scripts/md2docx.py"),
            "--input",
            str(markdown_path),
            "--output",
            str(docx_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode or not docx_path.is_file():
        temporary.cleanup()
        raise RuntimeError(f"DOCX export failed: {result.stderr.strip() or result.stdout.strip()}")
    integrity = inspect_docx_citation_links(docx_path)
    if integrity["reference_ids"] != [1, 2, 3] or integrity["cited_reference_ids"] != [1, 2, 3]:
        temporary.cleanup()
        raise ValueError("DOCX does not bind all three numbered references")
    if integrity["bookmark_count"] != 3 or integrity["doi_hyperlink_count"] != 3:
        temporary.cleanup()
        raise ValueError("DOCX bookmark or DOI link count is incomplete")
    return docx_path, integrity, temporary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the first complete bounded evidence-grounded mini-review.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--workspace-parent", type=Path, default=Path(os.environ.get("AI_REVIEW_WORKSPACES", Path.home() / "my_folder/AI_REVIEW_WORKSPACES")))
    parser.add_argument("--output-parent", type=Path, default=REPO_ROOT / "review-projects")
    parser.add_argument("--run-id")
    parser.add_argument("--docx-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--use-qwen", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--mock-response", type=Path)
    parser.add_argument("--bibliography", type=Path, required=True, help="External bibliography JSON with schema finished-review-bibliography-1.0.")
    parser.add_argument("--bibliography-sha256", required=True, help="Exact SHA-256 of --bibliography.")
    parser.add_argument("--model", default="qwen3.7-max", help="Exact authorized model identity; no fallback is available.")
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--max-output-tokens", type=int, default=16000)
    parser.add_argument("--connect-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--first-byte-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--total-timeout-seconds", type=float, default=600.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.mock_response is None and not (args.use_qwen and args.allow_network):
            raise ValueError("real generation requires both --use-qwen and --allow-network")
        if args.mock_response is not None and (args.use_qwen or args.allow_network):
            raise ValueError("mock and network generation modes are mutually exclusive")
        repo_root = args.repo_root.resolve()
        if args.mock_response is None and _git(repo_root, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("real generation requires a clean committed tracked worktree")
        repo_head = _git(repo_root, "rev-parse", "HEAD")
        closure_root = args.workspace_parent.resolve() / CLOSURE_RUN_ID
        claims_path = closure_root / "final/final_reconciled_claims.jsonl"
        manifest_path = closure_root / "HASH_MANIFEST.sha256"
        input_hashes = verify_frozen_inputs(
            claims_path,
            manifest_path,
            EXPECTED_FINAL_CLAIMS_SHA256,
            EXPECTED_CLOSURE_MANIFEST_SHA256,
        )
        bibliography = load_hash_bound_bibliography(args.bibliography, args.bibliography_sha256)
        input_hashes["bibliography_sha256"] = args.bibliography_sha256
        final_rows = _read_jsonl(claims_path)
        evidence_plan = build_finished_review_plan(final_rows)
        run_id = args.run_id or time.strftime("case-01-allene-mini-review-%Y%m%dT%H%M%SZ", time.gmtime())
        if not run_id.startswith("case-01-allene-mini-review-") or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
            raise ValueError("invalid run ID")
        output_root = args.output_parent.resolve() / run_id

        if args.mock_response:
            selected_model = "offline-mock"
            capability = {"status": "NOT_USED_OFFLINE_MOCK", "query_count": 0, "region": "offline"}
            provider: Any = FileJsonProvider(args.mock_response)
            model_authorization = {"model": selected_model, "authorization_id": "offline-fixture", "provider_identity": "offline"}
        else:
            selected_model, capability = _select_model(args.model)
            provider = QwenJsonProvider(selected_model, args)
            model_authorization = capability["authorization"]
        generation = generate_finished_review_with_bounded_repair(
            provider, final_rows, evidence_plan, bibliography,
            failure_package_root=output_root.with_name(f"{output_root.name}-generation-failure"),
            model_authorization=model_authorization,
            input_hashes=input_hashes,
        )
        if generation["validation"]["blockers"]:
            diagnostic_root = output_root.with_name(f"{output_root.name}-failed")
            write_failed_generation_diagnostic(
                output_root=diagnostic_root,
                payload=generation["payload"],
                final_rows=final_rows,
                bibliography_metadata=bibliography,
                validation=generation["validation"],
                generation_manifest={
                    "actual_model": selected_model,
                    "request_count": generation["request_count"],
                    "repair_used": generation["repair_used"],
                    "attempts": generation["attempts"],
                    "capability_check": capability,
                    "repo_head": repo_head,
                    "input_hashes": input_hashes,
                },
            )
            raise ValueError(f"Qwen output retained blockers after bounded repair: {generation['validation']['blockers']}")
        markdown, _citations = render_final_review(generation["payload"], final_rows, bibliography)
        docx_path, docx_integrity, temporary = _export_docx(markdown, args.docx_python.resolve(), repo_root)
        try:
            generation_manifest = {
                "schema_version": "finished-review-generation-1.0",
                "provider": "alibaba_openai_compatible" if args.mock_response is None else "offline-mock",
                "endpoint_class": capability.get("endpoint_class", "offline"),
                "base_url": "redacted" if args.mock_response is None else "not_used",
                "actual_model": selected_model,
                "request_count": generation["request_count"],
                "maximum_completion_requests": 2,
                "repair_used": generation["repair_used"],
                "attempts": generation["attempts"],
                "parameters": {
                    "temperature": args.temperature,
                    "max_output_tokens": args.max_output_tokens,
                    "response_format": "json_object",
                    "thinking_enabled": False,
                    "search_enabled": False,
                },
                "capability_check": capability,
                "repo_head": repo_head,
                "input_hashes": input_hashes,
                "docx_integrity": docx_integrity,
            }
            result = write_finished_review_package(
                output_root=output_root,
                payload=generation["payload"],
                final_rows=final_rows,
                bibliography_metadata=bibliography,
                evidence_plan=evidence_plan,
                generation_manifest=generation_manifest,
                qoderwork_status="MANUAL_QODERWORK_EXECUTION_REQUIRED",
                docx_source=docx_path,
                docx_integrity=docx_integrity,
            )
        finally:
            temporary.cleanup()
        current = verify_frozen_inputs(
            claims_path,
            manifest_path,
            EXPECTED_FINAL_CLAIMS_SHA256,
            EXPECTED_CLOSURE_MANIFEST_SHA256,
        )
        if current != input_hashes:
            raise RuntimeError("a frozen input changed during finished-review delivery")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "stage": result["stage"],
                    "output_root": str(output_root),
                    "final_review_md_sha256": sha256_file(output_root / "final_review.md"),
                    "final_review_docx_sha256": sha256_file(output_root / "final_review.docx"),
                    "word_count": result["word_count"],
                    "model": selected_model,
                    "request_count": generation["request_count"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"finished-review-delivery: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
