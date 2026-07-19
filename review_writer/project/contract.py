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
from .path_safety import PathSafetyError, validate_relative_path, validate_source_file, validate_source_inputs


SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def validate_manifest_inputs(manifest: dict[str, Any], manifest_directory: Path, *, allowed_adapter_refs: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Resolve manifest and read only ordinary, contained source inputs to hash them."""
    try:
        resolved = resolve_project_manifest(manifest)
    except ManifestResolutionError as exc:
        _fail(exc.code, str(exc))
    if resolved["output_language"] != "en" or resolved["citation_style"] != "BRACKETED_NUMERIC":
        _fail("PROJECT_CONSTANT_INVALID", "output_language=en and citation_style=BRACKETED_NUMERIC are required")
    adapter = resolved.get("adapter_ref")
    if adapter is not None and adapter not in allowed_adapter_refs:
        _fail("ADAPTER_REF_INVALID", "adapter_ref is not a product-maintained closed ID")
    root_value = _portable_path(resolved["paths"]["seed_source_root"])
    root = (Path(manifest_directory) / root_value).resolve(strict=True)
    if not root.is_dir():
        _fail("SEED_SOURCE_ROOT_INVALID", "seed source root is not a directory")
    source_ids: set[str] = set()
    papers: dict[str, list[dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    for item in resolved["initial_source_inputs"]:
        source_id = item["source_id"]
        if source_id in source_ids:
            _fail("SOURCE_ID_DUPLICATE", "source_id must be unique")
        source_ids.add(source_id)
        relative = _portable_path(item["relative_path"])
        try: actual = validate_source_inputs(root, [entry["relative_path"] for entry in resolved["initial_source_inputs"][:len(source_ids)]])[-1]
        except PathSafetyError as exc: _fail("NORMALIZED_SOURCE_PATH_DUPLICATE", str(exc))
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


def _derive_registry_view(claims: list[dict[str, Any]], decisions: list[dict[str, Any]], sources: list[dict[str, Any]], *, active_scope_claim_ids: set[str]) -> dict[str, dict[str, Any]]:
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

def seal_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical immutable record seal; callers never mutate old bytes."""
    sealed = copy.deepcopy(record); sealed["record_sha256"] = ""
    sealed["record_sha256"] = hashlib.sha256(_canonical_bytes(sealed)).hexdigest()
    return sealed

def _verify_record(record: dict[str, Any], code: str) -> None:
    expected = _require_hash(record.get("record_sha256"), code)
    copy_record = copy.deepcopy(record); copy_record["record_sha256"] = ""
    if hashlib.sha256(_canonical_bytes(copy_record)).hexdigest() != expected: _fail(code, "canonical record hash mismatch")

def seal_snapshot_package(package: dict[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(package)
    artifact = sealed["artifact"]; artifact["artifact_ref"]["content_sha256"] = hashlib.sha256(_canonical_bytes(artifact["content"])).hexdigest()
    digest = artifact["artifact_ref"]["content_sha256"]
    for key, ref_key in (("checkpoint", "approved_artifact_sha256"), ("run", "snapshot_artifact_sha256")):
        sealed[key][ref_key] = digest
    sealed["release"]["artifact_ref"]["content_sha256"] = digest
    for key in ("artifact", "sources", "parses", "claims", "decisions", "conflicts", "checkpoint", "run", "release"):
        if isinstance(sealed[key], list): sealed[key] = [seal_record(item) for item in sealed[key]]
        else: sealed[key] = seal_record(sealed[key])
    return seal_record(sealed)


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


def consume_pinned_source(root: Path, relative_path: str, pinned_sha256: str) -> Path:
    """Reopen the declared ordinary source and require its current byte hash."""
    actual = validate_source_path(root, relative_path)
    if hashlib.sha256(actual.read_bytes()).hexdigest() != _require_hash(pinned_sha256, "SOURCE_HASH_INVALID"):
        _fail("SOURCE_CONTENT_DRIFT", "source bytes differ from immutable pinned hash")
    return actual


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
    _verify_record(package, "PACKAGE_HASH_INVALID")
    project_id = package.get("project_id"); config = _require_hash(package.get("resolved_config_sha256"), "CONFIG_HASH_INVALID")
    artifact = package.get("artifact", {}); ref = artifact.get("artifact_ref", {})
    _verify_record(artifact, "ARTIFACT_RECORD_HASH_INVALID")
    digest = _require_hash(ref.get("content_sha256"), "ARTIFACT_HASH_INVALID")
    if artifact.get("artifact_id") != ref.get("artifact_id") or digest != hashlib.sha256(_canonical_bytes(artifact.get("content"))).hexdigest():
        _fail("ARTIFACT_REF_INVALID", "artifact identity mismatch")
    def indexed(records: list[dict[str, Any]], field: str, code: str) -> dict[str, dict[str, Any]]:
        values = [record.get(field) for record in records]
        if any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
            _fail(code, "duplicate or missing immutable identity")
        return {record[field]: record for record in records}
    sources = indexed(package.get("sources", []), "source_id", "SOURCE_IDENTITY_INVALID")
    parses = indexed(package.get("parses", []), "parse_artifact_id", "PARSE_IDENTITY_INVALID")
    source_enums = {"document_role": {"MAIN", "SI"}, "governance_status": {"INCLUDED", "EXCLUDED"}, "usage_role": {"EVIDENCE", "BACKGROUND", "DISCOVERY_ONLY"}, "availability_status": {"PARSED", "FULL_TEXT_AVAILABLE", "METADATA_ONLY"}, "integrity_status": {"VALIDATED", "QUARANTINED", "UNVERIFIED"}}
    if not sources or not parses or any(_verify_record(source, "SOURCE_RECORD_HASH_INVALID") or source.get("project_id") != project_id or not _require_hash(source.get("content_sha256"), "SOURCE_HASH_INVALID") or any(field in source and source.get(field) not in values for field, values in source_enums.items()) for source in sources.values()):
        _fail("SOURCE_RECORD_INVALID", "source record binding missing")
    for parse in parses.values():
        _verify_record(parse, "PARSE_RECORD_HASH_INVALID")
        if parse.get("project_id") != project_id or parse.get("source_id") not in sources or parse.get("source_content_sha256") != sources[parse["source_id"]].get("content_sha256"):
            _fail("PARSE_ARTIFACT_INVALID", "parse must bind current source hash")
    claims = indexed(package.get("claims", []), "claim_version_id", "CLAIM_IDENTITY_INVALID")
    if not claims: _fail("CLAIM_RECORD_INVALID", "claims required")
    for claim in claims.values(): _verify_record(claim, "CLAIM_RECORD_HASH_INVALID"); _validate_claim(claim, sources, parses)
    decisions = package.get("decisions", [])
    indexed(decisions, "event_id", "DECISION_IDENTITY_INVALID")
    allowed_events = {"EVIDENCE_SUPPORT", "REGISTER", "REJECT", "WITHDRAW", "SUPERSEDE", "CHECKPOINT_APPROVE"}
    states = {key: {"support": "NOT_EVALUATED", "registered": False} for key in claims}
    for event in decisions:
        _verify_record(event, "DECISION_RECORD_HASH_INVALID")
        if event.get("event_type") == "AI_INFERENCE": _fail("AI_INFERENCE_FORBIDDEN", "AI inference cannot register facts")
        if event.get("event_type") not in allowed_events or event.get("claim_version_id") not in states:
            _fail("CLAIM_DECISION_INVALID", "unknown or malformed decision")
        state = states[event["claim_version_id"]]
        if event["event_type"] == "EVIDENCE_SUPPORT":
            if event.get("evidence_support_status") not in {"SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"}: _fail("CLAIM_DECISION_INVALID", "support status invalid")
            state["support"] = event["evidence_support_status"]
        elif event["event_type"] == "REGISTER": state["registered"] = True
    registered_by_lineage: dict[str, int] = {}
    for version_id, state in states.items():
        if state["registered"]:
            lineage = claims[version_id]["claim_id"]; registered_by_lineage[lineage] = registered_by_lineage.get(lineage, 0) + 1
    if any(count > 1 for count in registered_by_lineage.values()): _fail("CLAIM_CURRENT_AMBIGUOUS", "one lineage may have only one registered current version")
    view = _derive_registry_view(list(claims.values()), decisions, list(sources.values()), active_scope_claim_ids={item["claim_id"] for item in claims.values()})
    conflicts = package.get("conflicts", [])
    indexed(conflicts, "conflict_id", "CONFLICT_IDENTITY_INVALID")
    for conflict in conflicts: _verify_record(conflict, "CONFLICT_RECORD_HASH_INVALID"); conflict_compatibility_matrix(conflict)
    for claim_id, claim in claims.items():
        if claim["epistemic_class"] == "REVIEWER_SYNTHESIS":
            deps = claim["supporting_claim_refs"]
            if len(deps) < 2 or any(dep not in view or not view[dep]["writing_eligible"] or claims[dep]["epistemic_class"] == "REVIEWER_SYNTHESIS" for dep in deps): _fail("SUPPORTING_CLAIM_INVALID", "synthesis requires two current eligible material claims")
        if states[claim_id]["registered"] and states[claim_id]["support"] != "SUPPORTED": _fail("CLAIM_REGISTRATION_INVALID", "only supported claim may register")
    for key in ("checkpoint", "run", "release"):
        record = package.get(key, {})
        _verify_record(record, f"{key.upper()}_RECORD_HASH_INVALID")
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
