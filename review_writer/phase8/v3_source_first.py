from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Any

from .ai_adjudication import (
    _copy_reflink,
    _is_within,
    atomic_write_json,
    atomic_write_jsonl,
    atomic_write_text,
    sha256_file,
)


V3_RUN_ID_RE = re.compile(r"^phase8_source_first_v3_\d{8}T\d{6}Z$")
V2_AUDIT_DISTRIBUTION = {
    "VALID_EXACT_UNAMBIGUOUS": 6,
    "VALID_BUT_UNDERSPECIFIED": 8,
    "VALID_FACT_WRONG_LOCATOR": 6,
    "INVALID_ENTITY_OR_LABEL": 5,
    "INVALID_FACT_TYPE_AT_TARGET": 14,
    "INVALID_LOCATOR_OR_NO_QUALIFYING_VISUAL": 2,
}
INVENTORY_CATEGORIES = [
    "target_reaction_numeric_outcome",
    "substrate_preparation_numeric_outcome",
    "optimization_result",
    "scope_result",
    "negative_scope",
    "explicit_limitation",
    "author_proposed_mechanism",
    "experimental_mechanistic_observation",
    "figure_table_scheme_evidence",
    "source_identity_provenance",
]
SOURCE_GROUPS = [
    ("F3I", ["F3I_MAIN"], {"F3I_MAIN": "MAIN"}),
    ("F47A", ["F47A_MAIN", "F47A_SI"], {"F47A_MAIN": "MAIN", "F47A_SI": "SI"}),
    ("P403", ["P403_MAIN", "P403_SI"], {"P403_MAIN": "MAIN", "P403_SI": "SI"}),
]
REQUIRED_SOURCE_IDS = {source for _, sources, _ in SOURCE_GROUPS for source in sources}


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


def build_adversarial_dataset(v2_run: Path) -> dict[str, Any]:
    v2_run = v2_run.resolve()
    mapping = _read_json(v2_run / "coordinator/private_task_mapping.json")
    task1 = {row["blind_task_id"]: row for row in _read_jsonl(v2_run / "layer1_extractor/input/tasks.jsonl")}
    task2 = {row["blind_task_id"]: row for row in _read_jsonl(v2_run / "layer2_verifier/input/tasks.jsonl")}
    result1 = {row["blind_task_id"]: row for row in _read_jsonl(v2_run / "layer1_extractor/output/results.jsonl")}
    result2 = {row["blind_task_id"]: row for row in _read_jsonl(v2_run / "layer2_verifier/output/results.jsonl")}
    expected = set(mapping)
    named_sets = {"layer1_tasks": set(task1), "layer2_tasks": set(task2), "layer1_results": set(result1), "layer2_results": set(result2)}
    mismatches = {name: sorted(values ^ expected) for name, values in named_sets.items() if values != expected}
    if len(expected) != 41 or mismatches:
        raise ValueError(f"V2 adversarial source coverage mismatch: expected={len(expected)} mismatches={mismatches}")
    items = []
    for blind_id in sorted(expected):
        row = {
            "blind_task_id": blind_id,
            "review_item_id": mapping[blind_id].get("review_item_id"),
            "semantic_audit_label": "NOT_PROVIDED",
            "layer1_task": task1[blind_id],
            "layer2_task": task2[blind_id],
            "layer1_result": result1[blind_id],
            "layer2_result": result2[blind_id],
            "layer1_task_hash": _canonical_hash(task1[blind_id]),
            "layer2_task_hash": _canonical_hash(task2[blind_id]),
            "layer1_result_hash": _canonical_hash(result1[blind_id]),
            "layer2_result_hash": _canonical_hash(result2[blind_id]),
        }
        items.append(row)
    return {
        "schema_version": "3.0",
        "dataset_role": "ADVERSARIAL_TASK_VALIDATION_SET",
        "item_count": len(items),
        "items": items,
        "aggregate_semantic_distribution": dict(V2_AUDIT_DISTRIBUTION),
        "per_item_semantic_labels_available": False,
        "metric_boundary": "TASK_REJECTION_SAFETY_ONLY",
        "allowed_metrics": ["safe_rejection", "error_category_accuracy", "wrong_value_binding_avoidance"],
        "validation_targets": ["invalid_entity", "invalid_fact_type", "wrong_locator", "wrong_reaction_stage", "unsupported_negative_claim", "ee_vs_er", "substrate_vs_product", "related_evidence_misbinding"],
        "forbidden_interpretation": "NOT_FOUND_RATE_IS_NOT_SCIENTIFIC_EXTRACTION_RECALL",
    }


def _calibration_event(human_events: list[dict[str, Any]]) -> dict[str, Any]:
    matches = []
    for event in human_events:
        classification = str(event.get("classification") or "")
        locator = event.get("source_locator") or {}
        if event.get("final_decision") == "edit" and "substrate_preparation_yield" in classification and locator.get("source_document_id") == "P403_SI":
            matches.append(event)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one substrate-preparation calibration event, found {len(matches)}")
    return matches[0]


def _source_unit_id(run_id: str, index: int) -> str:
    payload = f"{run_id}\0{index}".encode()
    return f"SU-{hashlib.sha256(payload).hexdigest()[:16]}"


def _with_task_hash(task: dict[str, Any]) -> dict[str, Any]:
    return {**task, "task_hash": _canonical_hash(task)}


def build_source_units(*, run_id: str, human_events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not V3_RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid V3 run ID")
    units = []
    scientific_ids = []
    for index, (paper_id, source_ids, source_roles) in enumerate(SOURCE_GROUPS):
        unit_id = _source_unit_id(run_id, index)
        scientific_ids.append(unit_id)
        units.append(
            _with_task_hash(
                {
                    "source_unit_id": unit_id,
                    "paper_id": paper_id,
                    "source_document_ids": source_ids,
                    "source_roles": source_roles,
                    "locator_scope": "FULL_SOURCE",
                    "pdf_page_index": None,
                    "page_window": None,
                    "section": None,
                    "inventory_categories": INVENTORY_CATEGORIES,
                    "review_scope": "Inventory only atomic, review-relevant evidence actually reported within the allowed locator scope.",
                }
            )
        )
    event = _calibration_event(human_events)
    locator = event["source_locator"]
    calibration_id = _source_unit_id(run_id, len(units))
    units.append(
        _with_task_hash(
            {
                "source_unit_id": calibration_id,
                "paper_id": "P403",
                "source_document_ids": ["P403_SI"],
                "source_roles": {"P403_SI": "SI"},
                "locator_scope": "EXACT_PAGE",
                "pdf_page_index": locator.get("pdf_page_index"),
                "page_window": None,
                "section": None,
                "inventory_categories": INVENTORY_CATEGORIES,
                "review_scope": "Inventory only atomic, review-relevant evidence actually reported within the allowed locator scope.",
            }
        )
    )
    classification = [part.strip() for part in str(event.get("classification") or "").split("/", maxsplit=1)]
    value_match = re.search(r"\b\d+(?:\.\d+)?\s*%", str(event.get("edited_value") or ""))
    private = {
        "schema_version": "3.0",
        "scientific_source_unit_ids": scientific_ids,
        "opaque_source_unit_id": calibration_id,
        "exclude_opaque_unit_from_scientific_queue": True,
        "gold": {
            "review_item_id": event.get("core_review_item_id") or event.get("review_item_id"),
            "source_document_id": locator.get("source_document_id"),
            "pdf_page_index": locator.get("pdf_page_index"),
            "printed_page_label_observed": locator.get("printed_page_label"),
            "compound_label": locator.get("compound_label"),
            "value": value_match.group(0).replace(" ", "") if value_match else event.get("edited_value"),
            "fact_type": classification[0],
            "reaction_stage": classification[1] if len(classification) == 2 else None,
            "target_catalytic_reaction_relevance": event.get("target_catalytic_reaction_relevance"),
            "consumes_additional_human_budget": False,
        },
    }
    return units, private


def _schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas/phase8_source_first_v3"


def _template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "templates/phase8_source_first_v3"


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
    os.chmod(workspace / "output", 0o755)


def _parse_checksum_file(path: Path) -> dict[str, str]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", maxsplit=1)
        rows[relative] = digest
    return rows


def verify_v3_input_package(workspace: Path) -> dict[str, Any]:
    issues = []
    try:
        manifest = _read_json(workspace / "INPUT_MANIFEST.json")
        checksums = _parse_checksum_file(workspace / "INPUT_MANIFEST.sha256")
    except Exception as exc:
        return {"status": "FAIL", "issues": [f"manifest parse failed: {exc}"]}
    expected_paths = {"INPUT_MANIFEST.json", *(row["path"] for row in manifest.get("files", []))}
    if set(checksums) != expected_paths:
        issues.append("checksum file does not cover exactly the manifest and every listed input")
    for relative, expected in checksums.items():
        path = workspace / relative
        if not path.is_file() or sha256_file(path) != expected:
            issues.append(f"input hash mismatch: {relative}")
    actual_inputs = {"AGENTS.override.md", "WORK_ORDER.md"}
    for directory in ("sources", "input", "schemas"):
        actual_inputs.update(path.relative_to(workspace).as_posix() for path in (workspace / directory).rglob("*") if path.is_file())
    manifest_inputs = {row["path"] for row in manifest.get("files", [])}
    if actual_inputs != manifest_inputs:
        issues.append("manifest-listed input files do not match actual input files")
    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": sorted(set(issues)),
        "manifest_hash": sha256_file(workspace / "INPUT_MANIFEST.json") if (workspace / "INPUT_MANIFEST.json").is_file() else None,
    }


def validate_v3_workspace(workspace: Path, *, repo_root: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    issues = []
    if _is_within(workspace, repo_root.resolve()):
        issues.append("workspace must be outside the Git repository")
    if (workspace / ".git").exists():
        issues.append("workspace contains .git")
    for path in workspace.rglob("*"):
        if path.is_symlink():
            issues.append(f"symlink is forbidden: {path.relative_to(workspace)}")
    package = verify_v3_input_package(workspace)
    issues.extend(package["issues"])
    for relative in ("AGENTS.override.md", "WORK_ORDER.md", "INPUT_MANIFEST.json", "INPUT_MANIFEST.sha256"):
        path = workspace / relative
        if not path.is_file() or path.stat().st_mode & stat.S_IWUSR:
            issues.append(f"required root input missing or writable: {relative}")
    output = workspace / "output"
    if not output.is_dir() or not output.stat().st_mode & stat.S_IWUSR:
        issues.append("output directory is not owner-writable")
    for directory in ("sources", "input", "schemas"):
        for path in (workspace / directory).rglob("*"):
            if path.is_file() and path.stat().st_mode & stat.S_IWUSR:
                issues.append(f"input file is writable: {path.relative_to(workspace)}")
    units_path = workspace / "input/source_units.jsonl"
    units = _read_jsonl(units_path) if units_path.is_file() else []
    if len(units) != 4 or len({row.get("source_unit_id") for row in units}) != len(units):
        issues.append("source-unit count or uniqueness is invalid")
    text_paths = [path for path in workspace.rglob("*") if path.is_file() and path.suffix.lower() != ".pdf"]
    forbidden = ("human_review_required", "reviewer_note", "final_decision", "gold answer", "layerb", "layerc", "substrate_preparation_yield")
    for path in text_paths:
        text = path.read_text(encoding="utf-8", errors="replace").casefold()
        for term in forbidden:
            if term in text:
                issues.append(f"forbidden context leaked in {path.relative_to(workspace)}: {term}")
        if str(repo_root.resolve()).casefold() in text or re.search(r"(?:^|[\s\"'])/(?:home|users|mnt)/", text):
            issues.append(f"absolute path leaked in {path.relative_to(workspace)}")
    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": sorted(set(issues)),
        "source_unit_count": len(units),
        "manifest_hash": package.get("manifest_hash"),
    }


def prepare_v3_workspace(
    *,
    repo_root: Path,
    workspace_parent: Path,
    run_id: str,
    sources: dict[str, Path],
    identity_audits: dict[str, dict[str, Any]],
    human_events: list[dict[str, Any]],
    adversarial_dataset: dict[str, Any],
    repo_head: str,
    branch: str,
    pr_number: int,
    random_seed: int,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    workspace_parent = workspace_parent.resolve()
    if _is_within(workspace_parent, repo_root):
        raise ValueError("workspace parent must be outside the Git repository")
    if not V3_RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid V3 run ID")
    if set(sources) != REQUIRED_SOURCE_IDS:
        raise ValueError("V3 requires exactly the five identity-audited source files")
    for source_id, source in sources.items():
        audit = identity_audits.get(source_id, {})
        if audit.get("status") not in {"IDENTITY_VALIDATED_STRONG", "IDENTITY_VALIDATED_PROBABLE"}:
            raise ValueError(f"source identity is not validated: {source_id}")
        if not source.is_file() or sha256_file(source) != audit.get("sha256"):
            raise ValueError(f"source hash mismatch: {source_id}")
    run_root = workspace_parent / run_id
    existing = run_root / "coordinator/preparation_result.json"
    if run_root.exists():
        if not existing.is_file():
            raise FileExistsError("V3 run exists without preparation result")
        result = _read_json(existing)
        report = validate_v3_workspace(Path(result["layerA_workspace"]), repo_root=repo_root)
        if report["status"] != "PASS":
            raise ValueError("existing V3 Layer A workspace is invalid")
        return result
    temporary = workspace_parent / f".{run_id}.tmp-{os.getpid()}"
    if temporary.exists():
        raise FileExistsError(f"temporary V3 run already exists: {temporary}")
    units, private = build_source_units(run_id=run_id, human_events=human_events)
    public_values = set(_scalar_values(units))
    for key in ("value", "compound_label", "fact_type"):
        if private["gold"].get(key) in public_values:
            raise ValueError(f"private calibration field leaked into public source units: {key}")
    coordinator = temporary / "coordinator"
    workspace = temporary / "layerA_inventory"
    coordinator.mkdir(parents=True)
    for directory in ("sources", "input", "schemas", "output"):
        (workspace / directory).mkdir(parents=True, exist_ok=True)
    atomic_write_json(coordinator / "private_calibration.json", private)
    atomic_write_json(coordinator / "adversarial_task_validation_set.json", adversarial_dataset)
    atomic_write_json(
        coordinator / "adversarial_task_validation_manifest.json",
        {"schema_version": "3.0", "item_count": adversarial_dataset["item_count"], "dataset_sha256": _canonical_hash(adversarial_dataset)},
    )
    shutil.copy2(_template_root() / "AGENTS.override.md", workspace / "AGENTS.override.md")
    shutil.copy2(_template_root() / "WORK_ORDER.md", workspace / "WORK_ORDER.md")
    atomic_write_jsonl(workspace / "input/source_units.jsonl", units)
    for name in ("validation_core.py", "verify_input_package.py", "validate_results.py", "finalize_output.py"):
        shutil.copy2(_template_root() / name, workspace / "input" / name)
    for name in ("source_unit.schema.json", "layerA_inventory_output.schema.json"):
        shutil.copy2(_schema_root() / name, workspace / "schemas" / name)
    for source_id, source in sorted(sources.items()):
        _copy_reflink(source, workspace / "sources" / f"{source_id}.pdf")
    manifest = {
        "schema_version": "3.0",
        "package_role": "SOURCE_FIRST_LAYER_A",
        "run_id": run_id,
        "procedural_isolation_only": True,
        "expected_source_unit_ids": [row["source_unit_id"] for row in units],
        "source_unit_task_hashes": {row["source_unit_id"]: row["task_hash"] for row in units},
        "allowed_output_files": ["results.jsonl", "OUTPUT_MANIFEST.json", "OUTPUT_MANIFEST.sha256"],
        "files": _manifest_files(workspace),
    }
    atomic_write_json(workspace / "INPUT_MANIFEST.json", manifest)
    _write_checksum_file(workspace, manifest)
    _freeze_inputs(workspace)
    report = validate_v3_workspace(workspace, repo_root=repo_root)
    if report["status"] != "PASS":
        raise ValueError(f"V3 Layer A workspace validation failed: {report['issues']}")
    final_workspace = run_root / "layerA_inventory"
    result = {
        "schema_version": "3.0",
        "run_id": run_id,
        "run_root": str(run_root),
        "layerA_workspace": str(final_workspace),
        "stage": "PREPARED_FOR_SOURCE_FIRST_LAYER_A_V3",
        "scientific_source_unit_count": 3,
        "opaque_calibration_unit_count": 1,
        "input_manifest_hash": report["manifest_hash"],
        "repo_head": repo_head,
        "branch": branch,
        "pr_number": pr_number,
        "random_seed": random_seed,
        "human_budget": {"used": 6, "maximum": 10, "remaining": 4},
        "layerA_started": False,
        "layerB_created": False,
        "layerC_created": False,
        "phase8b_started": False,
    }
    atomic_write_json(coordinator / "run_manifest.json", result)
    atomic_write_json(coordinator / "preparation_result.json", result)
    atomic_write_text(
        coordinator / "COORDINATOR_RESUME.md",
        "\n".join(
            [
                "# Phase 8 V3 Coordinator Resume",
                "",
                f"- run ID: `{run_id}`",
                "- checkpoint: `PREPARED_FOR_SOURCE_FIRST_LAYER_A_V3`",
                "- scientific source units: `3`",
                "- opaque same-contract calibration units: `1`",
                f"- Layer A workspace: `{final_workspace}`",
                "- Layer A: not started",
                "- Layer B: not created",
                "- Layer C: not created",
                "- Phase 8B: not started",
                "",
            ]
        ),
    )
    os.replace(temporary, run_root)
    return result


def write_v2_diagnostic_markers(v2_run: Path, *, artifact_validation: dict[str, Any] | None = None) -> None:
    report = {
        "schema_version": "3.0",
        "status": "V2_DIAGNOSTIC_COMPLETE",
        "scientific_adjudication_status": "SCIENTIFIC_ADJUDICATION_NOT_APPLICABLE",
        "item_count": 41,
        "aggregate_semantic_distribution": dict(V2_AUDIT_DISTRIBUTION),
        "allowed_uses": ["adversarial_task_validation_set", "regression_corpus", "task_builder_debugging"],
        "forbidden_destinations": ["final_ai_decisions.jsonl", "human_review_log", "phase8b_evidence_pack"],
        "original_ab_outputs_modified": False,
        "artifact_validation": artifact_validation,
        "diagnostic_reasons": [
            "EXACT_LOCATOR_DID_NOT_VERIFY_ENTITY_FACT_STAGE_VALUE_BINDING",
            "FIXED_FIELD_MATRIX_CREATED_NONEXISTENT_TASKS",
            "OPEN_TASKS_ALLOWED_MULTIPLE_DIFFERENT_CORRECT_ANSWERS",
            "LAYER_SEARCH_POLICIES_DIVERGED",
            "SUBSTRATE_PRODUCT_AND_REACTION_STAGE_BINDING_ERRORS",
            "IDENTITY_ITEMS_WERE_NOT_SCIENTIFIC_CLAIMS",
            "CALIBRATION_WAS_NOT_EXECUTED",
            "FINALIZER_DID_NOT_ENFORCE_FULL_INTEGRITY",
            "PRINTED_PAGE_LABEL_ERRORS",
        ],
    }
    atomic_write_json(v2_run / "coordinator/V2_DIAGNOSTIC_REPORT.json", report)
    lines = [
        "# V2 Diagnostic Report",
        "",
        "- status: `V2_DIAGNOSTIC_COMPLETE`",
        "- scientific adjudication: `SCIENTIFIC_ADJUDICATION_NOT_APPLICABLE`",
        "- item count: `41`",
        "- allowed use: adversarial task validation, regression, task-builder debugging",
        "- forbidden: final AI decisions, human review log, Phase 8B evidence pack",
        "- original Layer 1/2 inputs and outputs remain unchanged",
        "",
    ]
    atomic_write_text(v2_run / "coordinator/V2_DIAGNOSTIC_REPORT.md", "\n".join(lines))
    atomic_write_text(
        v2_run / "DO_NOT_CREATE_V2_LAYER3",
        "status=V2_DIAGNOSTIC_COMPLETE\nscientific_adjudication=SCIENTIFIC_ADJUDICATION_NOT_APPLICABLE\n",
    )
