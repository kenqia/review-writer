from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema


EXPECTED_TASK_COUNT = 44


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_checksums(path: Path) -> dict[str, str]:
    checksums = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, relative = line.split("  ", maxsplit=1)
            checksums[relative] = digest
    return checksums


def _without_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: child for key, child in value.items() if key != field}


def _locator_pages(locator: dict[str, Any]) -> set[int]:
    page = locator.get("pdf_page_index")
    if locator.get("scope") == "EXACT_PAGE":
        return {page} if isinstance(page, int) and locator.get("page_window") is None else set()
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
    return set()


def _claim_locators(claim: dict[str, Any]) -> list[dict[str, Any]]:
    locators = [claim.get("evidence_locator") or {}]
    conflict = claim.get("source_conflict") or {}
    locators.extend(row.get("locator") or {} for row in conflict.get("alternatives", []))
    return locators


def _task_semantic_issues(task: dict[str, Any], root: Path) -> list[str]:
    issues = []
    claim = task["claim"]
    if task["claim_id"] != claim.get("claim_id"):
        issues.append("task claim_id differs from its single claim")
    if canonical_hash(claim) != task["claim_hash"]:
        issues.append("claim hash is invalid")
    if canonical_hash(_without_hash(task, "task_hash")) != task["task_hash"]:
        issues.append("task hash is invalid")
    if task["source_document_id"] != claim.get("source_document_id") or task["source_role"] != claim.get("source_role"):
        issues.append("task source identity differs from its claim")
    conflict = claim.get("source_conflict")
    if claim.get("claim_type") == "source_conflict":
        if not claim.get("source_conflict_detected") or not isinstance(conflict, dict) or len(conflict.get("alternatives", [])) < 2:
            issues.append("source-conflict claim lacks structured alternatives")
    elif claim.get("source_conflict_detected") != (conflict is not None):
        issues.append("claim source-conflict flag and object disagree")
    locator_pages = set()
    for locator in _claim_locators(claim):
        pages = _locator_pages(locator)
        if not pages:
            issues.append("claim contains an invalid structured evidence locator")
        locator_pages.update(pages)
    allowed = set(task["allowed_original_page_indices"])
    if locator_pages != allowed:
        issues.append("allowed pages differ from the structured claim locator pages")
    binding = task["source_binding"]
    if binding["source_document_id"] != task["source_document_id"] or binding["source_role"] != task["source_role"]:
        issues.append("source binding identity differs from task identity")
    if binding["original_page_indices"] != task["allowed_original_page_indices"]:
        issues.append("source binding pages differ from task allowed pages")
    expected_packaged = list(range(len(task["allowed_original_page_indices"])))
    if binding["packaged_page_indices"] != expected_packaged:
        issues.append("packaged page indices are not a zero-based contiguous mapping")
    expected_map = {str(page): index for index, page in enumerate(task["allowed_original_page_indices"])}
    if binding["original_to_packaged_page_index"] != expected_map:
        issues.append("original-to-packaged page map is invalid")
    if set(binding["printed_page_labels"]) != {str(page) for page in allowed}:
        issues.append("printed-page label map differs from allowed pages")
    for locator in _claim_locators(claim):
        page = locator.get("pdf_page_index")
        if isinstance(page, int) and binding["printed_page_labels"].get(str(page)) != locator.get("printed_page_label_observed"):
            issues.append("claim printed-page label differs from the source binding")
    artifact = root / task["source_artifact"]
    if not artifact.is_file() or sha256_file(artifact) != binding["packaged_artifact_sha256"]:
        issues.append("packaged source artifact hash mismatch")
    return issues


def verify_input_package(root: Path) -> list[str]:
    issues = []
    try:
        manifest = read_json(root / "INPUT_MANIFEST.json")
        checksums = parse_checksums(root / "INPUT_MANIFEST.sha256")
    except Exception as exc:
        return [f"input manifest parse failed: {exc}"]
    expected_checksum_paths = {"INPUT_MANIFEST.json", *(row["path"] for row in manifest.get("files", []))}
    if set(checksums) != expected_checksum_paths:
        issues.append("checksum coverage must equal the manifest plus every listed input")
    for relative, digest in checksums.items():
        path = root / relative
        if not path.is_file():
            issues.append(f"manifest-listed input missing: {relative}")
        elif sha256_file(path) != digest:
            issues.append(f"manifest-listed input changed: {relative}")
    actual = {"AGENTS.override.md", "WORK_ORDER.md"}
    for directory in ("sources", "input", "schemas"):
        actual.update(path.relative_to(root).as_posix() for path in (root / directory).rglob("*") if path.is_file())
    if actual != {row["path"] for row in manifest.get("files", [])}:
        issues.append("unexpected or missing file in the closed input package")
    try:
        tasks = read_jsonl(root / "input/verifier_tasks.jsonl")
        schema = read_json(root / "schemas/verifier_task.schema.json")
    except Exception as exc:
        return sorted(set([*issues, f"verifier task input parse failed: {exc}"]))
    if manifest.get("package_role") != "EXACT_CLAIM_VERIFICATION" or manifest.get("schema_version") != "3.1.1-layer-b":
        issues.append("manifest has the wrong Layer B role or schema version")
    if len(tasks) != EXPECTED_TASK_COUNT or manifest.get("upstream_claim_count") != EXPECTED_TASK_COUNT:
        issues.append("Layer B package must contain exactly 44 verifier tasks")
    if [task.get("verifier_task_id") for task in tasks] != manifest.get("expected_verifier_task_ids"):
        issues.append("verifier task IDs/order differ from the manifest")
    if len({task.get("claim_id") for task in tasks}) != len(tasks):
        issues.append("verifier tasks do not have unique claim IDs")
    for index, task in enumerate(tasks):
        try:
            jsonschema.Draft202012Validator(schema).validate(task)
        except jsonschema.ValidationError as exc:
            issues.append(f"verifier task {index} schema error: {exc.message}")
            continue
        claim_id = task["claim_id"]
        task_id = task["verifier_task_id"]
        if manifest.get("claim_hashes", {}).get(claim_id) != task["claim_hash"]:
            issues.append(f"manifest claim hash mismatch: {claim_id}")
        if manifest.get("verifier_task_hashes", {}).get(task_id) != task["task_hash"]:
            issues.append(f"manifest task hash mismatch: {task_id}")
        issues.extend(f"{task_id}: {issue}" for issue in _task_semantic_issues(task, root))
    return sorted(set(issues))


def _result_semantic_issues(task: dict[str, Any], row: dict[str, Any]) -> list[str]:
    issues = []
    conflict_claim = task["claim"]["claim_type"] == "source_conflict"
    verdict = row["verdict"]
    assessment = row["source_conflict_assessment"]
    if verdict == "EDIT_REQUIRED" and row["corrected_fields"] is None:
        issues.append("EDIT_REQUIRED requires corrected_fields")
    if verdict in {"SUPPORTED", "SOURCE_CONFLICT"} and row["corrected_fields"] is not None:
        issues.append("supported or faithful-conflict result cannot carry corrected_fields")
    if verdict == "SUPPORTED" and row["error_categories"]:
        issues.append("SUPPORTED result cannot carry error categories")
    if conflict_claim:
        if verdict == "SOURCE_CONFLICT" and assessment != "FAITHFULLY_RECORDED":
            issues.append("SOURCE_CONFLICT verdict requires a faithfully-recorded assessment")
        if verdict != "SOURCE_CONFLICT" and assessment == "NOT_APPLICABLE":
            issues.append("source-conflict claim requires an explicit conflict assessment")
    elif verdict == "SOURCE_CONFLICT" or assessment != "NOT_APPLICABLE":
        issues.append("non-conflict claim cannot use conflict verdict or assessment")
    if verdict == "SOURCE_CONFLICT" and "source_conflict" not in row["error_categories"]:
        issues.append("SOURCE_CONFLICT verdict must retain the source_conflict category")
    locator = row["observed_evidence_locator"]
    if locator is None:
        if verdict not in {"INSUFFICIENT_EVIDENCE", "LOCATOR_ERROR"}:
            issues.append("verdict requires an observed evidence locator")
    else:
        pages = _locator_pages(locator)
        allowed = set(task["allowed_original_page_indices"])
        if not pages or not pages.issubset(allowed):
            issues.append("observed evidence locator exceeds task-allowed pages")
        page = locator.get("pdf_page_index")
        expected_label = task["source_binding"]["printed_page_labels"].get(str(page))
        if expected_label != locator.get("printed_page_label_observed"):
            issues.append("observed printed-page label differs from task binding")
    return issues


def validate_results(root: Path, results_path: Path) -> tuple[list[str], dict[str, int]]:
    issues = verify_input_package(root)
    try:
        manifest = read_json(root / "INPUT_MANIFEST.json")
        tasks = read_jsonl(root / "input/verifier_tasks.jsonl")
        rows = read_jsonl(results_path)
        schema = read_json(root / "schemas/verifier_output.schema.json")
    except Exception as exc:
        return sorted(set([*issues, f"result input parse failed: {exc}"])), {"result_count": 0, "source_conflict_result_count": 0}
    task_by_id = {task["verifier_task_id"]: task for task in tasks}
    expected_ids = manifest.get("expected_verifier_task_ids", [])
    if [row.get("verifier_task_id") for row in rows] != expected_ids:
        issues.append("results must contain exactly one row per verifier task in manifest order")
    manifest_hash = sha256_file(root / "INPUT_MANIFEST.json")
    conflict_results = 0
    for index, row in enumerate(rows):
        try:
            jsonschema.Draft202012Validator(schema).validate(row)
        except jsonschema.ValidationError as exc:
            issues.append(f"result row {index} schema error: {exc.message}")
            continue
        task = task_by_id.get(row["verifier_task_id"])
        if task is None:
            issues.append(f"unknown verifier task: {row['verifier_task_id']}")
            continue
        if row["claim_id"] != task["claim_id"] or row["claim_hash"] != task["claim_hash"] or row["task_hash"] != task["task_hash"]:
            issues.append(f"result row does not bind its task and claim: {row['verifier_task_id']}")
        if row["input_manifest_hash"] != manifest_hash:
            issues.append(f"result row has the wrong input manifest hash: {row['verifier_task_id']}")
        issues.extend(f"{row['verifier_task_id']}: {issue}" for issue in _result_semantic_issues(task, row))
        conflict_results += row["verdict"] == "SOURCE_CONFLICT"
    if len(rows) != EXPECTED_TASK_COUNT:
        issues.append("Layer B finalization requires exactly 44 result rows")
    return sorted(set(issues)), {"result_count": len(rows), "source_conflict_result_count": conflict_results}
