from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from .ai_adjudication import (
    _is_within,
    atomic_write_json,
    atomic_write_jsonl,
    atomic_write_text,
    sha256_file,
)


V3_1_RUN_ID_RE = re.compile(r"^phase8_source_first_v3_1(?:_1)?_\d{8}T\d{6}Z$")
REQUIRED_SOURCE_IDS = {"F3I_MAIN", "F47A_MAIN", "F47A_SI", "P403_MAIN", "P403_SI"}
EXPECTED_PAGE_COUNTS = {
    "F3I_MAIN": 39,
    "F47A_MAIN": 2,
    "F47A_SI": 3,
    "P403_MAIN": 10,
    "P403_SI": 190,
}
SOURCE_IDENTITIES = {
    "F3I_MAIN": ("F3I", "MAIN"),
    "F47A_MAIN": ("F47A", "MAIN"),
    "F47A_SI": ("F47A", "SI"),
    "P403_MAIN": ("P403", "MAIN"),
    "P403_SI": ("P403", "SI"),
}


def _contract_version(run_id: str) -> str:
    return "3.1.1" if run_id.startswith("phase8_source_first_v3_1_1_") else "3.1"


def _checkpoint(run_id: str) -> str:
    suffix = "V3_1_1" if _contract_version(run_id) == "3.1.1" else "V3_1"
    return f"PREPARED_FOR_SOURCE_FIRST_LAYER_A_{suffix}"


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _scalar_values(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from _scalar_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _scalar_values(child)
    else:
        yield value


def _private_value_leaks(path: Path, private_values: set[str]) -> list[str]:
    if path.suffix.lower() == ".json":
        values = {str(value).casefold() for value in _scalar_values(_read_json(path))}
        return sorted(private_values & values)
    if path.suffix.lower() == ".jsonl":
        values = {str(value).casefold() for row in _read_jsonl(path) for value in _scalar_values(row)}
        return sorted(private_values & values)
    text = path.read_text(encoding="utf-8", errors="replace").casefold()
    return sorted(
        value
        for value in private_values
        if re.search(rf"(?<![a-z0-9_]){re.escape(value)}(?![a-z0-9_])", text)
    )


def _source_unit_id(run_id: str, role: str, index: int) -> str:
    digest = hashlib.sha256(f"{run_id}\0{role}\0{index}".encode()).hexdigest()[:16]
    return f"SU-{digest}"


def _with_task_hash(task: dict[str, Any]) -> dict[str, Any]:
    return {**task, "task_hash": _canonical_hash(task)}


def _extract_printed_label(page: Any) -> str:
    height = float(page.rect.height)
    bottom_lines: list[str] = []
    for block in page.get_text("blocks"):
        if float(block[1]) < height * 0.84:
            continue
        bottom_lines.extend(line.strip() for line in str(block[4]).splitlines() if line.strip())
    for line in bottom_lines:
        match = re.fullmatch(r"S\s*(\d+)", line, flags=re.IGNORECASE)
        if match:
            return f"S{match.group(1)}"
    for line in bottom_lines:
        if re.fullmatch(r"\d{1,5}", line):
            return line
    candidates: list[str] = []
    for line in bottom_lines:
        candidates.extend(re.findall(r"(?<![./\d])(\d{3,5})(?![./\d])", line))
    filtered = [value for value in candidates if not 1900 <= int(value) <= 2100]
    if filtered:
        return filtered[-1]
    return "NO_PRINTED_PAGE_LABEL_OBSERVED"


def inspect_source_metadata(sources: dict[str, Path]) -> dict[str, dict[str, Any]]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - exercised by the Phase 8 environment gate
        raise RuntimeError("PyMuPDF is required to prepare V3.1 source packages") from exc
    if set(sources) != REQUIRED_SOURCE_IDS:
        raise ValueError("V3.1 requires exactly the five identity-audited source PDFs")
    metadata: dict[str, dict[str, Any]] = {}
    for source_id, path in sorted(sources.items()):
        if not path.is_file():
            raise FileNotFoundError(path)
        paper_id, role = SOURCE_IDENTITIES[source_id]
        with fitz.open(path) as document:
            labels = {str(index): _extract_printed_label(document[index]) for index in range(len(document))}
            metadata[source_id] = {
                "source_document_id": source_id,
                "paper_id": paper_id,
                "source_role": role,
                "page_count": len(document),
                "sha256": sha256_file(path),
                "printed_page_labels": labels,
            }
    wrong_counts = {
        source_id: metadata[source_id]["page_count"]
        for source_id, expected in EXPECTED_PAGE_COUNTS.items()
        if metadata[source_id]["page_count"] != expected
    }
    if wrong_counts:
        raise ValueError(f"unexpected source PDF page counts: {wrong_counts}")
    return metadata


def _ranges(*groups: tuple[str, list[int]]) -> list[dict[str, Any]]:
    return [{"source_document_id": source_id, "page_indices": pages} for source_id, pages in groups]


def _unit(
    *,
    run_id: str,
    index: int,
    unit_kind: str,
    paper_id: str,
    ranges: list[dict[str, Any]],
    source_metadata: dict[str, dict[str, Any]],
    search_scope: str,
    review_question: str,
    included: list[str],
    excluded: list[str],
    completion_basis: str,
    completed_maximum_claim_count: int | None = None,
) -> dict[str, Any]:
    unit_id = _source_unit_id(run_id, unit_kind, index)
    source_ids = list(dict.fromkeys(group["source_document_id"] for group in ranges))
    source_roles = {source_id: source_metadata[source_id]["source_role"] for source_id in source_ids}
    source_artifacts = {source_id: f"sources/{unit_id}__{source_id}.pdf" for source_id in source_ids}
    page_labels = {
        source_id: {
            str(page): source_metadata[source_id]["printed_page_labels"][str(page)]
            for group in ranges
            if group["source_document_id"] == source_id
            for page in group["page_indices"]
        }
        for source_id in source_ids
    }
    required_ranges = []
    for group in ranges:
        pages = group["page_indices"]
        required_ranges.append(
            {
                "source_document_id": group["source_document_id"],
                "start_page_index": min(pages),
                "end_page_index": max(pages),
                "page_indices": pages,
            }
        )
    return _with_task_hash(
        {
            "source_unit_id": unit_id,
            "unit_kind": unit_kind,
            "paper_id": paper_id,
            "source_document_ids": source_ids,
            "source_roles": source_roles,
            "source_artifacts": source_artifacts,
            "source_page_counts": {source_id: source_metadata[source_id]["page_count"] for source_id in source_ids},
            "printed_page_labels": page_labels,
            "search_scope": search_scope,
            "review_question": review_question,
            "included_claim_classes": included,
            "excluded_material": excluded,
            "required_sections_or_page_ranges": required_ranges,
            "completion_criteria": {
                "required_page_indices": ranges,
                "completed_requires_all_required_pages": True,
                "completed_minimum_claim_count": 1,
                "completed_maximum_claim_count": completed_maximum_claim_count,
                "zero_claim_statuses": ["NO_QUALIFYING_EVIDENCE", "SOURCE_UNREADABLE", "OUT_OF_SCOPE"],
                "out_of_scope_allowed": False,
                "completion_basis": completion_basis,
            },
        }
    )


def build_v3_1_source_units(
    *,
    run_id: str,
    source_metadata: dict[str, dict[str, Any]],
    calibration_page_index: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not V3_1_RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid V3.1 run ID")
    common_exclusions = [
        "Bibliographic references without scientific body evidence.",
        "Long-form rationale, confidence scores, and unsupported AI inference.",
        "Routine spectra unless explicitly included by the unit page boundary.",
    ]
    specifications = [
        (
            "F3I",
            _ranges(("F3I_MAIN", list(range(0, 9)))),
            "PAGE_WINDOW",
            "Identify atomic review-source evidence about allene synthesis concepts and representative catalytic asymmetric strategies in the opening part of the review.",
            ["scope_result", "explicit_limitation", "author_proposed_mechanism"],
            common_exclusions + ["Exhaustive extraction of every scheme value.", "Reference list pages 33-38."],
            "Inspect every included page and record only review-relevant atomic summaries with REVIEW_ARTICLE_SUMMARY epistemic class.",
        ),
        (
            "F3I",
            _ranges(("F3I_MAIN", list(range(9, 17)))),
            "PAGE_WINDOW",
            "Identify atomic review-source evidence about catalytic asymmetric allene-forming methods and their stated scope or limitations in this middle review segment.",
            ["scope_result", "explicit_limitation", "author_proposed_mechanism"],
            common_exclusions + ["Exhaustive extraction of every scheme value.", "Reference list pages 33-38."],
            "Inspect every included page and distinguish review summaries from direct primary-source observations.",
        ),
        (
            "F3I",
            _ranges(("F3I_MAIN", list(range(17, 33)))),
            "PAGE_WINDOW",
            "Identify atomic review-source evidence about later catalytic asymmetric allene synthesis examples, method boundaries, and author-level synthesis conclusions.",
            ["scope_result", "explicit_limitation", "author_proposed_mechanism"],
            common_exclusions + ["Exhaustive extraction of every scheme value.", "Reference list pages 33-38."],
            "Inspect every included non-reference page and preserve the review article's epistemic role.",
        ),
        (
            "F47A",
            _ranges(("F47A_MAIN", [0, 1]), ("F47A_SI", [0, 1, 2])),
            "FULL_SOURCE",
            "Identify atomic evidence for the Pd/DBA asymmetric allene method, separating catalytic outcomes, stoichiometric reactivity, isolated intermediates, and control experiments.",
            ["target_reaction_numeric_outcome", "stoichiometric_result", "intermediate_isolation_result", "control_experiment_result", "experimental_mechanistic_observation"],
            common_exclusions,
            "Inspect both complete documents and assign a controlled reaction stage to every retained fact.",
        ),
        (
            "P403",
            _ranges(("P403_MAIN", list(range(0, 10)))),
            "FULL_SOURCE",
            "Identify atomic evidence for the reported Pd-catalyzed asymmetric allenylation, including method-defining outcomes, scope, limitations, controls, and epistemically classified mechanism statements.",
            ["target_reaction_numeric_outcome", "optimization_result", "scope_result", "negative_scope", "explicit_limitation", "author_proposed_mechanism", "experimental_mechanistic_observation", "downstream_transformation_result"],
            common_exclusions + ["References used as substitutes for evidence from the article body."],
            "Inspect all article pages while distinguishing reported results, author proposals, and experimental observations.",
        ),
        (
            "P403",
            _ranges(("P403_SI", list(range(0, 10)))),
            "PAGE_WINDOW",
            "Identify atomic evidence in SI methods, optimization, control, and mechanism material, preserving any internally conflicting labels or values as structured conflicts.",
            ["optimization_result", "control_experiment_result", "author_proposed_mechanism", "experimental_mechanistic_observation", "source_conflict"],
            common_exclusions + ["Substrate preparation pages 10-17.", "Product characterization pages 18-41.", "Routine spectra pages 42-189."],
            "Inspect pages 0-9, verify table/figure locators, and preserve both sides of any source-internal conflict.",
        ),
        (
            "P403",
            _ranges(("P403_SI", [10, *range(12, 18)])),
            "PAGE_WINDOW",
            "Identify atomic substrate-preparation evidence in the available SI preparation pages without treating preparation yields as target catalytic outcomes.",
            ["substrate_preparation_numeric_outcome", "explicit_limitation"],
            common_exclusions + ["The coordinator-reserved page is not present in this workspace.", "Target catalytic product scope.", "Routine spectra pages 42-189."],
            "Inspect every packaged preparation page and bind each retained yield to substrate_synthesis.",
        ),
        (
            "P403",
            _ranges(("P403_SI", list(range(18, 42)))),
            "PAGE_WINDOW",
            "Identify atomic product characterization and scope evidence that can support exact verification of reported target-reaction outcomes and stereochemical metrics.",
            ["target_reaction_numeric_outcome", "scope_result", "negative_scope", "explicit_limitation", "source_conflict"],
            common_exclusions + ["Routine spectra and chromatograms at pages 42-189 unless later requested for targeted verification."],
            "Inspect pages 18-41 and preserve reported metric types, units, product identities, and exact evidence locators.",
        ),
    ]
    scientific = [
        _unit(
            run_id=run_id,
            index=index,
            unit_kind="SCIENTIFIC",
            paper_id=paper_id,
            ranges=ranges,
            source_metadata=source_metadata,
            search_scope=scope,
            review_question=question,
            included=included,
            excluded=excluded,
            completion_basis=basis,
        )
        for index, (paper_id, ranges, scope, question, included, excluded, basis) in enumerate(specifications)
    ]
    calibration = [
        _unit(
            run_id=run_id,
            index=0,
            unit_kind="CALIBRATION",
            paper_id="P403",
            ranges=_ranges(("P403_SI", [calibration_page_index])),
            source_metadata=source_metadata,
            search_scope="EXACT_PAGE",
            review_question="Find exactly one atomic quantitative substrate-preparation fact: the first qualifying fact in source reading order on the provided exact page, preserving its reaction stage and entity binding.",
            included=["substrate_preparation_numeric_outcome", "explicit_limitation", "source_conflict"],
            excluded=common_exclusions + ["Facts located on any page other than the provided exact page."],
            completion_basis="One-item spot-check: inspect the complete page and emit exactly the first qualifying quantitative preparation fact in source reading order.",
            completed_maximum_claim_count=1,
        )
    ]
    return scientific, calibration


def _calibration_event(human_events: list[dict[str, Any]]) -> dict[str, Any]:
    matches = []
    for event in human_events:
        locator = event.get("source_locator") or {}
        classification = str(event.get("classification") or "")
        if event.get("final_decision") == "edit" and locator.get("source_document_id") == "P403_SI" and "substrate_preparation_yield" in classification:
            matches.append(event)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one private preparation-yield calibration event, found {len(matches)}")
    return matches[0]


_COMPOUND_LABEL_TOKEN = r"[a-z0-9]+(?:[-'][a-z0-9]+)*"


def _canonical_compound_label(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    if re.fullmatch(_COMPOUND_LABEL_TOKEN, text):
        return text
    terminal = re.search(rf"\(({_COMPOUND_LABEL_TOKEN})\)\s*$", text)
    return terminal.group(1) if terminal else None


def _canonical_percent_value(value: Any, unit: Any) -> tuple[Decimal, str] | None:
    if str(unit or "").strip() != "%" or value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return number, "%"


def _calibration_claim_matches(expected: dict[str, Any], claim: dict[str, Any]) -> bool:
    locator = claim.get("evidence_locator") or {}
    exact_fields = {
        "source_document_id": claim.get("source_document_id"),
        "pdf_page_index": locator.get("pdf_page_index"),
        "printed_page_label_observed": locator.get("printed_page_label_observed"),
        "claim_type": claim.get("claim_type"),
        "reaction_stage": claim.get("reaction_stage"),
        "metric_type": claim.get("metric_type"),
        "epistemic_class": claim.get("epistemic_class"),
    }
    if any(exact_fields[key] != expected.get(key) for key in exact_fields):
        return False
    expected_product = _canonical_compound_label(expected.get("product_id"))
    observed_product = _canonical_compound_label(claim.get("product_id"))
    if expected_product is None or observed_product != expected_product:
        return False
    expected_value = _canonical_percent_value(expected.get("value_as_reported"), expected.get("unit_as_reported"))
    observed_value = _canonical_percent_value(claim.get("value_as_reported"), claim.get("unit_as_reported"))
    return expected_value is not None and observed_value == expected_value


def _build_private_gold(event: dict[str, Any], source_metadata: dict[str, dict[str, Any]], *, schema_version: str) -> dict[str, Any]:
    locator = event["source_locator"]
    page_index = int(locator["pdf_page_index"])
    value_match = re.search(r"\b\d+(?:\.\d+)?\s*%", str(event.get("edited_value") or ""))
    if not value_match:
        raise ValueError("private calibration event has no percentage value")
    classification = [part.strip() for part in str(event["classification"]).split("/", maxsplit=1)]
    if len(classification) != 2:
        raise ValueError("private calibration classification must contain fact type and reaction stage")
    canonical_value = _canonical_percent_value(value_match.group(0), "%")
    if canonical_value is None:
        raise ValueError("private calibration percentage value cannot be canonicalized")
    decimal_value = canonical_value[0]
    stored_value: int | str = int(decimal_value) if decimal_value == decimal_value.to_integral_value() else format(decimal_value, "f")
    return {
        "schema_version": schema_version,
        "calibration_mode": "ONE_ITEM_SPOT_CHECK",
        "allowed_extra_quantitative_claims": [],
        "review_item_id": event.get("core_review_item_id") or event.get("review_item_id"),
        "expected": {
            "source_document_id": "P403_SI",
            "pdf_page_index": page_index,
            "printed_page_label_observed": source_metadata["P403_SI"]["printed_page_labels"][str(page_index)],
            "claim_type": "substrate_preparation_numeric_outcome",
            "reaction_stage": classification[1],
            "product_id": locator.get("compound_label"),
            "metric_type": "isolated_yield",
            "value_as_reported": stored_value,
            "unit_as_reported": "%",
            "epistemic_class": "DIRECT_REPORTED_RESULT",
        },
        "forbidden_reaction_stage": "target_catalytic_reaction",
        "consumes_additional_human_budget": False,
    }


def _schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas/phase8_source_first_v3_1"


def _template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "templates/phase8_source_first_v3_1"


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


def _write_pdf_slice(source: Path, destination: Path, original_page_indices: list[int]) -> None:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required to package source slices") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as original:
        sliced = fitz.open()
        try:
            for page_index in original_page_indices:
                sliced.insert_pdf(original, from_page=page_index, to_page=page_index)
            sliced.save(destination)
        finally:
            sliced.close()


def _parse_checksums(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, relative = line.split("  ", maxsplit=1)
            rows[relative] = digest
    return rows


def verify_v3_1_input_package(workspace: Path) -> dict[str, Any]:
    issues: list[str] = []
    try:
        manifest = _read_json(workspace / "INPUT_MANIFEST.json")
        checksums = _parse_checksums(workspace / "INPUT_MANIFEST.sha256")
    except Exception as exc:
        return {"status": "FAIL", "issues": [f"manifest parse failed: {exc}"], "manifest_hash": None}
    expected = {"INPUT_MANIFEST.json", *(row["path"] for row in manifest.get("files", []))}
    if set(checksums) != expected:
        issues.append("checksum file does not cover exactly the manifest and every listed input")
    for relative, digest in checksums.items():
        path = workspace / relative
        if not path.is_file() or sha256_file(path) != digest:
            issues.append(f"input hash mismatch: {relative}")
    actual = {"AGENTS.override.md", "WORK_ORDER.md"}
    for directory in ("sources", "input", "schemas"):
        actual.update(path.relative_to(workspace).as_posix() for path in (workspace / directory).rglob("*") if path.is_file())
    listed = {row["path"] for row in manifest.get("files", [])}
    if actual != listed:
        issues.append("manifest-listed files do not match the closed input set")
    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": sorted(set(issues)),
        "manifest_hash": sha256_file(workspace / "INPUT_MANIFEST.json") if (workspace / "INPUT_MANIFEST.json").is_file() else None,
    }


def validate_v3_1_workspace(workspace: Path, *, repo_root: Path, expected_package_role: str | None = None) -> dict[str, Any]:
    workspace = workspace.resolve()
    issues: list[str] = []
    if _is_within(workspace, repo_root.resolve()):
        issues.append("workspace must be outside the Git repository")
    if (workspace / ".git").exists():
        issues.append("workspace contains .git")
    for path in workspace.rglob("*"):
        if path.is_symlink():
            issues.append(f"symlink is forbidden: {path.relative_to(workspace)}")
    package = verify_v3_1_input_package(workspace)
    issues.extend(package["issues"])
    manifest = _read_json(workspace / "INPUT_MANIFEST.json") if (workspace / "INPUT_MANIFEST.json").is_file() else {}
    role = manifest.get("package_role")
    if expected_package_role and role != expected_package_role:
        issues.append(f"unexpected package role: {role}")
    for relative in ("AGENTS.override.md", "WORK_ORDER.md", "INPUT_MANIFEST.json", "INPUT_MANIFEST.sha256"):
        path = workspace / relative
        if not path.is_file() or path.stat().st_mode & stat.S_IWUSR:
            issues.append(f"required root input missing or writable: {relative}")
    for directory in ("sources", "input", "schemas"):
        for path in (workspace / directory).rglob("*"):
            if path.is_file() and path.stat().st_mode & stat.S_IWUSR:
                issues.append(f"input file is writable: {path.relative_to(workspace)}")
    if not (workspace / "output").is_dir() or not (workspace / "output").stat().st_mode & stat.S_IWUSR:
        issues.append("output directory is missing or not writable")
    tasks = _read_jsonl(workspace / "input/source_units.jsonl") if (workspace / "input/source_units.jsonl").is_file() else []
    expected_count = 8 if role == "SCIENTIFIC_INVENTORY" else 1 if role == "HIDDEN_CALIBRATION" else None
    if expected_count is None or len(tasks) != expected_count or len({task.get("source_unit_id") for task in tasks}) != len(tasks):
        issues.append("source-unit count or uniqueness is invalid")
    expected_kind = "SCIENTIFIC" if role == "SCIENTIFIC_INVENTORY" else "CALIBRATION"
    if any(task.get("unit_kind") != expected_kind for task in tasks):
        issues.append("workspace contains a source-unit kind outside its package role")
    if role == "SCIENTIFIC_INVENTORY":
        for task in tasks:
            for group in task.get("completion_criteria", {}).get("required_page_indices", []):
                if group.get("source_document_id") == "P403_SI" and 11 in group.get("page_indices", []):
                    issues.append("scientific workspace contains the coordinator-reserved P403 SI page")
    root_text_paths = [path for path in workspace.rglob("*") if path.is_file() and path.suffix.lower() != ".pdf"]
    forbidden = ("reviewer_note", "final_decision", "reviewer_1.jsonl", "private_calibration", "human_review_required")
    for path in root_text_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        folded = text.casefold()
        for term in forbidden:
            if term in folded:
                issues.append(f"private context leaked in {path.relative_to(workspace)}: {term}")
        if str(repo_root.resolve()).casefold() in folded or re.search(r"(?:^|[\s\"'])/(?:home|users|mnt)/", folded):
            issues.append(f"absolute path leaked in {path.relative_to(workspace)}")
    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": sorted(set(issues)),
        "source_unit_count": len(tasks),
        "manifest_hash": package.get("manifest_hash"),
    }


def _prepare_workspace(
    *,
    workspace: Path,
    package_role: str,
    tasks: list[dict[str, Any]],
    sources: dict[str, Path],
    source_metadata: dict[str, dict[str, Any]],
    pdf_slice_writer: Callable[[Path, Path, list[int]], None],
    schema_version: str,
) -> dict[str, Any]:
    for directory in ("sources", "input", "schemas", "output"):
        (workspace / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_template_root() / "AGENTS.override.md", workspace / "AGENTS.override.md")
    shutil.copy2(_template_root() / "WORK_ORDER.md", workspace / "WORK_ORDER.md")
    atomic_write_jsonl(workspace / "input/source_units.jsonl", tasks)
    bindings: dict[str, Any] = {}
    for task in tasks:
        for group in task["completion_criteria"]["required_page_indices"]:
            source_id = group["source_document_id"]
            artifact = task["source_artifacts"][source_id]
            destination = workspace / artifact
            pdf_slice_writer(sources[source_id], destination, group["page_indices"])
            bindings[artifact] = {
                "source_document_id": source_id,
                "source_role": source_metadata[source_id]["source_role"],
                "original_source_sha256": source_metadata[source_id]["sha256"],
                "original_page_count": source_metadata[source_id]["page_count"],
                "original_page_indices": group["page_indices"],
                "printed_page_labels": {str(page): source_metadata[source_id]["printed_page_labels"][str(page)] for page in group["page_indices"]},
                "artifact_sha256": sha256_file(destination),
            }
    atomic_write_json(workspace / "input/source_bindings.json", {"schema_version": schema_version, "artifacts": bindings})
    for name in ("validation_core.py", "verify_input_package.py", "validate_results.py", "finalize_output.py"):
        shutil.copy2(_template_root() / name, workspace / "input" / name)
    for name in ("source_unit.schema.json", "layerA_inventory_output.schema.json"):
        shutil.copy2(_schema_root() / name, workspace / "schemas" / name)
    manifest = {
        "schema_version": schema_version,
        "package_role": package_role,
        "procedural_isolation_only": True,
        "not_os_security_sandbox": True,
        "not_statistically_independent": True,
        "expected_source_unit_ids": [task["source_unit_id"] for task in tasks],
        "source_unit_task_hashes": {task["source_unit_id"]: task["task_hash"] for task in tasks},
        "allowed_output_files": ["results.jsonl", "OUTPUT_MANIFEST.json", "OUTPUT_MANIFEST.sha256"],
        "files": _manifest_files(workspace),
    }
    atomic_write_json(workspace / "INPUT_MANIFEST.json", manifest)
    _write_checksum_file(workspace, manifest)
    _freeze_inputs(workspace)
    return manifest


def prepare_v3_1_workspaces(
    *,
    repo_root: Path,
    workspace_parent: Path,
    run_id: str,
    sources: dict[str, Path],
    identity_audits: dict[str, dict[str, Any]],
    human_events: list[dict[str, Any]],
    repo_head: str,
    branch: str,
    pr_number: int,
    random_seed: int,
    instruction_sources: list[dict[str, Any]],
    source_metadata: dict[str, dict[str, Any]] | None = None,
    pdf_slice_writer: Callable[[Path, Path, list[int]], None] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    workspace_parent = workspace_parent.resolve()
    if _is_within(workspace_parent, repo_root):
        raise ValueError("workspace parent must be outside the Git repository")
    if not V3_1_RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid V3.1 run ID")
    metadata = source_metadata or inspect_source_metadata(sources)
    if set(metadata) != REQUIRED_SOURCE_IDS:
        raise ValueError("source metadata must cover exactly the five required source IDs")
    wrong_counts = {
        source_id: metadata[source_id].get("page_count")
        for source_id, expected in EXPECTED_PAGE_COUNTS.items()
        if metadata[source_id].get("page_count") != expected
    }
    if wrong_counts:
        raise ValueError(f"unexpected source metadata page counts: {wrong_counts}")
    slice_writer = pdf_slice_writer or _write_pdf_slice
    for source_id, source in sources.items():
        audit = identity_audits.get(source_id, {})
        if audit.get("status") not in {"IDENTITY_VALIDATED_STRONG", "IDENTITY_VALIDATED_PROBABLE"}:
            raise ValueError(f"source identity is not validated: {source_id}")
        if sha256_file(source) != audit.get("sha256") or metadata[source_id]["sha256"] != audit.get("sha256"):
            raise ValueError(f"source hash mismatch: {source_id}")
        expected_paper, expected_role = SOURCE_IDENTITIES[source_id]
        if metadata[source_id].get("paper_id") != expected_paper or metadata[source_id].get("source_role") != expected_role:
            raise ValueError(f"source metadata identity mismatch: {source_id}")
        if audit.get("source_role") and audit["source_role"] != metadata[source_id]["source_role"]:
            raise ValueError(f"source-role identity mismatch: {source_id}")
    run_root = workspace_parent / run_id
    existing = run_root / "coordinator/preparation_result.json"
    if run_root.exists():
        if not existing.is_file():
            raise FileExistsError("V3.1 run exists without a preparation result")
        result = _read_json(existing)
        for path_key, role in (("layerA_inventory_workspace", "SCIENTIFIC_INVENTORY"), ("calibration_layerA_workspace", "HIDDEN_CALIBRATION")):
            report = validate_v3_1_workspace(Path(result[path_key]), repo_root=repo_root, expected_package_role=role)
            if report["status"] != "PASS":
                raise ValueError(f"existing V3.1 workspace is invalid: {report['issues']}")
        return result
    schema_version = _contract_version(run_id)
    event = _calibration_event(human_events)
    private_gold = _build_private_gold(event, metadata, schema_version=schema_version)
    calibration_page = private_gold["expected"]["pdf_page_index"]
    scientific_tasks, calibration_tasks = build_v3_1_source_units(
        run_id=run_id,
        source_metadata=metadata,
        calibration_page_index=calibration_page,
    )
    temporary = workspace_parent / f".{run_id}.tmp-{os.getpid()}"
    if temporary.exists():
        raise FileExistsError(f"temporary V3.1 run already exists: {temporary}")
    coordinator = temporary / "coordinator"
    scientific = temporary / "layerA_inventory"
    calibration = temporary / "calibration_layerA"
    coordinator.mkdir(parents=True)
    try:
        _prepare_workspace(workspace=scientific, package_role="SCIENTIFIC_INVENTORY", tasks=scientific_tasks, sources=sources, source_metadata=metadata, pdf_slice_writer=slice_writer, schema_version=schema_version)
        _prepare_workspace(workspace=calibration, package_role="HIDDEN_CALIBRATION", tasks=calibration_tasks, sources=sources, source_metadata=metadata, pdf_slice_writer=slice_writer, schema_version=schema_version)
        private_values = {
            str(private_gold["expected"][key]).casefold()
            for key in ("product_id", "value_as_reported")
            if private_gold["expected"].get(key)
        }
        for path in [*scientific.rglob("*"), *calibration.rglob("*")]:
            if not path.is_file() or path.suffix.lower() == ".pdf":
                continue
            leaked = _private_value_leaks(path, private_values)
            if leaked:
                raise ValueError(f"private calibration value leaked into public package: {path.relative_to(temporary)}")
        atomic_write_json(coordinator / "private_calibration.json", private_gold)
        atomic_write_json(
            coordinator / "instruction_chain.json",
            {
                "schema_version": schema_version,
                "sources": instruction_sources,
                "procedural_isolation_only": True,
                "not_os_security_sandbox": True,
                "not_statistically_independent": True,
                "new_session_required_after_instruction_change": True,
            },
        )
        final_scientific = run_root / "layerA_inventory"
        final_calibration = run_root / "calibration_layerA"
        sci_report = validate_v3_1_workspace(scientific, repo_root=repo_root, expected_package_role="SCIENTIFIC_INVENTORY")
        cal_report = validate_v3_1_workspace(calibration, repo_root=repo_root, expected_package_role="HIDDEN_CALIBRATION")
        if sci_report["status"] != "PASS" or cal_report["status"] != "PASS":
            raise ValueError(f"V3.1 workspace validation failed: scientific={sci_report['issues']} calibration={cal_report['issues']}")
        result = {
            "schema_version": schema_version,
            "run_id": run_id,
            "run_root": str(run_root),
            "layerA_inventory_workspace": str(final_scientific),
            "calibration_layerA_workspace": str(final_calibration),
            "stage": _checkpoint(run_id),
            "scientific_source_unit_count": len(scientific_tasks),
            "calibration_source_unit_count": len(calibration_tasks),
            "scientific_input_manifest_hash": sci_report["manifest_hash"],
            "calibration_input_manifest_hash": cal_report["manifest_hash"],
            "private_calibration_hash": sha256_file(coordinator / "private_calibration.json"),
            "repo_head": repo_head,
            "branch": branch,
            "pr_number": pr_number,
            "random_seed": random_seed,
            "human_budget": {"used": 6, "maximum": 10, "remaining": 4},
            "layerA_started": False,
            "calibration_layerA_started": False,
            "layerB_created": False,
            "layerC_created": False,
            "phase8b_started": False,
        }
        atomic_write_json(coordinator / "run_manifest.json", result)
        atomic_write_json(coordinator / "preparation_result.json", result)
        atomic_write_json(
            coordinator / "V3_NO_GO_AUDIT.json",
            {
                "schema_version": schema_version,
                "old_run_id": "phase8_source_first_v3_20260713T103618Z",
                "verdict": "NO_GO",
                "bypasses_reproduced": [
                    "all_empty_finalizes",
                    "source_unreadable_with_claims",
                    "wrong_source_role",
                    "nonexistent_page_full_source",
                    "visual_claim_without_visual_locator",
                    "numeric_outcome_no_metric_value_binding",
                    "ee_with_wrong_unit_and_normalization",
                    "calibration_wrong_printed_label",
                ],
                "old_run_modified": False,
            },
        )
        atomic_write_text(
            coordinator / "COORDINATOR_RESUME.md",
            "\n".join(
                [
                    f"# Phase 8 V{schema_version} Coordinator Resume",
                    "",
                    f"- run ID: `{run_id}`",
                    f"- checkpoint: `{_checkpoint(run_id)}`",
                    "- scientific Layer A: not started",
                    "- calibration Layer A: not started",
                    "- Layer B/C: not created",
                    "- Phase 8B: not started",
                    f"- scientific workspace: `{final_scientific}`",
                    f"- calibration workspace: `{final_calibration}`",
                    f"- scientific manifest: `{sci_report['manifest_hash']}`",
                    f"- calibration manifest: `{cal_report['manifest_hash']}`",
                    "- launch each workspace in a separate new VS Code window and fresh Codex session only after a new independent audit approves it",
                    "",
                ]
            ),
        )
        os.replace(temporary, run_root)
        return result
    except Exception:
        raise


def evaluate_v3_1_calibration(run_root: Path) -> dict[str, Any]:
    run_root = run_root.resolve()
    workspace = run_root / "calibration_layerA"
    results_path = workspace / "output/results.jsonl"
    issues: list[str] = []
    private_path = run_root / "coordinator/private_calibration.json"
    output_manifest_path = workspace / "output/OUTPUT_MANIFEST.json"
    if not private_path.is_file():
        issues.append("private calibration policy is missing")
        private: dict[str, Any] = {"schema_version": "3.1", "expected": {}, "forbidden_reaction_stage": None}
    else:
        private = _read_json(private_path)
    if not results_path.is_file():
        issues.append("calibration results are missing")
    validation = subprocess.run(
        [sys.executable, str(workspace / "input/validate_results.py"), "--results", str(results_path)],
        capture_output=True,
        text=True,
        cwd=workspace,
    )
    if validation.returncode != 0:
        try:
            validation_report = json.loads(validation.stdout)
            issues.extend(f"shared validator: {issue}" for issue in validation_report.get("issues", []))
        except json.JSONDecodeError:
            issues.append("shared validator did not return a valid report")
    if not output_manifest_path.is_file():
        issues.append("calibration output manifest is missing")
        manifest: dict[str, Any] = {}
    else:
        manifest = _read_json(output_manifest_path)
    if results_path.is_file() and manifest.get("results_sha256") != sha256_file(results_path):
        issues.append("calibration output manifest does not bind the current results")
    if manifest.get("input_manifest_hash") != sha256_file(workspace / "INPUT_MANIFEST.json"):
        issues.append("calibration output manifest does not bind the current input")
    if manifest.get("package_role") != "HIDDEN_CALIBRATION" or manifest.get("status") != "PASS":
        issues.append("calibration output manifest has the wrong role or status")
    rows = _read_jsonl(results_path) if results_path.is_file() else []
    claims = [claim for row in rows for claim in row.get("claims", [])]
    expected = private["expected"]
    matches = []
    nonnumeric_types = {
        "explicit_limitation",
        "author_proposed_mechanism",
        "experimental_mechanistic_observation",
        "negative_scope",
        "source_conflict",
    }
    quantitative_claim_ids: list[str] = []
    for claim in claims:
        numeric_payload = claim.get("metric_type") != "not_applicable" or any(
            claim.get(key) is not None
            for key in ("value_as_reported", "unit_as_reported", "normalized_value_candidate", "normalized_metric_type", "normalization_rule")
        )
        if claim.get("reaction_stage") == private.get("forbidden_reaction_stage"):
            issues.append(f"forbidden calibration reaction stage: {claim.get('claim_id')}")
        if claim.get("claim_type") in nonnumeric_types and numeric_payload:
            issues.append(f"nonnumeric calibration claim carries quantitative payload: {claim.get('claim_id')}")
        if numeric_payload:
            quantitative_claim_ids.append(claim.get("claim_id"))
        if _calibration_claim_matches(expected, claim) and claim.get("reaction_stage") != private.get("forbidden_reaction_stage"):
            matches.append(claim.get("claim_id"))
    if len(matches) != 1:
        issues.append(f"expected exactly one private gold match, found {len(matches)}")
    allowed_extra_ids = set(private.get("allowed_extra_quantitative_claims", []))
    unexpected_quantitative = set(quantitative_claim_ids) - set(matches) - allowed_extra_ids
    if unexpected_quantitative:
        issues.append(f"unexplained extra quantitative calibration claims: {sorted(unexpected_quantitative)}")
    report = {
        "schema_version": private.get("schema_version", "3.1"),
        "calibration_mode": private.get("calibration_mode", "ONE_ITEM_SPOT_CHECK"),
        "status": "PASS" if not issues else "FAIL",
        "match_count": len(matches),
        "matched_claim_ids": matches,
        "issues": issues,
        "scientific_queue_eligible": not issues,
        "consumes_additional_human_budget": False,
    }
    atomic_write_json(run_root / "coordinator/private_calibration_evaluation.json", report)
    return report
