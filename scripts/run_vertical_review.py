#!/usr/bin/env python3
"""Thin, offline CLI for the authoritative vertical review projection."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import unicodedata
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.acquisition.manifest_identity import normalize_doi  # noqa: E402
from review_writer.acquisition.reusable_library import (  # noqa: E402
    CANONICAL_ARTIFACT as REUSABLE_LIBRARY_AUDIT_ARTIFACT,
    ReusableLibraryError,
    audit_reusable_library,
    reusable_request_set_digest,
    reusable_requests_from_downloads,
)
from review_writer.acquisition.supplement_identity import (  # noqa: E402
    SOURCE_COVERAGE_ARTIFACT,
    SupplementAuditError,
    audit_source_coverage,
)
from review_writer.project.vertical_review import (  # noqa: E402
    VerticalReviewError,
    benchmark_metrics,
    build_risk_packet,
    build_writer_packet,
    initialize_review,
    register_study,
)
from review_writer.project.batch_runner import BatchRunnerError, run_batch  # noqa: E402
from review_writer.delivery.project_release import (  # noqa: E402
    ProjectReleaseError,
    bind_authoritative_draft,
)
from scripts.evidence.build_page_atom_catalog import (  # noqa: E402
    PageCatalogError,
    build_page_atom_catalog,
    validate_catalog_schema,
)
from scripts.evidence.evidence_atom_core import canonical_sealed_job_id, sha256_file  # noqa: E402
from scripts.evidence.validate_evidence_candidate import validate as validate_evidence_candidate  # noqa: E402


CATALOG_SCHEMA = REPO_ROOT / "schemas" / "evidence" / "evidence_atom_catalog.v1.schema.json"
CANDIDATE_SCHEMA = REPO_ROOT / "schemas" / "evidence" / "evidence_candidate.v2.schema.json"
DEFAULT_MINERU_TOKEN_FILE = (
    REPO_ROOT
    / "skills"
    / "mineru-precise-parse-review-writer"
    / "config"
    / "mineru_api_token.txt"
)
MINERU_ORIGIN = "https://mineru.net"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _print_summary(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")),
        file=stream,
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _audit_reusable_library(project: Path) -> dict[str, Any]:
    project = project.resolve()
    manifest_path = project / "00_discovery" / "acquisition_manifest.json"
    requests: list[dict[str, Any]] = []
    if manifest_path.is_file():
        manifest = _load_json(manifest_path)
        downloads = manifest.get("downloads") if isinstance(manifest, dict) else None
        requests = reusable_requests_from_downloads(downloads)

    descriptor_path = project / "00_sources" / "reusable_library_descriptor.json"
    if descriptor_path.is_file():
        descriptor = _load_json(descriptor_path)
        if not isinstance(descriptor, dict):
            raise ValueError("reusable library descriptor must be an object")
        library_root_value = descriptor.get("library_root")
        records = descriptor.get("library_records")
        parser_contract = descriptor.get("required_parser_contract")
        if (
            not isinstance(library_root_value, str)
            or not library_root_value
            or Path(library_root_value).is_absolute()
            or not isinstance(records, list)
            or not isinstance(parser_contract, str)
            or not parser_contract
        ):
            raise ValueError("reusable library descriptor is invalid")
        library_root = (project / library_root_value).resolve()
        try:
            library_root.relative_to(project)
        except ValueError as exc:
            raise ValueError("reusable library root must stay inside the project") from exc
        library_status = "DECLARED"
    else:
        library_root = project
        records = []
        parser_contract = "NOT_DECLARED"
        library_status = "NOT_DECLARED"

    report = audit_reusable_library(
        requests=requests,
        library_root=library_root,
        library_records=records,
        required_parser_contract=parser_contract,
    )
    report["library_status"] = library_status
    _atomic_write_json(project / REUSABLE_LIBRARY_AUDIT_ARTIFACT, report)
    return {
        "command": "audit-reusable-library",
        "library_status": library_status,
        "reusable_count": sum(row["status"] == "REUSABLE" for row in report["results"]),
        "status": "AUDITED",
    }


def _decision_counts(projection: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "approved_claim_count": sum(row.get("decision") == "APPROVED" for row in projection),
        "blocked_claim_count": sum(row.get("decision") == "BLOCKED" for row in projection),
        "human_required_claim_count": sum(
            row.get("decision") == "HUMAN_REQUIRED" for row in projection
        ),
    }


def _preflight_status(
    review_root: Path,
    *,
    mineru_token_file: Path,
    mineru_egress_authorized: bool,
    check_network: bool,
) -> dict[str, Any]:
    existing = review_root.expanduser().resolve(strict=False)
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    token_present = bool(os.environ.get("MINERU_API_TOKEN")) or (
        mineru_token_file.is_file() and mineru_token_file.stat().st_size > 0
    )
    checks: dict[str, str] = {
        "docx_export": "ready" if importlib.util.find_spec("docx") else "missing",
        "image_rendering": "ready" if importlib.util.find_spec("PIL") else "missing",
        "jsonschema": "ready" if importlib.util.find_spec("jsonschema") else "missing",
        "mineru_egress": "authorized" if mineru_egress_authorized else "not_authorized",
        "mineru_parser": "ready"
        if (
            REPO_ROOT
            / "skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py"
        ).is_file()
        else "missing",
        "mineru_token": "present" if token_present else "missing",
        "pdftotext": "ready" if shutil.which("pdftotext") else "missing",
        "review_root": "writable" if existing.is_dir() and os.access(existing, os.W_OK) else "not_writable",
    }
    if check_network and token_present and mineru_egress_authorized:
        try:
            request = urllib.request.Request(MINERU_ORIGIN, method="HEAD")
            with urllib.request.urlopen(request, timeout=10):  # noqa: S310 - fixed HTTPS origin.
                checks["mineru_network"] = "reachable"
        except (OSError, urllib.error.URLError):
            checks["mineru_network"] = "unreachable"
    else:
        checks["mineru_network"] = "not_checked"
    blocking = {
        key: value
        for key, value in checks.items()
        if value in {"missing", "not_authorized", "not_writable", "unreachable"}
    }
    return {
        "checks": checks,
        "command": "preflight",
        "reason_code": "MINERU_PREFLIGHT_BLOCKED" if blocking else "PREFLIGHT_READY",
        "status": "BLOCKED" if blocking else "READY",
    }


def _canonical_r0_report(project: Path, candidate: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    study_id = candidate.get("study_id") if isinstance(candidate, dict) else None
    if (
        not isinstance(study_id, str)
        or not study_id
        or study_id in {".", ".."}
        or "/" in study_id
        or "\\" in study_id
    ):
        raise VerticalReviewError("STUDY_ID_INVALID", "candidate study_id is invalid")
    job_path = project / "01_evidence" / study_id / "sealed_job.json"
    if not job_path.is_file():
        raise VerticalReviewError("R0_JOB_MISSING", "canonical sealed job is missing")
    canonical = validate_evidence_candidate(
        _load_json(job_path),
        candidate,
        project.resolve(),
        _load_json(CANDIDATE_SCHEMA),
    )
    if canonical.get("status") != "R0_PASS":
        raise VerticalReviewError("R0_REJECTED", "candidate failed deterministic grounding validation")
    if supplied != canonical:
        raise VerticalReviewError(
            "R0_REPORT_NOT_CANONICAL",
            "supplied R0 report differs from fresh deterministic validation",
        )
    return canonical


class _PrepareNotReady(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _prepare_block(code: str) -> None:
    raise _PrepareNotReady(code)


def _prepare_manifest(
    project: Path,
    relative: str,
    *,
    missing: str,
    invalid: str,
) -> dict[str, Any]:
    path = project / relative
    if not path.is_file():
        _prepare_block(missing)
    try:
        payload = _load_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _prepare_block(invalid)
    if not isinstance(payload, dict):
        _prepare_block(invalid)
    return payload


def _prepare_rows(payload: dict[str, Any], key: str, invalid: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        _prepare_block(invalid)
    return rows


def _verify_reusable_library_audit(project: Path) -> None:
    audit = _prepare_manifest(
        project,
        REUSABLE_LIBRARY_AUDIT_ARTIFACT,
        missing="REUSABLE_LIBRARY_AUDIT_MISSING",
        invalid="REUSABLE_LIBRARY_AUDIT_INVALID",
    )
    if (
        audit.get("schema_version") != "reusable-library-audit.v1"
        or audit.get("canonical_artifact") != REUSABLE_LIBRARY_AUDIT_ARTIFACT
        or not isinstance(audit.get("required_parser_contract"), str)
        or not audit["required_parser_contract"]
        or audit["required_parser_contract"] != audit["required_parser_contract"].strip()
    ):
        _prepare_block("REUSABLE_LIBRARY_AUDIT_INVALID")
    manifest = _prepare_manifest(
        project,
        "00_discovery/acquisition_manifest.json",
        missing="ACQUISITION_MANIFEST_MISSING",
        invalid="ACQUISITION_MANIFEST_INVALID",
    )
    try:
        requests = reusable_requests_from_downloads(manifest.get("downloads"))
    except ReusableLibraryError:
        _prepare_block("ACQUISITION_MANIFEST_INVALID")
    if audit.get("request_set_digest") != reusable_request_set_digest(requests):
        _prepare_block("REUSABLE_LIBRARY_AUDIT_STALE")
    results = audit.get("results")
    if not isinstance(results, list) or not all(isinstance(row, dict) for row in results):
        _prepare_block("REUSABLE_LIBRARY_AUDIT_INVALID")
    allowed_statuses = {"REUSABLE", "PDF_ONLY", "NOT_REUSABLE", "UNRESOLVED"}
    allowed_match_bases = {"DOI", "PDF_SHA256"}
    result_keys = {
        "assets",
        "document_role",
        "library_id",
        "match_basis",
        "reason",
        "status",
        "study_id",
    }
    derived_asset_keys = {"path", "sha256", "source_pdf_sha256", "parser_contract"}

    def valid_asset(name: str, descriptor: Any) -> bool:
        expected_keys = {"path", "sha256"} if name == "pdf" else derived_asset_keys
        if not isinstance(descriptor, dict) or set(descriptor) != expected_keys:
            return False
        relative = descriptor.get("path")
        sha256 = descriptor.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
        ):
            return False
        if name == "pdf":
            return True
        return (
            isinstance(descriptor.get("source_pdf_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", descriptor["source_pdf_sha256"]) is not None
            and isinstance(descriptor.get("parser_contract"), str)
            and bool(descriptor["parser_contract"])
        )

    for row in results:
        assets = row.get("assets")
        status = row.get("status")
        expected_asset_names = {
            "REUSABLE": {"pdf", "mineru", "text", "atom"},
            "PDF_ONLY": {"pdf"},
            "NOT_REUSABLE": set(),
            "UNRESOLVED": set(),
        }.get(status)
        if (
            set(row) != result_keys
            or not isinstance(row.get("study_id"), str)
            or not row["study_id"]
            or row.get("document_role") not in {"MAIN", "SI"}
            or status not in allowed_statuses
            or row.get("match_basis") not in allowed_match_bases
            or not isinstance(assets, dict)
            or set(assets) != expected_asset_names
            or any(not valid_asset(name, descriptor) for name, descriptor in assets.items())
            or (
                status == "REUSABLE"
                and any(
                    assets[name]["source_pdf_sha256"] != assets["pdf"]["sha256"]
                    or assets[name]["parser_contract"] != audit["required_parser_contract"]
                    for name in ("mineru", "text", "atom")
                )
            )
            or not isinstance(row.get("library_id"), (str, type(None)))
            or row.get("library_id") == ""
            or not isinstance(row.get("reason"), (str, type(None)))
            or (status == "REUSABLE") != (row.get("reason") is None)
        ):
            _prepare_block("REUSABLE_LIBRARY_AUDIT_INVALID")
    expected = {
        (row["study_id"], row["document_role"]): "DOI" if row.get("doi") else "PDF_SHA256"
        for row in requests
    }
    expected_pairs = sorted(expected)
    observed_pairs = sorted((row["study_id"], row["document_role"]) for row in results)
    if observed_pairs != expected_pairs:
        _prepare_block("REUSABLE_LIBRARY_AUDIT_STALE")
    if any(
        row["match_basis"] != expected[(row["study_id"], row["document_role"])]
        for row in results
    ):
        _prepare_block("REUSABLE_LIBRARY_AUDIT_STALE")


def _normalized_title(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        character.casefold() if character.isalnum() else " " for character in normalized
    )
    return re.sub(r"\s+", " ", normalized).strip() or None


def _bound_file(project: Path, root: Path, value: Any, code: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        _prepare_block(code)
    portable = value.strip().replace("\\", "/")
    relative = Path(portable)
    if relative.is_absolute():
        candidate = relative
    elif relative.parts and relative.parts[0] in {
        "00_sources",
        "01_evidence",
    }:
        candidate = project / relative
    else:
        candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        _prepare_block(code)
    if not resolved.is_file():
        _prepare_block(code)
    return resolved


def _receipt_sources(project: Path, study: dict[str, Any]) -> list[dict[str, Any]]:
    main = study.get("main_pdf")
    if study.get("status") != "ACQUIRED":
        _prepare_block("ACQUISITION_STUDY_NOT_ACQUIRED")
    if main is not None and not isinstance(main, dict):
        _prepare_block("ACQUISITION_MAIN_INVALID")
    si_value = study.get("si_pdf")
    if si_value is None:
        supplements = []
    elif isinstance(si_value, dict):
        supplements = [si_value]
    elif isinstance(si_value, list) and all(isinstance(row, dict) for row in si_value):
        supplements = si_value
    else:
        _prepare_block("ACQUISITION_SI_INVALID")
    if any(not isinstance(row.get("path"), str) or not row["path"].strip() for row in supplements):
        _prepare_block("ACQUISITION_SI_INVALID")
    declared = ([] if main is None else [("MAIN", main)]) + [
        ("SI", row) for row in supplements
    ]
    declared = sorted(declared, key=lambda item: (item[0] != "MAIN", str(item[1].get("path"))))
    sources: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for role, row in declared:
        path = _bound_file(project, project / "00_sources", row.get("path"), "ACQUISITION_SOURCE_MISSING")
        if path in seen_paths:
            _prepare_block("ACQUISITION_SOURCE_AMBIGUOUS")
        seen_paths.add(path)
        observed = sha256_file(path)
        expected = row.get("sha256", row.get("pdf_sha256"))
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in expected)
        ):
            _prepare_block("ACQUISITION_SOURCE_HASH_INVALID")
        if expected.lower() != observed:
            _prepare_block("ACQUISITION_SOURCE_HASH_MISMATCH")
        sources.append({"document_role": role, "path": path, "pdf_sha256": expected.lower()})
    return sources


def _source_coverage_for_candidate(
    candidate: dict[str, Any], sources: list[dict[str, Any]]
) -> dict[str, Any]:
    try:
        return audit_source_coverage(
            study_id=candidate.get("candidate_id"),
            available_roles=sorted({source["document_role"] for source in sources}),
            si_policy=candidate.get("si_policy", "NOT_REQUIRED"),
            si_dependent_claim_ids=candidate.get("si_dependent_claim_ids", []),
        )
    except SupplementAuditError:
        _prepare_block("CANDIDATE_SOURCE_POLICY_INVALID")


def _persist_source_coverage(project: Path, coverage: dict[str, Any]) -> None:
    path = project / SOURCE_COVERAGE_ARTIFACT
    studies: list[dict[str, Any]] = []
    if path.exists():
        try:
            existing = _load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            _prepare_block("SOURCE_COVERAGE_INVALID")
        if not isinstance(existing, dict) or existing.get("schema_version") != "source-coverage.v1":
            _prepare_block("SOURCE_COVERAGE_INVALID")
        if isinstance(existing.get("studies"), list):
            studies = existing["studies"]
        elif isinstance(existing.get("study_id"), str):
            studies = [
                {
                    key: value
                    for key, value in existing.items()
                    if key not in {"schema_version", "canonical_artifact"}
                }
            ]
        if not all(isinstance(row, dict) and isinstance(row.get("study_id"), str) for row in studies):
            _prepare_block("SOURCE_COVERAGE_INVALID")
    study_row = {
        key: value
        for key, value in coverage.items()
        if key not in {"schema_version", "canonical_artifact"}
    }
    studies = [row for row in studies if row.get("study_id") != study_row["study_id"]]
    studies.append(study_row)
    _atomic_write_json(
        path,
        {
            "schema_version": "source-coverage.v1",
            "canonical_artifact": SOURCE_COVERAGE_ARTIFACT,
            "studies": sorted(studies, key=lambda row: row["study_id"]),
        },
    )


def _verify_source_identity(
    project: Path,
    *,
    doi: str | None,
    study_id: str,
    title: str | None,
) -> None:
    audit = _prepare_manifest(
        project,
        "00_sources/source_identity_audit.json",
        missing="SOURCE_IDENTITY_AUDIT_MISSING",
        invalid="SOURCE_IDENTITY_AUDIT_INVALID",
    )
    rows = audit.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        _prepare_block("SOURCE_IDENTITY_AUDIT_INVALID")
    if doi is not None:
        matches = [row for row in rows if normalize_doi(row.get("doi")) == doi]
    else:
        matches = [
            row
            for row in rows
            if row.get("study_id") == study_id
            or (title is not None and _normalized_title(row.get("title")) == title)
        ]
    if not matches:
        _prepare_block("SOURCE_IDENTITY_BINDING_MISSING")
    if len(matches) != 1:
        _prepare_block("SOURCE_IDENTITY_AMBIGUOUS")
    verdict = matches[0].get("verdict")
    if verdict == "QUARANTINE":
        _prepare_block("SOURCE_IDENTITY_QUARANTINED")
    if verdict != "PASS":
        _prepare_block("SOURCE_IDENTITY_NOT_PASS")


def _bind_source_layers(project: Path, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mineru_root = project / "01_evidence/mineru"
    mineru = _prepare_manifest(
        project,
        "01_evidence/mineru/manifest.json",
        missing="MINERU_MANIFEST_MISSING",
        invalid="MINERU_MANIFEST_INVALID",
    )
    completed = _prepare_rows(mineru, "completed", "MINERU_MANIFEST_INVALID")
    completed_paths = [
        (_bound_file(project, project / "00_sources", row.get("relative_pdf_path"), "MINERU_MANIFEST_INVALID"), row)
        for row in completed
    ]

    layer_root = project / "01_evidence/text_layers"
    layer_manifest = _prepare_manifest(
        project,
        "01_evidence/text_layers/text_layers.manifest.json",
        missing="TEXT_LAYER_MANIFEST_MISSING",
        invalid="TEXT_LAYER_MANIFEST_INVALID",
    )
    layer_rows = _prepare_rows(layer_manifest, "sources", "TEXT_LAYER_MANIFEST_INVALID")
    bound: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    for source in sources:
        mineru_matches = [row for path, row in completed_paths if path == source["path"]]
        if len(mineru_matches) != 1:
            _prepare_block(
                "MINERU_BINDING_MISSING" if not mineru_matches else "MINERU_BINDING_AMBIGUOUS"
            )
        mineru_row = mineru_matches[0]
        slug = mineru_row.get("slug")
        markdown_value = (
            f"markdown/{slug}.md"
            if isinstance(slug, str)
            and slug
            and "/" not in slug
            and "\\" not in slug
            else mineru_row.get("markdown_copy")
        )
        _bound_file(project, mineru_root, markdown_value, "MINERU_MARKDOWN_MISSING")

        matches = [row for row in layer_rows if row.get("pdf_sha256") == source["pdf_sha256"]]
        if len(matches) != 1:
            _prepare_block(
                "TEXT_LAYER_BINDING_MISSING" if not matches else "TEXT_LAYER_BINDING_AMBIGUOUS"
            )
        row = matches[0]
        source_id = row.get("source_id")
        page_count = row.get("page_count")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in seen_source_ids
            or not isinstance(page_count, int)
            or isinstance(page_count, bool)
            or page_count < 1
        ):
            _prepare_block("TEXT_LAYER_BINDING_INVALID")
        seen_source_ids.add(source_id)
        reading = _bound_file(project, layer_root, row.get("reading_order_path"), "TEXT_LAYER_BINDING_INVALID")
        layout = _bound_file(project, layer_root, row.get("layout_path"), "TEXT_LAYER_BINDING_INVALID")
        if sha256_file(reading) != row.get("reading_order_sha256") or sha256_file(layout) != row.get("layout_sha256"):
            _prepare_block("TEXT_LAYER_HASH_MISMATCH")
        bound.append(
            {
                "document_role": source["document_role"],
                "layout_path": layout.relative_to(project.resolve()).as_posix(),
                "layout_sha256": row["layout_sha256"],
                "page_count": page_count,
                "reading_order_path": reading.relative_to(project.resolve()).as_posix(),
                "reading_order_sha256": row["reading_order_sha256"],
                "source_binary_sha256": source["pdf_sha256"],
                "source_id": source_id,
                "visual_evidence_allowed": False,
            }
        )
    return bound


def _persist_prepare_packet(project: Path, study_id: str, job: dict[str, Any]) -> None:
    evidence_root = project / "01_evidence"
    target = evidence_root / study_id
    stage: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{study_id}.prepare-", dir=evidence_root)
    )
    try:
        job_path = stage / "sealed_job.json"
        catalog_path = stage / "atom_catalog.json"
        _atomic_write_json(job_path, job)
        catalog = build_page_atom_catalog(job_path, project)
        validate_catalog_schema(catalog, _load_json(CATALOG_SCHEMA))
        _atomic_write_json(catalog_path, catalog)
        if target.exists():
            existing = (target / "sealed_job.json", target / "atom_catalog.json")
            if (
                target.is_dir()
                and not target.is_symlink()
                and all(path.is_file() for path in existing)
                and existing[0].read_bytes() == job_path.read_bytes()
                and existing[1].read_bytes() == catalog_path.read_bytes()
            ):
                return
            _prepare_block("PREPARE_OUTPUT_CONFLICT")
        stage.rename(target)
        stage = None
    finally:
        if stage is not None:
            for name in ("sealed_job.json", "atom_catalog.json"):
                (stage / name).unlink(missing_ok=True)
            stage.rmdir()


def _prepare_status(project: Path, study_id: str) -> dict[str, Any]:
    benchmark_metrics(project)
    if (
        not study_id.strip()
        or study_id != study_id.strip()
        or study_id in {".", ".."}
        or "/" in study_id
        or "\\" in study_id
    ):
        raise VerticalReviewError("STUDY_ID_INVALID", "study_id must be nonempty")
    manifest_path = project / "00_discovery" / "acquisition_manifest.json"
    if not manifest_path.is_file():
        return {
            "command": "prepare-study",
            "reason_code": "ACQUISITION_MANIFEST_MISSING",
            "status": "NOT_READY",
            "study_id": study_id,
        }
    try:
        _verify_reusable_library_audit(project)
        pool = _prepare_manifest(
            project,
            "00_discovery/candidate_pool.json",
            missing="CANDIDATE_POOL_MISSING",
            invalid="CANDIDATE_POOL_INVALID",
        )
        candidates = _prepare_rows(pool, "candidates", "CANDIDATE_POOL_INVALID")
        matches = [row for row in candidates if row.get("candidate_id") == study_id]
        if len(matches) != 1:
            _prepare_block("STUDY_NOT_DECLARED" if not matches else "STUDY_ID_AMBIGUOUS")
        candidate = matches[0]
        supplied_doi = candidate.get("doi")
        doi = normalize_doi(supplied_doi)
        title = _normalized_title(candidate.get("title"))
        if supplied_doi not in {None, ""} and doi is None:
            _prepare_block("CANDIDATE_DOI_INVALID")
        if doi is None and title is None:
            _prepare_block("CANDIDATE_IDENTITY_INVALID")

        screening = _prepare_manifest(
            project,
            "00_discovery/screening_decisions.json",
            missing="SCREENING_DECISIONS_MISSING",
            invalid="SCREENING_DECISIONS_INVALID",
        )
        decisions = [
            row
            for row in _prepare_rows(screening, "decisions", "SCREENING_DECISIONS_INVALID")
            if row.get("candidate_id") == study_id
        ]
        if len(decisions) != 1:
            _prepare_block(
                "SCREENING_DECISION_MISSING" if not decisions else "SCREENING_DECISION_AMBIGUOUS"
            )
        if decisions[0].get("disposition") != "INCLUDE_FOR_FULL_TEXT":
            _prepare_block("STUDY_NOT_INCLUDED")

        receipt = _prepare_manifest(
            project,
            "00_sources/acquisition_final_receipt.json",
            missing="ACQUISITION_FINAL_RECEIPT_MISSING",
            invalid="ACQUISITION_FINAL_RECEIPT_INVALID",
        )
        receipt_studies = _prepare_rows(
            receipt, "studies", "ACQUISITION_FINAL_RECEIPT_INVALID"
        )
        if doi is not None:
            studies = [row for row in receipt_studies if normalize_doi(row.get("doi")) == doi]
        else:
            studies = [
                row
                for row in receipt_studies
                if row.get("study_id") == study_id
                or (title is not None and _normalized_title(row.get("title")) == title)
            ]
        if len(studies) != 1:
            _prepare_block("ACQUISITION_DOI_MISSING" if not studies else "ACQUISITION_DOI_AMBIGUOUS")
        sources = _receipt_sources(project, studies[0])
        coverage = _source_coverage_for_candidate(candidate, sources)
        if coverage["study_status"] == "BLOCKED":
            _persist_source_coverage(project, coverage)
            _prepare_block("MAIN_REQUIRED")
        _verify_source_identity(project, doi=doi, study_id=study_id, title=title)
        source_files = _bind_source_layers(project, sources)
        _persist_source_coverage(project, coverage)
        study_identity: dict[str, Any] = {"doi": doi, "study_id": study_id}
        if title is not None:
            study_identity["title"] = candidate["title"].strip()
        semantic_target_contract = {
            "allowed_target_kinds": ["ELIGIBILITY", "REACTION_UNIT", "CLAIM"],
            "denied_claim_ids": coverage["blocked_claim_ids"],
            "policy": "ALLOW_EXCEPT_DECLARED_SI_DEPENDENT_CLAIMS",
        }
        job = {
            "mode": "EVIDENCE_ATOM_SEMANTIC_DECISION_V1",
            "schema_version": "sealed-evidence-extraction-job.v2",
            "semantic_target_contract": semantic_target_contract,
            "source_files": source_files,
            "study": study_identity,
            "target_namespace": "study-"
            + hashlib.sha256(study_id.encode("utf-8")).hexdigest(),
            "visual_crops": [],
        }
        job["job_id"] = canonical_sealed_job_id(job)
        _persist_prepare_packet(project, study_id, job)
    except (_PrepareNotReady, PageCatalogError) as exc:
        return {
            "command": "prepare-study",
            "reason_code": exc.code,
            "status": "NOT_READY",
            "study_id": study_id,
        }
    return {
        "command": "prepare-study",
        "outputs": {
            "atom_catalog": f"01_evidence/{study_id}/atom_catalog.json",
            "sealed_job": f"01_evidence/{study_id}/sealed_job.json",
        },
        "reason_code": "PRE_PROVIDER_PACKET_READY",
        "status": "READY",
        "study_id": study_id,
    }


def _wait_for_state(
    project: Path,
    *,
    expected_status: str,
    expected_stage: str,
    poll_seconds: float,
    timeout_seconds: float | None,
) -> dict[str, str]:
    if (
        not expected_status.strip()
        or not expected_stage.strip()
        or poll_seconds <= 0
        or (timeout_seconds is not None and timeout_seconds <= 0)
    ):
        raise VerticalReviewError(
            "WAIT_STATE_ARGUMENT_INVALID",
            "status, stage, and timing values must be valid",
        )
    state_path = project / "00_brief" / "review_state.json"
    started = time.monotonic()
    while True:
        try:
            state = _load_json(state_path)
        except FileNotFoundError as exc:
            raise VerticalReviewError(
                "WAIT_STATE_FILE_MISSING",
                "review state file does not exist",
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VerticalReviewError(
                "WAIT_STATE_FILE_INVALID",
                "review state file is unreadable",
            ) from exc
        if not isinstance(state, dict):
            raise VerticalReviewError(
                "WAIT_STATE_FILE_INVALID",
                "review state must be a JSON object",
            )
        status = state.get("status")
        stage = state.get("current_stage")
        if status == expected_status and stage == expected_stage:
            return {
                "command": "wait-state",
                "current_stage": expected_stage,
                "status": expected_status,
            }
        elapsed = time.monotonic() - started
        if timeout_seconds is not None and elapsed >= timeout_seconds:
            raise VerticalReviewError(
                "WAIT_STATE_TIMEOUT",
                "review state did not reach the expected status before timeout",
            )
        delay = poll_seconds
        if timeout_seconds is not None:
            delay = min(delay, max(0.0, timeout_seconds - elapsed))
        time.sleep(delay)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline vertical review projection.")
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--review-root", type=Path, required=True)
    preflight.add_argument("--mineru-token-file", type=Path, default=DEFAULT_MINERU_TOKEN_FILE)
    preflight.add_argument("--mineru-egress-authorized", action="store_true")
    preflight.add_argument("--skip-network-check", action="store_true")

    init = commands.add_parser("init")
    init.add_argument("--review-root", type=Path, required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--brief", type=Path, required=True)

    wait = commands.add_parser("wait-state")
    wait.add_argument("--project-dir", type=Path, required=True)
    wait.add_argument("--status", required=True)
    wait.add_argument("--stage", required=True)
    wait.add_argument("--poll-seconds", type=float, default=2.0)
    wait.add_argument("--timeout-seconds", type=float)

    reusable_audit = commands.add_parser("audit-reusable-library")
    reusable_audit.add_argument("--project-dir", type=Path, required=True)

    prepare = commands.add_parser("prepare-study")
    prepare.add_argument("--project-dir", type=Path, required=True)
    prepare.add_argument("--study-id", required=True)

    batch = commands.add_parser("prepare-batch")
    batch.add_argument("--project-dir", type=Path, required=True)
    batch.add_argument("--study-ids-file", type=Path, required=True)

    run = commands.add_parser("run-batch")
    run.add_argument("--project-dir", type=Path, required=True)
    run.add_argument("--study-ids-file", type=Path, required=True)
    run.add_argument("--credits-before", type=int)
    run.add_argument("--credits-after", type=int)
    run.add_argument("--forecast-credits", type=float)

    register = commands.add_parser("register-study")
    register.add_argument("--project-dir", type=Path, required=True)
    register.add_argument("--candidate", type=Path, required=True)
    register.add_argument("--r0-report", type=Path, required=True)
    register.add_argument("--reviewer", type=Path, required=True)

    risk = commands.add_parser("build-risk-packet")
    risk.add_argument("--project-dir", type=Path, required=True)

    writer = commands.add_parser("build-writer-packet")
    writer.add_argument("--project-dir", type=Path, required=True)

    bind = commands.add_parser("bind-draft")
    bind.add_argument("--project-dir", type=Path, required=True)
    bind.add_argument("--manuscript", type=Path, required=True)
    bind.add_argument("--lineage", type=Path, required=True)

    metrics = commands.add_parser("metrics")
    metrics.add_argument("--project-dir", type=Path, required=True)
    metrics.add_argument("--output", type=Path, required=True)
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "preflight":
        summary = _preflight_status(
            args.review_root,
            mineru_token_file=args.mineru_token_file,
            mineru_egress_authorized=args.mineru_egress_authorized,
            check_network=not args.skip_network_check,
        )
        _print_summary(summary)
        return 0 if summary["status"] == "READY" else 3
    if args.command == "init":
        project = initialize_review(args.review_root, args.project_id, _load_json(args.brief))
        state = _load_json(project / "00_brief" / "review_state.json")
        _print_summary(
            {"command": "init", "project_dir": str(project), "status": state["status"]}
        )
        return 0
    if args.command == "wait-state":
        _print_summary(
            _wait_for_state(
                args.project_dir,
                expected_status=args.status,
                expected_stage=args.stage,
                poll_seconds=args.poll_seconds,
                timeout_seconds=args.timeout_seconds,
            )
        )
        return 0
    if args.command == "audit-reusable-library":
        _print_summary(_audit_reusable_library(args.project_dir))
        return 0
    if args.command == "prepare-study":
        summary = _prepare_status(args.project_dir, args.study_id)
        _print_summary(summary)
        return 0 if summary["status"] == "READY" else 3
    if args.command == "prepare-batch":
        study_ids = [line.strip() for line in args.study_ids_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not study_ids or len(study_ids) != len(set(study_ids)):
            raise VerticalReviewError(
                "STUDY_IDS_INVALID",
                "study IDs must be nonempty and unique",
            )
        studies = [_prepare_status(args.project_dir, study_id) for study_id in study_ids]
        ready_count = sum(row["status"] == "READY" for row in studies)
        summary = {
            "command": "prepare-batch",
            "not_ready_count": len(studies) - ready_count,
            "ready_count": ready_count,
            "status": "READY" if ready_count == len(studies) else "NOT_READY",
            "studies": [
                {key: row[key] for key in ("outputs", "reason_code", "status", "study_id") if key in row}
                for row in studies
            ],
        }
        _print_summary(summary)
        return 0 if summary["status"] == "READY" else 3
    if args.command == "run-batch":
        study_ids = [
            line.strip()
            for line in args.study_ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        summary = run_batch(
            args.project_dir,
            study_ids,
            prepare_study=lambda study_id: _prepare_status(args.project_dir, study_id),
            credits_before=args.credits_before,
            credits_after=args.credits_after,
            forecast_credits=args.forecast_credits,
        )
        _print_summary(summary)
        return 0 if summary["status"] == "COMPLETE" else 3
    if args.command == "register-study":
        candidate = _load_json(args.candidate)
        r0_report = _canonical_r0_report(
            args.project_dir,
            candidate,
            _load_json(args.r0_report),
        )
        result = register_study(
            args.project_dir,
            candidate,
            r0_report,
            _load_json(args.reviewer),
        )
        summary = {
            "command": "register-study",
            "status": "REGISTERED",
            "study_id": result["study_id"],
            **_decision_counts(result["claim_projection"]),
        }
        _print_summary(summary)
        return 0
    if args.command == "build-risk-packet":
        packet = build_risk_packet(args.project_dir)
        _print_summary(
            {
                "command": "build-risk-packet",
                "human_required_count": packet["human_required_count"],
                "low_risk_sample_count": packet["low_risk_sample_count"],
                "status": "BUILT",
                "target_count": packet["target_count"],
            }
        )
        return 0
    if args.command == "build-writer-packet":
        packet = build_writer_packet(args.project_dir)
        _print_summary(
            {
                "approved_claim_count": packet["approved_claim_count"],
                "blocked_count": packet["blocked_count"],
                "command": "build-writer-packet",
                "human_required_count": packet["human_required_count"],
                "status": "BUILT",
            }
        )
        return 0
    if args.command == "bind-draft":
        result = bind_authoritative_draft(
            args.project_dir,
            args.manuscript,
            args.lineage,
        )
        _print_summary({"command": "bind-draft", "status": "BOUND", **result})
        return 0
    if args.command == "metrics":
        project = args.project_dir.resolve()
        output = args.output.resolve()
        try:
            output.relative_to(project)
        except ValueError:
            pass
        else:
            raise VerticalReviewError(
                "METRICS_OUTPUT_INSIDE_PROJECT",
                "metrics output must remain outside project persistence",
            )
        metrics = benchmark_metrics(args.project_dir)
        _atomic_write_json(args.output, metrics)
        _print_summary({"command": "metrics", "status": "WRITTEN", **metrics})
        return 0
    raise VerticalReviewError("COMMAND_INVALID", "unsupported command")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (BatchRunnerError, VerticalReviewError) as exc:
        payload: dict[str, Any] = {
            "command": args.command,
            "error_code": exc.code,
            "status": "ERROR",
        }
        if exc.code == "WAIT_STATE_TIMEOUT":
            payload.update(
                {
                    "project_saved": True,
                    "resume_instruction": "完成工作台操作后，在 QoderWork 发送“继续当前综述项目”。",
                }
            )
        _print_summary(
            payload,
            stream=sys.stderr,
        )
        return 2
    except ProjectReleaseError as exc:
        _print_summary(
            {"command": args.command, "error_code": exc.code, "status": "ERROR"},
            stream=sys.stderr,
        )
        return 2
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        _print_summary(
            {"command": args.command, "error_code": "INPUT_OR_IO_INVALID", "status": "ERROR"},
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
