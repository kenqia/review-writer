from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import jsonschema


SOURCE_IDENTITIES = {
    "F3I_MAIN": ("F3I", "MAIN"),
    "F47A_MAIN": ("F47A", "MAIN"),
    "F47A_SI": ("F47A", "SI"),
    "P403_MAIN": ("P403", "MAIN"),
    "P403_SI": ("P403", "SI"),
}
REACTION_STAGE_BY_CLAIM = {
    "target_reaction_numeric_outcome": "target_catalytic_reaction",
    "substrate_preparation_numeric_outcome": "substrate_synthesis",
    "stoichiometric_result": "stoichiometric_intermediate_reactivity",
    "intermediate_isolation_result": "intermediate_isolation",
    "optimization_result": "optimization",
    "control_experiment_result": "control_experiment",
    "downstream_transformation_result": "downstream_transformation",
}
NUMERIC_CLAIM_TYPES = {
    "target_reaction_numeric_outcome",
    "substrate_preparation_numeric_outcome",
    "optimization_result",
    "scope_result",
    "stoichiometric_result",
    "intermediate_isolation_result",
    "control_experiment_result",
    "downstream_transformation_result",
}
NUMERIC_METRICS = {
    "isolated_yield", "assay_yield", "conversion", "ee", "er", "dr",
    "temperature", "time", "catalyst_loading", "ratio", "other_numeric",
}


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
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, relative = line.split("  ", maxsplit=1)
            checksums[relative] = digest
    return checksums


def _task_without_hash(task: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in task.items() if key != "task_hash"}


def _flatten_pages(groups: list[dict[str, Any]]) -> set[tuple[str, int]]:
    return {
        (group["source_document_id"], page)
        for group in groups
        for page in group.get("page_indices", [])
    }


def verify_input_package(root: Path) -> list[str]:
    issues: list[str] = []
    try:
        manifest = read_json(root / "INPUT_MANIFEST.json")
        checksums = parse_checksums(root / "INPUT_MANIFEST.sha256")
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
        issues.append("unexpected or missing file in the closed input package")
    try:
        tasks = read_jsonl(root / "input/source_units.jsonl")
        bindings = read_json(root / "input/source_bindings.json")["artifacts"]
        schema = read_json(root / "schemas/source_unit.schema.json")
    except Exception as exc:
        return sorted(set([*issues, f"source-unit input parse failed: {exc}"]))
    if [task.get("source_unit_id") for task in tasks] != manifest.get("expected_source_unit_ids"):
        issues.append("source-unit IDs/order differ from the input manifest")
    expected_kind = "SCIENTIFIC" if manifest.get("package_role") == "SCIENTIFIC_INVENTORY" else "CALIBRATION"
    expected_count = 8 if expected_kind == "SCIENTIFIC" else 1
    if len(tasks) != expected_count:
        issues.append(f"package role requires exactly {expected_count} source units")
    used_artifacts: set[str] = set()
    for index, task in enumerate(tasks):
        try:
            jsonschema.Draft202012Validator(schema).validate(task)
        except jsonschema.ValidationError as exc:
            issues.append(f"source unit {index} schema error: {exc.message}")
            continue
        if task["unit_kind"] != expected_kind:
            issues.append(f"source unit has wrong package kind: {task['source_unit_id']}")
        if canonical_hash(_task_without_hash(task)) != task["task_hash"]:
            issues.append(f"source-unit task hash is invalid: {task['source_unit_id']}")
        if manifest.get("source_unit_task_hashes", {}).get(task["source_unit_id"]) != task["task_hash"]:
            issues.append(f"source-unit task hash differs from manifest: {task['source_unit_id']}")
        source_ids = task["source_document_ids"]
        if set(task["source_roles"]) != set(source_ids) or set(task["source_artifacts"]) != set(source_ids) or set(task["source_page_counts"]) != set(source_ids) or set(task["printed_page_labels"]) != set(source_ids):
            issues.append(f"source-unit source maps do not share exact keys: {task['source_unit_id']}")
        required_pages = _flatten_pages(task["completion_criteria"]["required_page_indices"])
        declared_pages = _flatten_pages(task["required_sections_or_page_ranges"])
        if required_pages != declared_pages:
            issues.append(f"completion pages differ from declared review pages: {task['source_unit_id']}")
        for source_id in source_ids:
            expected_paper, expected_role = SOURCE_IDENTITIES.get(source_id, (None, None))
            if task["paper_id"] != expected_paper or task["source_roles"].get(source_id) != expected_role:
                issues.append(f"paper/source-role identity mismatch: {task['source_unit_id']}:{source_id}")
            page_count = task["source_page_counts"].get(source_id, 0)
            pages = sorted(page for document, page in required_pages if document == source_id)
            if not pages or any(page < 0 or page >= page_count for page in pages):
                issues.append(f"required page outside source bounds: {task['source_unit_id']}:{source_id}")
            labels = task["printed_page_labels"].get(source_id, {})
            if set(labels) != {str(page) for page in pages}:
                issues.append(f"printed-label coverage differs from required pages: {task['source_unit_id']}:{source_id}")
            artifact = task["source_artifacts"].get(source_id)
            used_artifacts.add(artifact)
            binding = bindings.get(artifact, {})
            if binding.get("source_document_id") != source_id or binding.get("source_role") != expected_role or binding.get("original_page_indices") != pages:
                issues.append(f"source artifact binding mismatch: {task['source_unit_id']}:{source_id}")
            artifact_path = root / artifact
            if not artifact_path.is_file() or binding.get("artifact_sha256") != sha256_file(artifact_path):
                issues.append(f"source artifact hash mismatch: {artifact}")
            if binding.get("printed_page_labels") != labels:
                issues.append(f"source artifact printed labels differ from task: {artifact}")
        if task["search_scope"] == "EXACT_PAGE" and len(required_pages) != 1:
            issues.append(f"EXACT_PAGE task must bind exactly one page: {task['source_unit_id']}")
        if task["search_scope"] == "FULL_SOURCE":
            for source_id in source_ids:
                pages = {page for document, page in required_pages if document == source_id}
                if pages != set(range(task["source_page_counts"][source_id])):
                    issues.append(f"FULL_SOURCE task does not contain every source page: {task['source_unit_id']}:{source_id}")
    if used_artifacts != set(bindings):
        issues.append("source binding set differs from source-unit artifact set")
    return sorted(set(issues))


def _locator_issues(task: dict[str, Any], source_id: str, locator: dict[str, Any], label: str) -> list[str]:
    issues: list[str] = []
    allowed = _flatten_pages(task["completion_criteria"]["required_page_indices"])
    page_index = locator.get("pdf_page_index")
    if (source_id, page_index) not in allowed:
        issues.append("evidence page is outside the task search scope or source bounds")
        return issues
    expected_label = task["printed_page_labels"][source_id][str(page_index)]
    if label != expected_label:
        issues.append("printed page label does not match the observed source-page label")
    if locator.get("scope") == "EXACT_PAGE":
        if locator.get("page_window") is not None:
            issues.append("EXACT_PAGE evidence locator cannot include a page window")
    elif locator.get("scope") == "PAGE_WINDOW":
        window = locator.get("page_window")
        if not isinstance(window, list) or len(window) != 2 or window[0] > window[1] or window[1] - window[0] > 2:
            issues.append("PAGE_WINDOW evidence locator must be an ordered tight window of at most three pages")
        elif any((source_id, page) not in allowed for page in range(window[0], window[1] + 1)) or not window[0] <= page_index <= window[1]:
            issues.append("evidence page window exceeds the task search scope")
    return issues


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def _claim_issues(task: dict[str, Any], claim: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    source_id = claim["source_document_id"]
    expected_paper, expected_role = SOURCE_IDENTITIES[source_id]
    if source_id not in task["source_document_ids"] or claim["paper_id"] != expected_paper or claim["paper_id"] != task["paper_id"]:
        issues.append("claim source or paper differs from its source unit")
    if claim["source_role"] != expected_role or task["source_roles"].get(source_id) != expected_role:
        issues.append("claim source role differs from source identity")
    if claim["claim_type"] not in task["included_claim_classes"]:
        issues.append("claim type is outside the source-unit inclusion contract")
    locator = claim["evidence_locator"]
    issues.extend(_locator_issues(task, source_id, locator, locator["printed_page_label_observed"]))
    for conflict in (claim.get("source_conflict") or {}).get("alternatives", []):
        issues.extend(f"conflict alternative: {issue}" for issue in _locator_issues(task, source_id, conflict["locator"], conflict["locator"]["printed_page_label_observed"]))
    visual = claim["evidence_modality"] in {"TABLE", "FIGURE", "SCHEME", "CAPTION"}
    if visual and not any(locator.get(key) for key in ("table_id", "figure_id", "scheme_id")):
        issues.append("visual evidence requires a table, figure, or scheme locator")
    if claim["evidence_modality"] == "TEXT" and claim["directness"] == "FIGURE_SUPPORTED":
        issues.append("plain-text evidence cannot claim figure-supported directness")
    claim_type = claim["claim_type"]
    if claim_type in NUMERIC_CLAIM_TYPES:
        required = ("product_id", "reaction_entry", "conditions_as_reported", "value_as_reported", "unit_as_reported")
        if claim["metric_type"] not in NUMERIC_METRICS or any(claim.get(key) in (None, "") for key in required):
            issues.append("numeric claim lacks product, entry, conditions, metric, value, or unit binding")
    if claim_type in REACTION_STAGE_BY_CLAIM and claim["reaction_stage"] != REACTION_STAGE_BY_CLAIM[claim_type]:
        issues.append("claim type is bound to the wrong reaction stage")
    metric = claim["metric_type"]
    unit = str(claim.get("unit_as_reported") or "").casefold().strip()
    percent_units = {"%", "percent", "% ee", "ee %"}
    ratio_units = {"ratio", "er", "dr", ":"}
    if metric in {"isolated_yield", "assay_yield", "conversion"} and unit not in {"%", "percent"}:
        issues.append("yield or conversion metric requires a percent unit")
    if metric == "ee" and unit not in percent_units:
        issues.append("ee requires a percent-compatible unit")
    if metric in {"er", "dr"} and unit not in ratio_units:
        issues.append("er or dr requires a ratio-compatible unit")
    normalized = claim["normalized_value_candidate"]
    if normalized is None:
        if claim["normalized_metric_type"] is not None or claim["normalization_rule"] is not None:
            issues.append("null normalized value cannot carry normalization metadata")
    else:
        if claim["normalized_metric_type"] != metric or not claim["normalization_rule"] or not claim["normalization_source_supported"]:
            issues.append("normalization must preserve the reported metric and record a source-supported rule")
        reported_number = _numeric_value(claim["value_as_reported"])
        normalized_number = _numeric_value(normalized)
        if metric in {"isolated_yield", "assay_yield", "conversion", "ee"} and (reported_number is None or normalized_number != reported_number):
            issues.append("normalized percent value differs from the reported value")
        if metric == "ee" and "er" in str(normalized).casefold():
            issues.append("ee cannot be silently normalized to er")
    if claim_type == "author_proposed_mechanism" and (claim["epistemic_class"] != "AUTHOR_PROPOSED_MECHANISM" or claim["pathway_status"] != "AUTHOR_PROPOSED"):
        issues.append("author-proposed mechanism has the wrong epistemic or pathway class")
    if claim_type == "experimental_mechanistic_observation" and (claim["epistemic_class"] != "EXPERIMENTAL_MECHANISTIC_OBSERVATION" or claim["pathway_status"] != "EXPERIMENTALLY_OBSERVED"):
        issues.append("experimental mechanism claim has the wrong epistemic or pathway class")
    if claim_type == "intermediate_isolation_result" and (claim["epistemic_class"] != "INTERMEDIATE_ISOLATION" or claim["pathway_status"] != "NOT_PROVEN_BY_ISOLATION"):
        issues.append("intermediate isolation cannot be presented as a proven catalytic pathway")
    if claim_type == "negative_scope" and claim["directness"] not in {"DIRECT_TEXTUAL", "TABLE_SUPPORTED"}:
        issues.append("negative claim lacks explicit textual or table support")
    if claim["paper_id"] == "F3I" and claim["epistemic_class"] != "REVIEW_ARTICLE_SUMMARY":
        issues.append("review-source claim must use REVIEW_ARTICLE_SUMMARY")
    if claim["source_conflict_detected"] != (claim["source_conflict"] is not None):
        issues.append("source-conflict flag and structured conflict object disagree")
    if claim_type == "source_conflict" and not claim["source_conflict_detected"]:
        issues.append("source-conflict claim must preserve structured alternatives")
    if claim["source_conflict"] is not None:
        alternatives = claim["source_conflict"]["alternatives"]
        if len({str(row["reported_value"]) for row in alternatives}) < 2:
            issues.append("source conflict must preserve at least two distinct alternatives")
    return issues


def validate_results(root: Path, results_path: Path) -> tuple[list[str], dict[str, int]]:
    issues = verify_input_package(root)
    try:
        manifest = read_json(root / "INPUT_MANIFEST.json")
        tasks = read_jsonl(root / "input/source_units.jsonl")
        rows = read_jsonl(results_path)
        schema = read_json(root / "schemas/layerA_inventory_output.schema.json")
    except Exception as exc:
        return sorted(set([*issues, f"result input parse failed: {exc}"])), {"row_count": 0, "claim_count": 0}
    task_by_id = {task["source_unit_id"]: task for task in tasks}
    expected_ids = manifest["expected_source_unit_ids"]
    if [row.get("source_unit_id") for row in rows] != expected_ids:
        issues.append("results must contain exactly one row per source unit in manifest order")
    manifest_hash = sha256_file(root / "INPUT_MANIFEST.json")
    claim_ids: list[str] = []
    for index, row in enumerate(rows):
        try:
            jsonschema.Draft202012Validator(schema).validate(row)
        except jsonschema.ValidationError as exc:
            issues.append(f"result row {index} schema error: {exc.message}")
            continue
        task = task_by_id.get(row["source_unit_id"])
        if task is None:
            issues.append(f"unknown source unit in results: {row['source_unit_id']}")
            continue
        if row["input_manifest_hash"] != manifest_hash or row["task_hash"] != task["task_hash"]:
            issues.append(f"result row has wrong input or task hash: {row['source_unit_id']}")
        status = row["source_unit_status"]
        required = _flatten_pages(task["completion_criteria"]["required_page_indices"])
        examined = _flatten_pages(row["pages_examined"])
        if not examined.issubset(required):
            issues.append(f"coverage exceeds source-unit bounds: {row['source_unit_id']}")
        if status == "COMPLETED":
            if examined != required:
                issues.append(f"COMPLETED row lacks full required page coverage: {row['source_unit_id']}")
            if len(row["claims"]) < task["completion_criteria"]["completed_minimum_claim_count"]:
                issues.append(f"COMPLETED row lacks required qualifying claims: {row['source_unit_id']}")
            if row["status_reason"] is not None:
                issues.append(f"COMPLETED row must not carry a failure reason: {row['source_unit_id']}")
        elif status == "PARTIAL":
            if not row["status_reason"] or not examined:
                issues.append(f"PARTIAL row requires a reason and honest page coverage: {row['source_unit_id']}")
        elif status in {"SOURCE_UNREADABLE", "OUT_OF_SCOPE", "NO_QUALIFYING_EVIDENCE"}:
            if not row["status_reason"] or row["claims"]:
                issues.append(f"{status} requires a reason and no claims: {row['source_unit_id']}")
        for claim in row["claims"]:
            claim_ids.append(claim["claim_id"])
            expected_prefix = f"CL-{row['source_unit_id']}-"
            if not claim["claim_id"].startswith(expected_prefix):
                issues.append(f"claim ID does not bind its source unit: {claim['claim_id']}")
            issues.extend(f"{claim['claim_id']}: {issue}" for issue in _claim_issues(task, claim))
    if len(claim_ids) != len(set(claim_ids)):
        issues.append("duplicate claim_id in results")
    if not claim_ids:
        role = manifest.get("package_role")
        issues.append(f"{role} cannot finalize with zero claims")
    return sorted(set(issues)), {"row_count": len(rows), "claim_count": len(claim_ids)}
