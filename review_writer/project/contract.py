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
from .path_safety import PathSafetyError, validate_relative_path, validate_source_file


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
    try: return validate_relative_path(value)
    except PathSafetyError as exc: _fail("SOURCE_PATH_NONCANONICAL", str(exc))


def _within(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def validate_source_path(root: Path, relative: str) -> Path:
    """Standard-library-only path boundary used by both local and Windows smoke."""
    try: return validate_source_file(root, relative)
    except PathSafetyError as exc: _fail("SOURCE_PATH_REPARSE", str(exc))


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
        actual = validate_source_path(root, relative)
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


def _require_hash(value: Any, code: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        _fail(code, "expected lowercase SHA-256")
    return value


def _validate_claim(claim: dict[str, Any], sources: dict[str, dict[str, Any]], parses: dict[str, dict[str, Any]]) -> None:
    required = {"project_id", "claim_id", "claim_version", "claim_version_id", "claim_text", "claim_text_sha256", "epistemic_class", "evidence_refs", "supporting_claim_refs", "conflict_refs"}
    if not required <= set(claim) or claim["epistemic_class"] not in {"SOURCE_OBSERVATION", "AUTHOR_INTERPRETATION", "PROPOSED_MECHANISM", "REVIEWER_SYNTHESIS"}:
        _fail("CLAIM_RECORD_INVALID", "minimum claim fields or class missing")
    if hashlib.sha256(claim["claim_text"].encode("utf-8")).hexdigest() != claim["claim_text_sha256"]:
        _fail("CLAIM_TEXT_HASH_INVALID", "claim text hash mismatch")
    if claim["epistemic_class"] != "REVIEWER_SYNTHESIS" and not claim["evidence_refs"]:
        _fail("CLAIM_EVIDENCE_REQUIRED", "non-synthesis claim requires evidence")
    for ref in claim["evidence_refs"]:
        source = sources.get(ref.get("source_id")); parse = parses.get(ref.get("parse_artifact_id"))
        if not source or not parse or not source_is_claim_eligible(source, ref) or parse.get("source_content_sha256") != ref.get("source_content_sha256") or parse.get("validation_status") != "VALIDATED":
            _fail("CLAIM_EVIDENCE_INVALID", "source/parse evidence reference is not current and eligible")


def validate_snapshot_package(package: dict[str, Any]) -> dict[str, Any]:
    """Validate one explicit immutable package; this is a view, not a replay service."""
    project_id = package.get("project_id"); config = _require_hash(package.get("resolved_config_sha256"), "CONFIG_HASH_INVALID")
    artifact = package.get("artifact", {}); ref = artifact.get("artifact_ref", {})
    digest = _require_hash(ref.get("content_sha256"), "ARTIFACT_HASH_INVALID")
    if artifact.get("artifact_id") != ref.get("artifact_id"):
        _fail("ARTIFACT_REF_INVALID", "artifact identity mismatch")
    sources = {source.get("source_id"): source for source in package.get("sources", [])}
    parses = {parse.get("parse_artifact_id"): parse for parse in package.get("parses", [])}
    if not sources or not parses or any(source.get("project_id") != project_id or not _require_hash(source.get("content_sha256"), "SOURCE_HASH_INVALID") for source in sources.values()):
        _fail("SOURCE_RECORD_INVALID", "source record binding missing")
    for parse in parses.values():
        if parse.get("project_id") != project_id or parse.get("source_id") not in sources or parse.get("source_content_sha256") != sources[parse["source_id"]].get("content_sha256"):
            _fail("PARSE_ARTIFACT_INVALID", "parse must bind current source hash")
    claims = {claim.get("claim_version_id"): claim for claim in package.get("claims", [])}
    if not claims: _fail("CLAIM_RECORD_INVALID", "claims required")
    for claim in claims.values(): _validate_claim(claim, sources, parses)
    decisions = package.get("decisions", [])
    allowed_events = {"EVIDENCE_SUPPORT", "REGISTER", "REJECT", "WITHDRAW", "SUPERSEDE", "CHECKPOINT_APPROVE"}
    states = {key: {"support": "NOT_EVALUATED", "registered": False} for key in claims}
    for event in decisions:
        if event.get("event_type") == "AI_INFERENCE": _fail("AI_INFERENCE_FORBIDDEN", "AI inference cannot register facts")
        if event.get("event_type") not in allowed_events or event.get("claim_version_id") not in states:
            _fail("CLAIM_DECISION_INVALID", "unknown or malformed decision")
        state = states[event["claim_version_id"]]
        if event["event_type"] == "EVIDENCE_SUPPORT":
            if event.get("evidence_support_status") not in {"SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"}: _fail("CLAIM_DECISION_INVALID", "support status invalid")
            state["support"] = event["evidence_support_status"]
        elif event["event_type"] == "REGISTER": state["registered"] = True
    view = claim_registry_view(list(claims.values()), decisions, list(sources.values()), active_scope_claim_ids={item["claim_id"] for item in claims.values()})
    for conflict in package.get("conflicts", []): conflict_compatibility_matrix(conflict)
    for claim_id, claim in claims.items():
        if claim["epistemic_class"] == "REVIEWER_SYNTHESIS":
            deps = claim["supporting_claim_refs"]
            if len(deps) < 2 or any(dep not in view or not view[dep]["writing_eligible"] or claims[dep]["epistemic_class"] == "REVIEWER_SYNTHESIS" for dep in deps): _fail("SUPPORTING_CLAIM_INVALID", "synthesis requires two current eligible material claims")
        if states[claim_id]["registered"] and states[claim_id]["support"] != "SUPPORTED": _fail("CLAIM_REGISTRATION_INVALID", "only supported claim may register")
    for key in ("checkpoint", "run", "release"):
        record = package.get(key, {})
        if record.get("project_id") != project_id or record.get("resolved_config_sha256") != config: _fail("SNAPSHOT_CONFIG_DRIFT", "downstream record config binding mismatch")
    if package["checkpoint"].get("approved_artifact_sha256") != digest or package["run"].get("snapshot_artifact_sha256") != digest or package["release"].get("artifact_ref", {}).get("content_sha256") != digest:
        _fail("SNAPSHOT_CLOSURE_INVALID", "checkpoint/run/release artifact binding mismatch")
    return {"closed": True, "summary": {name: "CLOSED" for name in ("project", "corpus", "claims", "checkpoint", "run", "release")}, "claims": view}


def adapt_legacy_case_package(legacy: dict[str, Any]) -> dict[str, Any]:
    """Copy and map only legacy roles; no frozen input is modified."""
    adapted = copy.deepcopy(legacy)
    adapted["sources"] = adapt_legacy_case_sources(adapted.get("sources", []))
    for conflict in adapted.get("conflicts", []):
        conflict.update({"comparability": "EXPLICITLY_INCOMPARABLE", "classification": "SOURCE_INTERNAL_CONFLICT", "status": "EXCLUDED"})
    return adapted
