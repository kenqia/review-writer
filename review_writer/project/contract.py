"""Small, offline, case-neutral M0 evidence-contract predicates and snapshots."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .manifest import ManifestResolutionError, resolve_project_manifest


SHA256 = re.compile(r"^[0-9a-f]{64}$")
ADAPTER_REFS = frozenset({"case-01-frozen-v1"})


class ContractError(ValueError):
    """An explicit M0 contract boundary violation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ContractError(code, message)


def _portable_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        _fail("SOURCE_PATH_NONCANONICAL", "paths must be non-empty relative POSIX paths")
    if re.match(r"^[A-Za-z]:", value) or value.startswith("//") or value.startswith("\\\\"):
        _fail("SOURCE_PATH_ABSOLUTE", "drive and UNC paths are forbidden")
    pieces = value.split("/")
    if any(piece in {"", ".", ".."} for piece in pieces):
        _fail("SOURCE_PATH_NONCANONICAL", "dot, traversal, and repeated separators are forbidden")
    return "/".join(pieces)


def _within(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def validate_manifest_inputs(manifest: dict[str, Any], manifest_directory: Path) -> dict[str, Any]:
    """Resolve manifest and read only ordinary, contained source inputs to hash them."""
    try:
        resolved = resolve_project_manifest(manifest)
    except ManifestResolutionError as exc:
        _fail(exc.code, str(exc))
    if resolved["output_language"] != "en" or resolved["citation_style"] != "BRACKETED_NUMERIC":
        _fail("PROJECT_CONSTANT_INVALID", "output_language=en and citation_style=BRACKETED_NUMERIC are required")
    adapter = resolved.get("adapter_ref")
    if adapter is not None and adapter not in ADAPTER_REFS:
        _fail("ADAPTER_REF_INVALID", "adapter_ref is not a product-maintained closed ID")
    root_value = _portable_path(resolved["paths"]["seed_source_root"])
    root = (Path(manifest_directory) / root_value).resolve(strict=True)
    if not root.is_dir():
        _fail("SEED_SOURCE_ROOT_INVALID", "seed source root is not a directory")
    source_ids: set[str] = set()
    normalized_paths: set[str] = set()
    papers: dict[str, list[dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    for item in resolved["initial_source_inputs"]:
        source_id = item["source_id"]
        if source_id in source_ids:
            _fail("SOURCE_ID_DUPLICATE", "source_id must be unique")
        source_ids.add(source_id)
        relative = _portable_path(item["relative_path"])
        collision_key = relative.casefold()
        if collision_key in normalized_paths:
            _fail("NORMALIZED_SOURCE_PATH_DUPLICATE", "source paths collide across Windows/POSIX")
        normalized_paths.add(collision_key)
        candidate = root.joinpath(*relative.split("/"))
        try:
            actual = candidate.resolve(strict=True)
        except OSError as exc:
            _fail("SOURCE_PATH_UNREADABLE", str(exc))
        if not _within(root, actual):
            _fail("SOURCE_PATH_ESCAPE", "symlink or reparse target escapes seed root")
        if not actual.is_file():
            _fail("SOURCE_PATH_NOT_ORDINARY_FILE", "source input must be an ordinary file")
        hashes[source_id] = hashlib.sha256(actual.read_bytes()).hexdigest()
        papers.setdefault(item["paper_id"], []).append(item)
    for paper_id, items in papers.items():
        mains = [item for item in items if item["document_role"] == "MAIN"]
        if len(mains) != 1:
            _fail("PAPER_MAIN_CARDINALITY", f"paper {paper_id} must have exactly one MAIN")
        if any(item["document_role"] == "SI" for item in items) and not mains:
            _fail("SI_MAIN_MISSING", f"paper {paper_id} SI requires same-paper MAIN")
    resolved["source_hashes"] = hashes
    return resolved


def source_is_claim_eligible(source: dict[str, Any], reference: dict[str, Any]) -> bool:
    return (
        source.get("governance_status") == "INCLUDED"
        and source.get("usage_role") == "EVIDENCE"
        and source.get("availability_status") == "PARSED"
        and source.get("integrity_status") == "VALIDATED"
        and bool(source.get("active_parse_artifact_id"))
        and source.get("active_parse_artifact_id") == reference.get("parse_artifact_id")
        and source.get("source_id") == reference.get("source_id")
        and source.get("source_version") == reference.get("source_version")
        and source.get("content_sha256") == reference.get("source_content_sha256")
        and bool(reference.get("locator"))
        and bool(SHA256.fullmatch(str(reference.get("excerpt_sha256", ""))))
    )


def claim_registry_view(claims: list[dict[str, Any]], decisions: list[dict[str, Any]], sources: list[dict[str, Any]], *, active_scope_claim_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Build the M0 current/eligibility view from supplied immutable records."""
    source_by_id = {item.get("source_id"): item for item in sources}
    by_version = {item["claim_version_id"]: item for item in claims}
    outcome: dict[str, dict[str, Any]] = {version: {"evidence_support_status": "NOT_EVALUATED", "governance_status": "CANDIDATE"} for version in by_version}
    for event in decisions:
        state = outcome.get(event.get("claim_version_id"))
        if state is None:
            continue
        if event.get("event_type") == "EVIDENCE_SUPPORT":
            state["evidence_support_status"] = event.get("evidence_support_status", "NOT_EVALUATED")
        elif event.get("event_type") in {"REGISTER", "REJECT", "WITHDRAW", "SUPERSEDE"}:
            state["governance_status"] = {"REGISTER": "REGISTERED", "REJECT": "REJECTED", "WITHDRAW": "WITHDRAWN", "SUPERSEDE": "SUPERSEDED"}[event["event_type"]]
    current: dict[str, str] = {}
    for version, claim in by_version.items():
        state = outcome[version]
        if state["governance_status"] == "REGISTERED":
            prior = current.get(claim["claim_id"])
            if prior is None or claim["claim_version"] > by_version[prior]["claim_version"]:
                current[claim["claim_id"]] = version
    for version, claim in by_version.items():
        state = outcome[version]
        evidence_ok = all(source_is_claim_eligible(source_by_id.get(ref.get("source_id"), {}), ref) for ref in claim.get("evidence_refs", []))
        state["current"] = current.get(claim["claim_id"]) == version
        state["writing_eligible"] = bool(
            state["current"] and state["evidence_support_status"] == "SUPPORTED"
            and state["governance_status"] == "REGISTERED" and evidence_ok
            and claim["claim_id"] in active_scope_claim_ids
        )
    return outcome


def conflict_compatibility_matrix(conflict: dict[str, Any]) -> dict[str, Any]:
    """Validate explicit comparability input; never infer scientific comparability."""
    incomparable = conflict.get("comparability") == "EXPLICITLY_INCOMPARABLE"
    invalid = incomparable and (conflict.get("classification"), conflict.get("status")) != ("SOURCE_INTERNAL_CONFLICT", "EXCLUDED")
    if invalid:
        _fail("CONFLICT_COMBINATION_INVALID", "incomparable records may only be excluded source-internal conflicts")
    return {"classification": conflict.get("classification"), "status": conflict.get("status"), "permits_manuscript_treatment": not incomparable and conflict.get("status") == "ACTIVE"}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create_immutable_json(path: Path, record: dict[str, Any]) -> Path:
    if path.exists():
        _fail("IMMUTABLE_OUTPUT_EXISTS", f"immutable output exists: {path}")
    payload = copy.deepcopy(record)
    artifact = payload.setdefault("artifact_ref", {})
    artifact["artifact_sha256"] = ""
    artifact["artifact_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    except FileExistsError:
        _fail("IMMUTABLE_OUTPUT_EXISTS", f"immutable output exists: {path}")
    return path


def verify_closure(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        expected = value["artifact_ref"]["artifact_sha256"]
        value["artifact_ref"]["artifact_sha256"] = ""
        return bool(SHA256.fullmatch(expected)) and hashlib.sha256(_canonical_bytes(value)).hexdigest() == expected
    except (OSError, ValueError, KeyError, TypeError):
        return False


def snapshot_view(artifact: dict[str, Any], checkpoint: dict[str, Any], run: dict[str, Any], release: dict[str, Any]) -> dict[str, Any]:
    digest = artifact.get("artifact_sha256")
    closed = bool(SHA256.fullmatch(str(digest))) and all(item.get(key) == digest for item, key in ((checkpoint, "approved_artifact_sha256"), (run, "snapshot_artifact_sha256"), (release, "release_artifact_sha256")))
    return {"artifact_id": artifact.get("artifact_id"), "closed": closed}


def adapt_legacy_case_sources(legacy_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map frozen legacy source_role records without modifying their source bytes."""
    adapted = copy.deepcopy(legacy_sources)
    for record in adapted:
        role = record.get("source_role")
        if role not in {"MAIN", "SI"}:
            _fail("LEGACY_DOCUMENT_ROLE_INVALID", "legacy source_role must be MAIN or SI")
        record["document_role"] = role
    return adapted


def project_id_is_locked(immutable_records: list[dict[str, Any]]) -> bool:
    """A caller supplies only immutable project/run record presence; no history is mutated."""
    return any(record.get("record_type") in {"ProjectRecord", "RunManifest"} for record in immutable_records)
