from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .ai_adjudication import _is_within, atomic_write_json, atomic_write_jsonl, atomic_write_text, sha256_file


LAYER_B_RUN_ID_RE = re.compile(r"^phase8_exact_claim_layer_b_v3_1_1_\d{8}T\d{6}Z$")
EXPECTED_ROW_COUNT = 8
EXPECTED_CLAIM_COUNT = 44
EXPECTED_SOURCE_CONFLICT_COUNT = 7


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _locator_pages(locator: dict[str, Any]) -> set[int]:
    page = locator.get("pdf_page_index")
    if locator.get("scope") == "EXACT_PAGE":
        if isinstance(page, int) and locator.get("page_window") is None:
            return {page}
        raise ValueError("EXACT_PAGE claim locator is malformed")
    window = locator.get("page_window")
    if (
        locator.get("scope") == "PAGE_WINDOW"
        and isinstance(page, int)
        and isinstance(window, list)
        and len(window) == 2
        and all(isinstance(value, int) for value in window)
        and window[0] <= page <= window[1]
    ):
        return set(range(window[0], window[1] + 1))
    raise ValueError("PAGE_WINDOW claim locator is malformed")


def _claim_allowed_pages(claim: dict[str, Any]) -> list[int]:
    pages = set(_locator_pages(claim["evidence_locator"]))
    conflict = claim.get("source_conflict") or {}
    for alternative in conflict.get("alternatives", []):
        pages.update(_locator_pages(alternative["locator"]))
    return sorted(pages)


def _verifier_task_id(run_id: str, claim_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}\0{claim_id}".encode()).hexdigest()[:16]
    return f"VB-{digest}"


def _schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas/phase8_source_first_v3_1_1_layer_b"


def _template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "templates/phase8_source_first_v3_1_1_layer_b"


def _write_pdf_slice(source: Path, destination: Path, page_positions: list[int]) -> None:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required to package Layer B source slices") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as original:
        sliced = fitz.open()
        try:
            for page_position in page_positions:
                sliced.insert_pdf(original, from_page=page_position, to_page=page_position)
            sliced.save(destination)
        finally:
            sliced.close()


def _manifest_files(workspace: Path) -> list[dict[str, Any]]:
    paths = [workspace / "AGENTS.override.md", workspace / "WORK_ORDER.md"]
    for directory in ("sources", "input", "schemas"):
        paths.extend(path for path in (workspace / directory).rglob("*") if path.is_file())
    return [
        {"path": path.relative_to(workspace).as_posix(), "sha256": sha256_file(path), "size": path.stat().st_size}
        for path in sorted(paths)
    ]


def _write_checksum_file(workspace: Path, manifest: dict[str, Any]) -> None:
    rows = [f"{sha256_file(workspace / 'INPUT_MANIFEST.json')}  INPUT_MANIFEST.json"]
    rows.extend(f"{row['sha256']}  {row['path']}" for row in manifest["files"])
    atomic_write_text(workspace / "INPUT_MANIFEST.sha256", "\n".join(rows) + "\n")


def _freeze_inputs(workspace: Path) -> None:
    for relative in ("AGENTS.override.md", "WORK_ORDER.md", "INPUT_MANIFEST.json", "INPUT_MANIFEST.sha256"):
        os.chmod(workspace / relative, 0o444)
    for directory in ("sources", "input", "schemas"):
        for path in (workspace / directory).rglob("*"):
            if path.is_file():
                os.chmod(path, 0o444)
        for path in sorted((workspace / directory).rglob("*"), reverse=True):
            if path.is_dir():
                os.chmod(path, 0o555)
        os.chmod(workspace / directory, 0o555)
    os.chmod(workspace / "output", 0o755)


def validate_layer_b_workspace(workspace: Path, *, repo_root: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    issues = []
    if _is_within(workspace, repo_root.resolve()):
        issues.append("Layer B workspace must be outside the Git repository")
    if (workspace / ".git").exists():
        issues.append("Layer B workspace contains .git")
    for path in workspace.rglob("*"):
        if path.is_symlink():
            issues.append(f"symlink is forbidden: {path.relative_to(workspace)}")
    verifier = workspace / "input/verify_input_package.py"
    if verifier.is_file():
        completed = subprocess.run([sys.executable, str(verifier)], cwd=workspace, capture_output=True, text=True)
        try:
            package_report = json.loads(completed.stdout)
            issues.extend(package_report.get("issues", []))
        except json.JSONDecodeError:
            issues.append("workspace-local verifier did not return JSON")
    else:
        issues.append("workspace-local verifier is missing")
    for relative in ("AGENTS.override.md", "WORK_ORDER.md", "INPUT_MANIFEST.json", "INPUT_MANIFEST.sha256"):
        path = workspace / relative
        if not path.is_file() or path.stat().st_mode & stat.S_IWUSR:
            issues.append(f"required root input missing or writable: {relative}")
    for directory in ("sources", "input", "schemas"):
        for path in (workspace / directory).rglob("*"):
            if path.is_file() and path.stat().st_mode & stat.S_IWUSR:
                issues.append(f"input file is writable: {path.relative_to(workspace)}")
    output = workspace / "output"
    if not output.is_dir() or not output.stat().st_mode & stat.S_IWUSR:
        issues.append("output directory is missing or not writable")
    allowed_output = {"results.jsonl", "OUTPUT_MANIFEST.json", "OUTPUT_MANIFEST.sha256"}
    actual_output = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()} if output.is_dir() else set()
    if not actual_output.issubset(allowed_output):
        issues.append("output contains a file outside the closed output set")
    task_path = workspace / "input/verifier_tasks.jsonl"
    if task_path.is_file():
        folded = task_path.read_text(encoding="utf-8", errors="replace").casefold()
        for forbidden in ("locator_scope", "private_calibration", "reviewer_note", "final_decision", "reviewer_1.jsonl", "human_review_required"):
            if forbidden in folded:
                issues.append(f"forbidden context leaked into verifier tasks: {forbidden}")
    for path in workspace.rglob("*"):
        if not path.is_file() or path.suffix.lower() == ".pdf":
            continue
        text = path.read_text(encoding="utf-8", errors="replace").casefold()
        if str(repo_root.resolve()).casefold() in text or re.search(r"(?:^|[\s\"'])/(?:home|users|mnt)/", text):
            issues.append(f"absolute path leaked in {path.relative_to(workspace)}")
    manifest_hash = sha256_file(workspace / "INPUT_MANIFEST.json") if (workspace / "INPUT_MANIFEST.json").is_file() else None
    tasks = _read_jsonl(task_path) if task_path.is_file() else []
    return {"status": "PASS" if not issues else "FAIL", "issues": sorted(set(issues)), "task_count": len(tasks), "manifest_hash": manifest_hash}


def _verify_upstream(
    layer_a_workspace: Path,
    *,
    expected_results_sha256: str,
    expected_input_manifest_hash: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    results_path = layer_a_workspace / "output/results.jsonl"
    input_manifest_path = layer_a_workspace / "INPUT_MANIFEST.json"
    output_manifest_path = layer_a_workspace / "output/OUTPUT_MANIFEST.json"
    if sha256_file(results_path) != expected_results_sha256:
        raise ValueError("frozen Layer A results hash mismatch")
    if sha256_file(input_manifest_path) != expected_input_manifest_hash:
        raise ValueError("frozen Layer A input manifest hash mismatch")
    output_manifest = _read_json(output_manifest_path)
    if (
        output_manifest.get("status") != "PASS"
        or output_manifest.get("package_role") != "SCIENTIFIC_INVENTORY"
        or output_manifest.get("results_sha256") != expected_results_sha256
        or output_manifest.get("input_manifest_hash") != expected_input_manifest_hash
        or output_manifest.get("row_count") != EXPECTED_ROW_COUNT
        or output_manifest.get("claim_count") != EXPECTED_CLAIM_COUNT
    ):
        raise ValueError("Layer A output manifest does not bind the frozen scientific output")
    rows = _read_jsonl(results_path)
    claims = [claim for row in rows for claim in row.get("claims", [])]
    conflict_count = sum(claim.get("claim_type") == "source_conflict" for claim in claims)
    if len(rows) != EXPECTED_ROW_COUNT or len(claims) != EXPECTED_CLAIM_COUNT or conflict_count != EXPECTED_SOURCE_CONFLICT_COUNT:
        raise ValueError("frozen Layer A row, claim, or source-conflict count mismatch")
    source_units = {row["source_unit_id"]: row for row in _read_jsonl(layer_a_workspace / "input/source_units.jsonl")}
    source_bindings = _read_json(layer_a_workspace / "input/source_bindings.json")["artifacts"]
    if len({claim["claim_id"] for claim in claims}) != EXPECTED_CLAIM_COUNT:
        raise ValueError("frozen Layer A claim IDs are not unique")
    return rows, source_units, source_bindings


def prepare_v3_1_1_layer_b(
    *,
    repo_root: Path,
    workspace_parent: Path,
    run_id: str,
    layer_a_workspace: Path,
    expected_layer_a_results_sha256: str,
    expected_layer_a_input_manifest_hash: str,
    repo_head: str,
    branch: str,
    pr_number: int,
    pdf_slice_writer: Callable[[Path, Path, list[int]], None] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    workspace_parent = workspace_parent.resolve()
    layer_a_workspace = layer_a_workspace.resolve()
    if not LAYER_B_RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid V3.1.1 Layer B run ID")
    if _is_within(workspace_parent, repo_root):
        raise ValueError("Layer B workspace parent must be outside the Git repository")
    if _is_within(workspace_parent, layer_a_workspace):
        raise ValueError("Layer B workspace parent cannot be inside the frozen Layer A workspace")
    rows, source_units, source_bindings = _verify_upstream(
        layer_a_workspace,
        expected_results_sha256=expected_layer_a_results_sha256,
        expected_input_manifest_hash=expected_layer_a_input_manifest_hash,
    )
    run_root = workspace_parent / run_id
    existing = run_root / "coordinator/preparation_result.json"
    if run_root.exists():
        if not existing.is_file():
            raise FileExistsError("Layer B run exists without a preparation result")
        result = _read_json(existing)
        report = validate_layer_b_workspace(Path(result["layer_b_workspace"]), repo_root=repo_root)
        if report["status"] != "PASS":
            raise ValueError(f"existing Layer B workspace is invalid: {report['issues']}")
        return result
    workspace_parent.mkdir(parents=True, exist_ok=True)
    temporary = workspace_parent / f".{run_id}.tmp-{os.getpid()}"
    if temporary.exists():
        raise FileExistsError(f"temporary Layer B run already exists: {temporary}")
    coordinator = temporary / "coordinator"
    workspace = temporary / "layerB_exact_claim_verifier"
    for directory in (coordinator, workspace / "sources", workspace / "input", workspace / "schemas", workspace / "output"):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_template_root() / "AGENTS.override.md", workspace / "AGENTS.override.md")
    shutil.copy2(_template_root() / "WORK_ORDER.md", workspace / "WORK_ORDER.md")
    slice_writer = pdf_slice_writer or _write_pdf_slice
    tasks = []
    for row in rows:
        source_unit = source_units.get(row["source_unit_id"])
        if source_unit is None:
            raise ValueError(f"Layer A source unit is missing: {row['source_unit_id']}")
        for claim in row["claims"]:
            source_id = claim["source_document_id"]
            upstream_artifact = source_unit["source_artifacts"].get(source_id)
            if not upstream_artifact or upstream_artifact not in source_bindings:
                raise ValueError(f"Layer A source artifact binding is missing: {claim['claim_id']}")
            upstream_path = layer_a_workspace / upstream_artifact
            upstream_binding = source_bindings[upstream_artifact]
            upstream_hash = sha256_file(upstream_path)
            if upstream_binding.get("artifact_sha256") != upstream_hash:
                raise ValueError(f"frozen Layer A source artifact hash mismatch: {claim['claim_id']}")
            allowed_pages = _claim_allowed_pages(claim)
            upstream_pages = upstream_binding["original_page_indices"]
            if any(page not in upstream_pages for page in allowed_pages):
                raise ValueError(f"claim locator page is absent from its frozen Layer A artifact: {claim['claim_id']}")
            page_positions = [upstream_pages.index(page) for page in allowed_pages]
            task_id = _verifier_task_id(run_id, claim["claim_id"])
            artifact = f"sources/{task_id}__{source_id}.pdf"
            destination = workspace / artifact
            slice_writer(upstream_path, destination, page_positions)
            claim_hash = _canonical_hash(claim)
            binding = {
                "source_document_id": source_id,
                "source_role": claim["source_role"],
                "original_source_sha256": upstream_binding["original_source_sha256"],
                "upstream_artifact_sha256": upstream_hash,
                "packaged_artifact_sha256": sha256_file(destination),
                "original_page_indices": allowed_pages,
                "packaged_page_indices": list(range(len(allowed_pages))),
                "original_to_packaged_page_index": {str(page): index for index, page in enumerate(allowed_pages)},
                "printed_page_labels": {str(page): upstream_binding["printed_page_labels"][str(page)] for page in allowed_pages},
            }
            task_without_hash = {
                "verifier_task_id": task_id,
                "source_unit_id": row["source_unit_id"],
                "claim_id": claim["claim_id"],
                "claim_hash": claim_hash,
                "claim": claim,
                "source_document_id": source_id,
                "source_role": claim["source_role"],
                "source_artifact": artifact,
                "allowed_original_page_indices": allowed_pages,
                "source_binding": binding,
            }
            tasks.append({**task_without_hash, "task_hash": _canonical_hash(task_without_hash)})
    if len(tasks) != EXPECTED_CLAIM_COUNT:
        raise ValueError("Layer B task construction did not produce exactly 44 tasks")
    atomic_write_jsonl(workspace / "input/verifier_tasks.jsonl", tasks)
    for name in ("validation_core.py", "verify_input_package.py", "validate_results.py", "finalize_output.py"):
        shutil.copy2(_template_root() / name, workspace / "input" / name)
    for name in ("verifier_task.schema.json", "verifier_output.schema.json"):
        shutil.copy2(_schema_root() / name, workspace / "schemas" / name)
    manifest = {
        "schema_version": "3.1.1-layer-b",
        "package_role": "EXACT_CLAIM_VERIFICATION",
        "procedural_isolation_only": True,
        "not_os_security_sandbox": True,
        "not_statistically_independent": True,
        "upstream_layer_a_run_id": layer_a_workspace.parent.name,
        "upstream_layer_a_results_sha256": expected_layer_a_results_sha256,
        "upstream_layer_a_input_manifest_hash": expected_layer_a_input_manifest_hash,
        "upstream_row_count": EXPECTED_ROW_COUNT,
        "upstream_claim_count": EXPECTED_CLAIM_COUNT,
        "upstream_source_conflict_count": EXPECTED_SOURCE_CONFLICT_COUNT,
        "repo_head": repo_head,
        "branch": branch,
        "pr_number": pr_number,
        "expected_verifier_task_ids": [task["verifier_task_id"] for task in tasks],
        "claim_hashes": {task["claim_id"]: task["claim_hash"] for task in tasks},
        "verifier_task_hashes": {task["verifier_task_id"]: task["task_hash"] for task in tasks},
        "allowed_output_files": ["results.jsonl", "OUTPUT_MANIFEST.json", "OUTPUT_MANIFEST.sha256"],
        "files": _manifest_files(workspace),
    }
    atomic_write_json(workspace / "INPUT_MANIFEST.json", manifest)
    _write_checksum_file(workspace, manifest)
    _freeze_inputs(workspace)
    task_text = (workspace / "input/verifier_tasks.jsonl").read_text(encoding="utf-8").casefold()
    for forbidden in ("locator_scope", "private_calibration", "reviewer_note", "final_decision", "reviewer_1.jsonl", "human_review_required"):
        if forbidden in task_text:
            raise ValueError(f"forbidden context leaked into Layer B tasks: {forbidden}")
    report = validate_layer_b_workspace(workspace, repo_root=repo_root)
    if report["status"] != "PASS":
        raise ValueError(f"Layer B workspace validation failed: {report['issues']}")
    if sha256_file(layer_a_workspace / "output/results.jsonl") != expected_layer_a_results_sha256:
        raise RuntimeError("frozen Layer A results changed during Layer B preparation")
    final_workspace = run_root / "layerB_exact_claim_verifier"
    result = {
        "schema_version": "3.1.1-layer-b",
        "run_id": run_id,
        "run_root": str(run_root),
        "layer_b_workspace": str(final_workspace),
        "stage": "PREPARED_FOR_EXACT_CLAIM_LAYER_B_V3_1_1",
        "task_count": len(tasks),
        "source_conflict_task_count": sum(task["claim"]["claim_type"] == "source_conflict" for task in tasks),
        "layer_b_input_manifest_hash": report["manifest_hash"],
        "upstream_layer_a_results_sha256": expected_layer_a_results_sha256,
        "upstream_layer_a_input_manifest_hash": expected_layer_a_input_manifest_hash,
        "repo_head": repo_head,
        "branch": branch,
        "pr_number": pr_number,
        "layer_b_started": False,
        "layer_c_created": False,
        "phase8b_started": False,
    }
    atomic_write_json(coordinator / "run_manifest.json", result)
    atomic_write_json(coordinator / "preparation_result.json", result)
    atomic_write_text(
        coordinator / "COORDINATOR_RESUME.md",
        "\n".join(
            [
                "# Phase 8 V3.1.1 Layer B Coordinator Resume",
                "",
                f"- run ID: `{run_id}`",
                "- checkpoint: `PREPARED_FOR_EXACT_CLAIM_LAYER_B_V3_1_1`",
                f"- Layer B workspace: `{final_workspace}`",
                f"- task count: `{len(tasks)}`",
                f"- input manifest: `{report['manifest_hash']}`",
                f"- frozen Layer A results: `{expected_layer_a_results_sha256}`",
                "- Layer B: not started",
                "- Layer C: not created",
                "- Phase 8B: not started",
                "",
            ]
        ),
    )
    os.replace(temporary, run_root)
    return result
