"""Bounded Content Agent task packages and fail-closed result imports.

The Content Agent is a candidate generator.  It receives a hash-bound manifest
of the current project inputs and never gets an approval field.  Results are
validated and applied to a temporary project copy before any bytes in the
authoritative project are changed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from .paper_evidence import (
    PaperEvidenceError,
    require_dual_evidence_ready,
    register_paper_evidence_candidates,
    register_manual_pdf_evidence,
)
from .chemical_paper import STATE_NAME as CHEMICAL_PAPER_STATE_NAME
from .chemical_paper import STATE_ROOT as CHEMICAL_PAPER_STATE_ROOT
from .chemical_paper import ChemicalPaperError, load_chemical_paper_state
from .chemical_paper import chemical_paper_projection
from .parse_quality import ParseQualityError, parse_quality_state
from .parse_reconciliation import (
    ParseReconciliationError,
    load_parse_reconciliation,
)
from .paper_evidence_store import PaperEvidenceStoreError, project_write_lock
from .section_contract import SectionContractError, register_section_contracts
from .source_truth import (
    REPO_ROOT,
    SourceTruthError,
    canonical_digest,
    declared_study_ids,
    load_source_truth_bundle,
    source_truth_asset,
)
from .synthesis import SynthesisError, register_comparison_protocol, register_coverage_map, register_synthesis_candidates


REQUEST_SCHEMA = REPO_ROOT / "schemas/agents/content_agent_request.v1.schema.json"
RESULT_SCHEMA = REPO_ROOT / "schemas/agents/content_agent_result.v1.schema.json"
ALLOWED_INPUTS = frozenset({"source_truth", "parse_quality", "paper_evidence", "chemical_paper", "reconciliation", "comparison_protocol", "section_contract"})
REQUEST_KINDS = frozenset({"paper_evidence", "synthesis_claims", "section_draft"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^(?!\.\.?$)(?!.*[/\\\x00\r\n])\S{1,240}$")
_FORBIDDEN_TEXT = ("auth", "04_first_draft", "prompt")
_SUGGESTION_PATH = Path("01_evidence/content_agent_source_figure_suggestions.jsonl")


class ContentAgentError(ValueError):
    """Stable error code for task-package and result boundaries."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


def _schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContentAgentError("SCHEMA_INVALID") from exc
    if not isinstance(value, dict):
        raise ContentAgentError("SCHEMA_INVALID")
    return value


def _validate_schema(value: object, path: Path, code: str) -> None:
    errors = sorted(Draft202012Validator(_schema(path)).iter_errors(value), key=lambda e: list(e.path))
    if errors:
        raise ContentAgentError(code)


def _root(project: Path) -> Path:
    supplied = Path(project)
    if supplied.is_symlink() or not supplied.is_dir():
        raise ContentAgentError("PROJECT_INVALID")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise ContentAgentError("PROJECT_INVALID") from exc
    # A package must never follow a project-local symlink into another corpus.
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ContentAgentError("PROJECT_SYMLINK_UNSAFE")
    return root


def _read_json(path: Path, code: str) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContentAgentError(code) from exc
    return value


def _is_relative(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith("/") or value.startswith("\\"):
        return False
    if re.match(r"^[A-Za-z]:", value) or "\\" in value:
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ContentAgentError("IDENTIFIER_INVALID")
    return value


def _normalize_request(project: Path, request: object) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ContentAgentError("REQUEST_INVALID")
    value = copy.deepcopy(request)
    value.setdefault("schema_version", "content-agent-request.v1")
    value.setdefault("field_dependencies", [])
    _validate_schema(value, REQUEST_SCHEMA, "REQUEST_INVALID")
    if value["project_id"] != project.name:
        raise ContentAgentError("PROJECT_ID_MISMATCH")
    try:
        studies = set(declared_study_ids(project))
    except SourceTruthError as exc:
        raise ContentAgentError(exc.code) from exc
    targets = value["target_ids"]
    if value["request_kind"] == "paper_evidence" and not set(targets) <= studies:
        raise ContentAgentError("REQUEST_TARGET_OUT_OF_SCOPE")
    if value["request_kind"] == "synthesis_claims" and set(targets) != studies:
        raise ContentAgentError("REQUEST_TARGET_OUT_OF_SCOPE")
    return value


def _safe_project_relative(project: Path, relative: str) -> Path:
    if not _is_relative(relative):
        raise ContentAgentError("PACKAGE_PATH_INVALID")
    target = project / relative
    try:
        target.resolve(strict=True).relative_to(project.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ContentAgentError("PACKAGE_PATH_INVALID") from exc
    if target.is_symlink() or not target.is_file():
        raise ContentAgentError("PACKAGE_ASSET_INVALID")
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContentAgentError("PACKAGE_ASSET_INVALID") from exc
    return digest.hexdigest()


def _artifact(project: Path, source_path: str, kind: str, package_path: str | None = None) -> dict[str, Any]:
    path = _safe_project_relative(project, source_path)
    relative = package_path or f"inputs/{source_path}"
    if not _is_relative(relative):
        raise ContentAgentError("PACKAGE_PATH_INVALID")
    return {
        "path": relative,
        "source_path": source_path,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "kind": kind,
    }


def _add_artifact(project: Path, out: dict[str, list[dict[str, Any]]], key: str, source_path: str, kind: str) -> None:
    descriptor = _artifact(project, source_path, kind)
    out.setdefault(key, []).append(descriptor)


def _existing(project: Path, relative: str) -> bool:
    path = project / relative
    return path.is_file() and not path.is_symlink()


def _inline_artifact(
    out: dict[str, list[dict[str, Any]]],
    key: str,
    *,
    package_path: str,
    kind: str,
    content: object,
) -> None:
    payload = (json.dumps(content, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode()
    out.setdefault(key, []).append({
        "path": package_path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "kind": kind,
        "content": copy.deepcopy(content),
    })


def _safe_parse_projection(project: Path, study_id: str) -> dict[str, Any]:
    try:
        state = parse_quality_state(project, study_id)
    except ParseQualityError as exc:
        raise ContentAgentError(exc.code) from exc
    return {
        "study_id": study_id,
        "status": state["status"],
        "workflow_can_continue": state["workflow_can_continue"],
        "objects": [
            {
                "kind": row["kind"], "source_id": row["source_id"],
                "status": row["status"], "issues": row["issues"],
                "decision": (
                    {key: row["decision"].get(key) for key in ("action", "note", "actor_type", "actor_label")}
                    if isinstance(row.get("decision"), dict) else None
                ),
            }
            for row in state["objects"]
        ],
    }


def _safe_chemical_projection(project: Path, study_id: str) -> dict[str, Any]:
    try:
        projection = chemical_paper_projection(project)
    except ChemicalPaperError as exc:
        raise ContentAgentError(exc.code) from exc
    matches = [row for row in projection["studies"] if row["study_id"] == study_id]
    if len(matches) != 1:
        raise ContentAgentError("CHEMICAL_PAPER_NOT_IMPORTED")
    row = matches[0]
    return {
        key: copy.deepcopy(row[key])
        for key in (
            "study_id", "status", "backend", "version", "page_count", "molecule_count",
            "reaction_data_status", "missing_field_counts", "gaps", "limitations"
        )
    } | {
        "molecules": [
            {
                key: copy.deepcopy(molecule[key])
                for key in (
                    "molecule_index", "page", "bbox_normalized", "mol_idt",
                    "resolved_smiles", "smiles_candidates", "missing_fields",
                    "candidate_elements", "history"
                )
            }
            for molecule in row["molecules"]
        ]
    }


def _safe_reconciliation_projection(project: Path, study_id: str) -> dict[str, Any]:
    try:
        registry = load_parse_reconciliation(project, study_id)
    except ParseReconciliationError as exc:
        raise ContentAgentError(exc.code) from exc
    return {
        "study_id": study_id,
        "workflow_can_continue": registry["workflow_can_continue"],
        "objects": [
            {
                "kind": row["kind"], "source_id": row["source_id"], "page": row["page"],
                "generic_candidate": row["generic_candidate"],
                "chemical_candidate": row["chemical_candidate"], "status": row["status"],
                "decision": (
                    {key: row["decision"].get(key) for key in ("action", "selected_lane", "note", "pdf_locator", "actor_type", "actor_label")}
                    if isinstance(row.get("decision"), dict) else None
                ),
            }
            for row in registry["objects"]
        ],
    }


def _dual_source_artifacts(
    project: Path,
    studies: Iterable[str],
    request: dict[str, Any],
    out: dict[str, list[dict[str, Any]]],
) -> None:
    for study_id in studies:
        try:
            bindings = require_dual_evidence_ready(
                project,
                study_id,
                requires_chemical=bool(request["field_dependencies"]),
            )
            bundle = load_source_truth_bundle(project, study_id)
        except (PaperEvidenceError, SourceTruthError) as exc:
            raise ContentAgentError(exc.code) from exc
        for source in bundle["sources"]:
            if source.get("document_role") != "MAIN":
                continue
            for field, kind in (
                ("pdf", "source_asset:pdf"),
                ("canonical_markdown", "source_asset:canonical_markdown"),
                ("content_list_v2", "source_asset:content_list"),
            ):
                descriptor = source.get(field)
                if not isinstance(descriptor, dict) or not isinstance(descriptor.get("path"), str):
                    raise ContentAgentError("SOURCE_TRUTH_INVALID")
                _add_artifact(project, out, "source_truth", descriptor["path"], kind)
        _inline_artifact(
            out, "parse_quality", package_path=f"inputs/safe/{study_id}/parse-quality.json",
            kind="parse_quality_safe_projection", content=_safe_parse_projection(project, study_id),
        )
        if bindings["chemical_completion_digest"] is not None:
            _inline_artifact(
                out, "chemical_paper", package_path=f"inputs/safe/{study_id}/chemical-paper.json",
                kind="chemical_paper_safe_projection", content=_safe_chemical_projection(project, study_id),
            )
            _inline_artifact(
                out, "reconciliation", package_path=f"inputs/safe/{study_id}/reconciliation.json",
                kind="reconciliation_safe_projection", content=_safe_reconciliation_projection(project, study_id),
            )


def _source_artifacts(project: Path, studies: Iterable[str], out: dict[str, list[dict[str, Any]]]) -> None:
    for study_id in studies:
        try:
            bundle = load_source_truth_bundle(project, study_id)
        except SourceTruthError as exc:
            raise ContentAgentError(exc.code) from exc
        bundle_rel = f"01_evidence/source_truth/{study_id}/bundle.json"
        _add_artifact(project, out, "source_truth", bundle_rel, "source_truth_bundle")
        sources = bundle.get("sources", [])
        if not isinstance(sources, list):
            raise ContentAgentError("SOURCE_TRUTH_INVALID")
        for source in sources:
            if not isinstance(source, dict):
                raise ContentAgentError("SOURCE_TRUTH_INVALID")
            for name, descriptor in source.items():
                if name not in {"pdf", "canonical_markdown", "content_list", "layout", "reading_layer", "layout_layer"}:
                    continue
                if not isinstance(descriptor, dict) or not isinstance(descriptor.get("path"), str):
                    raise ContentAgentError("SOURCE_TRUTH_INVALID")
                _add_artifact(project, out, "source_truth", descriptor["path"], f"source_asset:{name}")
        parse_rel = f"01_evidence/source_truth/{study_id}/parse_quality.json"
        _add_artifact(project, out, "parse_quality", parse_rel, "parse_quality_gate")


def _chemical_paper_source_artifacts(
    project: Path,
    studies: Iterable[str],
    out: dict[str, list[dict[str, Any]]],
) -> None:
    for study_id in studies:
        try:
            state = load_chemical_paper_state(project, study_id)
            pdf_path = source_truth_asset(
                project,
                study_id,
                state["source_id"],
                "pdf",
            )
        except (ChemicalPaperError, SourceTruthError) as exc:
            raise ContentAgentError(exc.code) from exc
        state_relative = (
            CHEMICAL_PAPER_STATE_ROOT / study_id / CHEMICAL_PAPER_STATE_NAME
        ).as_posix()
        pdf_relative = pdf_path.relative_to(project).as_posix()
        _add_artifact(
            project,
            out,
            "chemical_paper",
            state_relative,
            "chemical_paper_state",
        )
        _add_artifact(
            project,
            out,
            "source_truth",
            pdf_relative,
            "source_asset:pdf",
        )


def _collect_inputs(project: Path, request: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    inputs: dict[str, list[dict[str, Any]]] = {}
    studies = request["target_ids"] if request["request_kind"] == "paper_evidence" else declared_study_ids(project)
    if (project / "01_evidence/dual_source").exists():
        _dual_source_artifacts(project, studies, request, inputs)
    elif (project / CHEMICAL_PAPER_STATE_ROOT).exists():
        _chemical_paper_source_artifacts(project, studies, inputs)
    else:
        _source_artifacts(project, studies, inputs)
    if request["request_kind"] != "paper_evidence":
        evidence_projection = "01_evidence/paper_evidence_projection.jsonl"
        if _existing(project, evidence_projection):
            _add_artifact(project, inputs, "paper_evidence", evidence_projection, "paper_evidence_projection")
        for study_id in studies:
            candidate = f"01_evidence/{study_id}/paper_evidence_candidates.json"
            if _existing(project, candidate):
                _add_artifact(project, inputs, "paper_evidence", candidate, "paper_evidence_candidates")
    if request["request_kind"] in {"synthesis_claims", "section_draft"}:
        for relative, kind in (
            ("02_synthesis/comparison_protocol.json", "comparison_protocol"),
            ("02_synthesis/coverage_map.json", "coverage_map"),
            ("02_synthesis/synthesis_claim_projection.jsonl", "synthesis_claims"),
        ):
            if _existing(project, relative):
                _add_artifact(project, inputs, "comparison_protocol", relative, kind)
    if request["request_kind"] == "section_draft":
        relative = "02_synthesis/section_contracts.jsonl"
        if _existing(project, relative):
            _add_artifact(project, inputs, "section_contract", relative, "section_contracts")
    if set(inputs) - ALLOWED_INPUTS:
        raise ContentAgentError("PACKAGE_INPUTS_OUT_OF_SCOPE")
    return inputs


def _package_digest(package: dict[str, Any]) -> str:
    keys = ("schema_version", "project_id", "request_kind", "target_ids", "field_dependencies", "inputs", "chemical_paper_import_bindings")
    value = {key: package[key] for key in keys if key in package}
    return canonical_digest(value)


def _chemical_paper_bindings(project: Path, studies: Iterable[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for study_id in studies:
        relative = project / CHEMICAL_PAPER_STATE_ROOT / study_id / CHEMICAL_PAPER_STATE_NAME
        if not relative.exists():
            continue
        try:
            state = load_chemical_paper_state(project, study_id)
        except ChemicalPaperError as exc:
            raise ContentAgentError(exc.code) from exc
        rows.append(
            {
                "study_id": study_id,
                "source_id": state["source_id"],
                "source_truth_bundle_digest": state["source_truth_bundle_digest"],
                "source_pdf_sha256": state["source_pdf_sha256"],
                "chemical_paper_import_digest": state["current_import_digest"],
            }
        )
    return sorted(rows, key=lambda row: row["study_id"])


def _forbidden_in_package(value: object) -> bool:
    # Check names and path-bearing values, while avoiding scientific prose false positives.
    if isinstance(value, dict):
        for key, item in value.items():
            if any(word in str(key).casefold() for word in _FORBIDDEN_TEXT):
                return True
            if _forbidden_in_package(item):
                return True
    elif isinstance(value, list):
        return any(_forbidden_in_package(item) for item in value)
    elif isinstance(value, str):
        if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
            return True
        # These are protocol-level forbidden markers, not words in source prose.
        if value.casefold() in {"auth", "04_first_draft", "prompt"}:
            return True
    return False


def build_content_task_package(project: Path, request: object, output_dir: Path | None = None) -> dict[str, Any]:
    """Build a read-only, hash-bound package manifest for a Content Agent."""
    root = _root(project)
    normalized = _normalize_request(root, request)
    inputs = _collect_inputs(root, normalized)
    package = {
        "schema_version": "content-agent-task-package.v1",
        "project_id": root.name,
        "request_kind": normalized["request_kind"],
        "target_ids": list(normalized["target_ids"]),
        "field_dependencies": list(normalized["field_dependencies"]),
        "inputs": inputs,
    }
    studies = normalized["target_ids"] if normalized["request_kind"] == "paper_evidence" else declared_study_ids(root)
    bindings = _chemical_paper_bindings(root, studies)
    if bindings and not (root / "01_evidence/dual_source").exists():
        package["chemical_paper_import_bindings"] = bindings
    package["task_package_digest"] = _package_digest(package)
    if _forbidden_in_package(package):
        raise ContentAgentError("PACKAGE_FORBIDDEN_INPUT")
    if output_dir is not None:
        destination = Path(output_dir)
        try:
            destination.resolve(strict=False).relative_to(root)
        except ValueError:
            pass
        else:
            raise ContentAgentError("PACKAGE_OUTPUT_IN_PROJECT")
        if destination.exists():
            raise ContentAgentError("PACKAGE_OUTPUT_INVALID")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
        staged = temporary / destination.name
        try:
            staged.mkdir()
            for entries in inputs.values():
                for item in entries:
                    target = staged / item["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if "source_path" in item:
                        source = _safe_project_relative(root, item["source_path"])
                        shutil.copyfile(source, target)
                    else:
                        target.write_text(
                            json.dumps(item["content"], ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                            encoding="utf-8",
                        )
            (staged / "manifest.json").write_text(
                json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(staged, destination)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
    return package


def _result_without_digest(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "result_digest"}


def _validate_result_shape(result: object) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ContentAgentError("RESULT_INVALID")
    value = copy.deepcopy(result)
    _validate_schema(value, RESULT_SCHEMA, "RESULT_INVALID")
    if value["result_digest"] != canonical_digest(_result_without_digest(value)):
        raise ContentAgentError("RESULT_DIGEST_INVALID")
    content = value["content"]
    if not isinstance(content, dict):
        raise ContentAgentError("RESULT_INVALID")
    kind = value["request_kind"]
    allowed = {
        "paper_evidence": {"evidence_candidates", "source_figure_suggestions"},
        "synthesis_claims": {"comparison_protocol", "coverage_map", "synthesis_claims", "source_figure_suggestions"},
        "section_draft": {"section_contracts"},
    }[kind]
    if set(content) - allowed or not set(content) & allowed:
        raise ContentAgentError("RESULT_CONTENT_OUT_OF_SCOPE")
    if kind == "paper_evidence" and not isinstance(content.get("evidence_candidates"), list):
        raise ContentAgentError("RESULT_CONTENT_INVALID")
    if kind == "synthesis_claims":
        if not any(
            content.get(key) not in (None, [], {})
            for key in ("comparison_protocol", "coverage_map", "synthesis_claims")
        ):
            raise ContentAgentError("RESULT_CONTENT_INVALID")
    if kind == "section_draft" and not isinstance(content.get("section_contracts"), list):
        raise ContentAgentError("RESULT_CONTENT_INVALID")
    return value


def _contains_decision(value: object) -> bool:
    if isinstance(value, dict):
        if "decision" in value and value["decision"] is not None:
            return True
        return any(_contains_decision(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_decision(item) for item in value)
    return False


def _result_scope(root: Path, result: dict[str, Any]) -> None:
    if result["project_id"] != root.name:
        raise ContentAgentError("PROJECT_ID_MISMATCH")
    try:
        studies = set(declared_study_ids(root))
    except SourceTruthError as exc:
        raise ContentAgentError(exc.code) from exc
    targets = set(result["target_ids"])
    if result["request_kind"] == "paper_evidence" and not targets <= studies:
        raise ContentAgentError("RESULT_OUT_OF_SCOPE")
    if result["request_kind"] == "synthesis_claims" and targets != studies:
        raise ContentAgentError("RESULT_OUT_OF_SCOPE")
    content = result["content"]
    if result["request_kind"] == "paper_evidence":
        candidates = content.get("evidence_candidates", [])
        suggestions = content.get("source_figure_suggestions", [])
        for row in [*candidates, *suggestions]:
            if not isinstance(row, dict):
                raise ContentAgentError("RESULT_OUT_OF_SCOPE")
            # A single-study evidence request may omit study_id; the importer
            # supplies the sole bounded target to the existing registrar.
            if row.get("study_id") is None and len(targets) == 1:
                continue
            if row.get("study_id") not in targets:
                raise ContentAgentError("RESULT_OUT_OF_SCOPE")
        for row in suggestions:
            if not isinstance(row, dict):
                raise ContentAgentError("RESULT_CONTENT_INVALID")
            if any(key in row for key in ("decision", "status", "selection_status")):
                raise ContentAgentError("CONTENT_AGENT_CANNOT_APPROVE")
            if any(any(token in str(key).casefold() for token in ("auth", "prompt", "session")) for key in row):
                raise ContentAgentError("RESULT_CONTENT_OUT_OF_SCOPE")
            for item in row.values():
                if isinstance(item, str) and (item.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", item)):
                    raise ContentAgentError("RESULT_CONTENT_OUT_OF_SCOPE")
            if not isinstance(row.get("source_id"), str) or not row["source_id"].strip():
                raise ContentAgentError("RESULT_CONTENT_INVALID")
            if not isinstance(row.get("page"), int) or isinstance(row.get("page"), bool) or row["page"] < 1:
                raise ContentAgentError("RESULT_CONTENT_INVALID")
            for key in ("asset_path", "source_path"):
                if key in row and not _is_relative(row[key]):
                    raise ContentAgentError("RESULT_CONTENT_INVALID")
            if "source_pdf_sha256" in row and (
                not isinstance(row["source_pdf_sha256"], str) or not _SHA256.fullmatch(row["source_pdf_sha256"])
            ):
                raise ContentAgentError("RESULT_CONTENT_INVALID")
    elif result["request_kind"] == "section_draft":
        for row in content.get("section_contracts", []):
            if not isinstance(row, dict) or row.get("section_id") not in targets:
                raise ContentAgentError("RESULT_OUT_OF_SCOPE")


def _expected_task_digest(root: Path, result: dict[str, Any]) -> str:
    dependencies = sorted({
        dependency
        for row in result.get("content", {}).get("evidence_candidates", [])
        if isinstance(row, dict)
        for dependency in row.get("field_dependencies", [])
        if isinstance(dependency, str)
    }) if result["request_kind"] == "paper_evidence" else []
    request = {
        "schema_version": "content-agent-request.v1",
        "request_kind": result["request_kind"],
        "project_id": root.name,
        "target_ids": result["target_ids"],
        "reason": "Content Agent candidate content requested by the review workflow.",
        "field_dependencies": dependencies,
    }
    package = build_content_task_package(root, request)
    return package["task_package_digest"]


def _snapshot(root: Path) -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file() or path.name == ".paper_evidence.lock":
            continue
        values[path.relative_to(root).as_posix()] = path.read_bytes()
    return values


def _write_bytes_atomic(root: Path, relative: str, data: bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(target) and (target.is_symlink() or not target.is_file()):
        raise ContentAgentError("IMPORT_PATH_INVALID")
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except OSError as exc:
        raise ContentAgentError("IMPORT_WRITE_FAILED") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _apply_on_copy(root: Path, result: dict[str, Any]) -> None:
    content = result["content"]
    try:
        if result["request_kind"] == "paper_evidence":
            for candidate in content.get("evidence_candidates", []):
                study_id = candidate.get("study_id") or result["target_ids"][0]
                locator = candidate.get("locator") if isinstance(candidate.get("locator"), dict) else {}
                if locator.get("source_mode") == "original_pdf_manual":
                    register_manual_pdf_evidence(root, {**candidate, "study_id": study_id})
                else:
                    register_paper_evidence_candidates(root, study_id, candidate)
            suggestions = content.get("source_figure_suggestions", [])
            if suggestions:
                path = root / _SUGGESTION_PATH
                prior = []
                if path.is_file():
                    prior = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                by_id = {row.get("suggestion_id"): row for row in prior if isinstance(row, dict)}
                for row in suggestions:
                    sid = row.get("suggestion_id") or canonical_digest(row)
                    if sid in by_id and by_id[sid] != row:
                        raise ContentAgentError("SUGGESTION_CONFLICT")
                    by_id[sid] = row
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in sorted(by_id.values(), key=lambda r: str(r.get("suggestion_id", "")))), encoding="utf-8")
        elif result["request_kind"] == "synthesis_claims":
            protocol = content.get("comparison_protocol")
            if protocol is not None:
                register_comparison_protocol(root, protocol)
            coverage = content.get("coverage_map")
            if coverage is not None:
                register_coverage_map(root, coverage)
            claims = content.get("synthesis_claims")
            if claims:
                register_synthesis_candidates(root, {"claims": claims})
        else:
            register_section_contracts(root, {"contracts": content["section_contracts"]})
    except (PaperEvidenceError, SynthesisError, SectionContractError, PaperEvidenceStoreError) as exc:
        code = getattr(exc, "code", str(exc))
        raise ContentAgentError(str(code)) from exc


def import_content_agent_result(project: Path, result: object) -> dict[str, Any]:
    """Validate and atomically import a candidate result; no approval is accepted."""
    root = _root(project)
    value = _validate_result_shape(result)
    if _contains_decision(value["content"]):
        raise ContentAgentError("CONTENT_AGENT_CANNOT_APPROVE")
    _result_scope(root, value)
    if value["task_package_digest"] != _expected_task_digest(root, value):
        raise ContentAgentError("TASK_PACKAGE_STALE")
    with tempfile.TemporaryDirectory(prefix="review-writer-content-import-") as temporary:
        staging = Path(temporary) / root.name
        shutil.copytree(root, staging, symlinks=True)
        _apply_on_copy(staging, value)
        before = _snapshot(root)
        after = _snapshot(staging)
        changed = sorted(path for path, data in after.items() if before.get(path) != data)
        deleted = sorted(path for path in before if path not in after)
        if deleted:
            raise ContentAgentError("IMPORT_DELETE_FORBIDDEN")
        if any(path.startswith("04_first_draft/") or path == "04_first_draft" for path in changed):
            raise ContentAgentError("IMPORT_OUT_OF_SCOPE")
        with project_write_lock(root):
            written: list[str] = []
            try:
                for relative in changed:
                    _write_bytes_atomic(root, relative, (staging / relative).read_bytes())
                    written.append(relative)
            except Exception:
                # Restore the pre-import bytes if an unexpected filesystem
                # error occurs after one of the replacements.
                for relative in reversed(written):
                    if relative in before:
                        _write_bytes_atomic(root, relative, before[relative])
                    else:
                        (root / relative).unlink(missing_ok=True)
                raise
    return {"status": "imported", "project_id": root.name, "request_kind": value["request_kind"], "changed_files": changed, "result_digest": value["result_digest"]}
