from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_checksums(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", maxsplit=1)
        result[relative] = digest
    return result


def verify_input_package(root: Path) -> list[str]:
    issues = []
    manifest_path = root / "INPUT_MANIFEST.json"
    checksum_path = root / "INPUT_MANIFEST.sha256"
    try:
        manifest = read_json(manifest_path)
        checksums = parse_checksums(checksum_path)
    except Exception as exc:
        return [f"input manifest parse failed: {exc}"]
    expected = {"INPUT_MANIFEST.json", *(row["path"] for row in manifest.get("files", []))}
    if set(checksums) != expected:
        issues.append("checksum coverage must equal the manifest plus every manifest-listed input")
    for relative, digest in checksums.items():
        path = root / relative
        if not path.is_file():
            issues.append(f"manifest-listed input missing: {relative}")
        elif sha256_file(path) != digest:
            issues.append(f"manifest-listed input changed: {relative}")
    actual = {"AGENTS.override.md", "WORK_ORDER.md"}
    for directory in ("sources", "input", "schemas"):
        actual.update(path.relative_to(root).as_posix() for path in (root / directory).rglob("*") if path.is_file())
    listed = {row["path"] for row in manifest.get("files", [])}
    if actual != listed:
        issues.append("unexpected or missing input file relative to INPUT_MANIFEST.json")
    try:
        source_units = read_jsonl(root / "input/source_units.jsonl")
        expected_ids = manifest["expected_source_unit_ids"]
        if [row.get("source_unit_id") for row in source_units] != expected_ids:
            issues.append("source-unit IDs/order differ from the manifest")
        task_hashes = manifest["source_unit_task_hashes"]
        for row in source_units:
            if task_hashes.get(row.get("source_unit_id")) != row.get("task_hash"):
                issues.append(f"source-unit task hash differs from manifest: {row.get('source_unit_id')}")
        schema = read_json(root / "schemas/source_unit.schema.json")
        for index, row in enumerate(source_units):
            try:
                jsonschema.Draft202012Validator(schema).validate(row)
            except jsonschema.ValidationError as exc:
                issues.append(f"source unit {index} schema error: {exc.message}")
    except Exception as exc:
        issues.append(f"source-unit validation failed: {exc}")
    return sorted(set(issues))


def _claim_locator_issues(task: dict[str, Any], claim: dict[str, Any]) -> list[str]:
    issues = []
    scope = task["locator_scope"]
    if claim.get("locator_scope") != scope:
        issues.append("claim locator_scope differs from its source unit")
    page = claim.get("pdf_page_index")
    if scope == "EXACT_PAGE" and page != task.get("pdf_page_index"):
        issues.append("EXACT_PAGE claim is outside the exact page")
    if scope == "PAGE_WINDOW":
        window = task.get("page_window") or []
        if len(window) != 2 or not isinstance(page, int) or not window[0] <= page <= window[1]:
            issues.append("PAGE_WINDOW claim is outside the page window")
    if scope == "SECTION" and claim.get("section") != task.get("section"):
        issues.append("SECTION claim is outside the named section")
    return issues


def validate_results(root: Path) -> tuple[list[str], dict[str, int]]:
    issues = []
    stats = {"row_count": 0, "claim_count": 0}
    manifest = read_json(root / "INPUT_MANIFEST.json")
    manifest_hash = sha256_file(root / "INPUT_MANIFEST.json")
    results_path = root / "output/results.jsonl"
    allowed = set(manifest["allowed_output_files"])
    actual_output = {path.relative_to(root / "output").as_posix() for path in (root / "output").rglob("*") if path.is_file()}
    if not actual_output <= allowed:
        issues.append(f"unexpected output files: {sorted(actual_output - allowed)}")
    if not results_path.is_file():
        return [*issues, "output/results.jsonl is missing"], stats
    try:
        rows = read_jsonl(results_path)
    except Exception as exc:
        return [*issues, f"results JSONL parse failed: {exc}"], stats
    stats["row_count"] = len(rows)
    expected = manifest["expected_source_unit_ids"]
    ids = [row.get("source_unit_id") for row in rows]
    if len(ids) != len(set(ids)):
        issues.append("duplicate source_unit_id in results")
    if set(ids) != set(expected) or len(ids) != len(expected):
        issues.append("results do not have exact expected source-unit coverage")
    tasks = {row["source_unit_id"]: row for row in read_jsonl(root / "input/source_units.jsonl")}
    schema = read_json(root / "schemas/layerA_inventory_output.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    claim_ids = []
    for index, row in enumerate(rows):
        try:
            validator.validate(row)
        except jsonschema.ValidationError as exc:
            issues.append(f"result row {index} schema error: {exc.message}")
            continue
        unit_id = row["source_unit_id"]
        task = tasks.get(unit_id)
        if task is None:
            continue
        if row["input_manifest_hash"] != manifest_hash:
            issues.append(f"wrong input_manifest_hash: {unit_id}")
        if row["task_hash"] != task["task_hash"]:
            issues.append(f"wrong task_hash: {unit_id}")
        allowed_sources = set(task["source_document_ids"])
        for claim in row["claims"]:
            claim_ids.append(claim["claim_id"])
            if not claim["claim_id"].startswith(f"CL-{unit_id}-"):
                issues.append(f"claim ID is not bound to source unit: {claim['claim_id']}")
            if claim["source_document_id"] not in allowed_sources:
                issues.append(f"claim source is outside its source unit: {claim['claim_id']}")
            if claim["paper_id"] != task["paper_id"]:
                issues.append(f"claim paper differs from its source unit: {claim['claim_id']}")
            issues.extend(f"{claim['claim_id']}: {issue}" for issue in _claim_locator_issues(task, claim))
            if claim["epistemic_class"] == "AI_INFERENCE":
                issues.append(f"AI_INFERENCE is not admissible evidence: {claim['claim_id']}")
            if claim["claim_type"] == "substrate_preparation_numeric_outcome" and claim["reaction_stage"] != "substrate_synthesis":
                issues.append(f"substrate preparation has wrong reaction stage: {claim['claim_id']}")
            if claim["claim_type"] == "target_reaction_numeric_outcome" and claim["reaction_stage"] != "target_catalytic_reaction":
                issues.append(f"target reaction outcome has wrong reaction stage: {claim['claim_id']}")
            if claim["claim_type"] == "negative_scope" and claim["directness"] not in {"DIRECT_TEXTUAL", "TABLE_SUPPORTED"}:
                issues.append(f"negative claim lacks explicit support: {claim['claim_id']}")
            if claim["paper_id"] == "F3I" and claim["claim_type"] != "source_identity_provenance" and claim["epistemic_class"] != "REVIEW_ARTICLE_SUMMARY":
                issues.append(f"review-source claim has wrong epistemic class: {claim['claim_id']}")
    if len(claim_ids) != len(set(claim_ids)):
        issues.append("duplicate claim_id in results")
    stats["claim_count"] = len(claim_ids)
    return sorted(set(issues)), stats
