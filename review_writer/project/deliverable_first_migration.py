"""One-purpose migration for the frozen legacy three-paper deliverable project."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from . import chemical_paper, dual_source, paper_evidence, parse_quality
from . import parse_reconciliation
from .chemical_completion import ChemicalCompletionError, project_chemical_completion_state
from .chemical_paper import ChemicalPaperError, load_chemical_paper_state
from .dual_source import DualSourceError, write_dual_source_binding
from .paper_evidence import (
    PaperEvidenceError,
    apply_paper_evidence_decision,
    paper_evidence_state,
    register_paper_evidence_candidates,
)
from .paper_evidence_store import (
    PaperEvidenceStoreError,
    project_read_lock,
    project_write_lock,
)
from .parse_quality import ParseQualityError, write_parse_quality_gate
from .parse_reconciliation import (
    ParseReconciliationError,
    write_parse_reconciliation,
)
from .source_truth import (
    SOURCE_TRUTH_ROOT,
    SourceTruthError,
    canonical_digest,
    declared_study_ids,
    load_source_truth_bundle,
    write_source_truth_bundle,
)


RECEIPT_PATH = Path("00_sources/acquisition_final_receipt.json")
SOURCE_COVERAGE_PATH = Path("00_sources/source_coverage.json")
INPUT_PROVENANCE_PATH = Path("00_sources/input_provenance_manifest.json")
SI_REGISTRY_PATH = Path("00_sources/si_resource_registry.json")
SI_ACQUISITION_PATH = Path(
    "00_sources/supplements/source-bundle-2026-08-01/si_acquisition_manifest.json"
)
MANUAL_IMPORT_RECEIPT_PATH = Path("00_sources/manual_import_receipt.json")
MINERU_MANIFEST_PATH = Path("01_evidence/mineru/manifest.json")
PARSES_MANIFEST_PATH = Path("01_evidence/parses/manifest.json")
TEXT_LAYERS_MANIFEST_PATH = Path(
    "01_evidence/text_layers/text_layers.manifest.json"
)
DECISIONS_PATH = Path("01_evidence/paper_evidence_decisions.jsonl")
PROJECTION_PATH = Path("01_evidence/paper_evidence_projection.jsonl")
EXPECTED_STUDY_COUNT = 3
EXPECTED_EVIDENCE_COUNT = 9
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ASSET_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
LEGACY_CORPUS_MARKER = {
    "corpus_kind": "legacy_three_paper",
    "variable_n": False,
    "study_count": EXPECTED_STUDY_COUNT,
}
LEGACY_SIMULATED_RESIDUAL_ACTOR = ("human_researcher", "simulated_researcher")


class DeliverableFirstMigrationError(ValueError):
    """Stable, non-sensitive refusal code for this one migration."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _root(project: Path) -> Path:
    supplied = Path(project)
    if supplied.is_symlink() or not supplied.is_dir():
        raise DeliverableFirstMigrationError("PROJECT_INVALID")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise DeliverableFirstMigrationError("PROJECT_INVALID") from exc
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *files):
            if (current_path / name).is_symlink():
                raise DeliverableFirstMigrationError("PROJECT_SYMLINK_UNSAFE")
    return root


def _reject_non_finite_json(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _read_json(path: Path, code: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DeliverableFirstMigrationError(code)
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise DeliverableFirstMigrationError(code) from exc
    if not isinstance(value, dict):
        raise DeliverableFirstMigrationError(code)
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _file_digest(path: Path, code: str) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise DeliverableFirstMigrationError(code)
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise DeliverableFirstMigrationError(code) from exc
    return digest.hexdigest(), size


def _project_file(
    project: Path,
    value: object,
    *,
    code: str,
    allow_sources_prefix: bool = False,
) -> tuple[Path, str]:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DeliverableFirstMigrationError(code)
    if "\\" in value or "\x00" in value or value.startswith("/"):
        raise DeliverableFirstMigrationError(code)
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise DeliverableFirstMigrationError(code)
    if value.startswith("00_sources/"):
        relative = value
    elif allow_sources_prefix and value.startswith("supplements/"):
        relative = f"00_sources/{value}"
    else:
        raise DeliverableFirstMigrationError(code)
    path = project.joinpath(*relative.split("/"))
    try:
        path.relative_to(project)
    except ValueError as exc:
        raise DeliverableFirstMigrationError(code) from exc
    if path.is_symlink() or not path.is_file():
        raise DeliverableFirstMigrationError(code)
    return path, relative


def _pdf_file_digest(path: Path, code: str) -> tuple[str, int]:
    digest, size = _file_digest(path, code)
    try:
        with path.open("rb") as handle:
            magic = handle.read(5)
    except OSError as exc:
        raise DeliverableFirstMigrationError(code) from exc
    if magic != b"%PDF-":
        raise DeliverableFirstMigrationError(code)
    return digest, size


def _require_sha256(value: object, code: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise DeliverableFirstMigrationError(code)
    return value


def _si_generic_identity_bound(
    source_id: object,
    slug: object,
    data_id: object,
) -> bool:
    if not all(isinstance(value, str) for value in (source_id, slug, data_id)):
        return False
    return (
        source_id in slug
        and source_id in data_id
        and (data_id == slug or data_id.endswith(f"-{slug}"))
    )


def _canonical_manifest_digest(value: dict[str, Any], key: str, code: str) -> None:
    digest = value.get(key)
    body = {name: item for name, item in value.items() if name != key}
    if not isinstance(digest, str) or digest != canonical_digest(body):
        raise DeliverableFirstMigrationError(code)


def _normalise_doi(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    result = value.strip().casefold()
    return result or None


def _index_study_rows(
    value: object,
    studies: list[str],
    code: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(studies):
        raise DeliverableFirstMigrationError(code)
    indexed: dict[str, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict):
            raise DeliverableFirstMigrationError(code)
        study_id = row.get("study_id")
        if (
            not isinstance(study_id, str)
            or not study_id
            or study_id in indexed
        ):
            raise DeliverableFirstMigrationError(code)
        indexed[study_id] = row
    if set(indexed) != set(studies):
        raise DeliverableFirstMigrationError(code)
    return indexed


def _validate_si_generic_sidecars(
    project: Path,
    *,
    canonical_pdf: str,
    pdf_sha256: str,
    page_count: int,
    source_id: str,
) -> str:
    expected_pdf = canonical_pdf.removeprefix("00_sources/")
    mineru = _read_json(project / MINERU_MANIFEST_PATH, "SI_GENERIC_BINDING_MISSING")
    completed = mineru.get("completed")
    if not isinstance(completed, list):
        raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")
    matches = [
        row
        for row in completed
        if isinstance(row, dict) and row.get("relative_pdf_path") == expected_pdf
    ]
    if len(matches) != 1:
        raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")
    row = matches[0]
    slug = row.get("slug")
    data_id = row.get("data_id")
    if (
        row.get("state") != "done"
        or not isinstance(slug, str)
        or not slug
        or any(not SAFE_ASSET_PART_RE.fullmatch(part) for part in slug.split("/"))
        or "/" in slug
        or not isinstance(data_id, str)
        or not data_id.strip()
        or not _si_generic_identity_bound(source_id, slug, data_id)
        or row.get("source_pdf_sha256") != pdf_sha256
        or row.get("markdown_copy") != f"markdown/{slug}.md"
    ):
        raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")

    expected_paths = (
        Path("01_evidence/mineru/markdown") / f"{slug}.md",
        Path("01_evidence/mineru/raw_zips") / f"{slug}.zip",
        Path("01_evidence/parses/markdown") / f"{slug}.md",
        Path("01_evidence/parses/extracted") / slug / "full.md",
        Path("01_evidence/parses/extracted") / slug / "layout.json",
    )
    try:
        for relative in expected_paths:
            path = project / relative
            if path.is_symlink() or not path.is_file():
                raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")
        raw_zip = project / expected_paths[1]
        if not zipfile.is_zipfile(raw_zip):
            raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")
        raw_zip_sha256, _ = _file_digest(
            raw_zip, "SI_GENERIC_BINDING_MISSING"
        )
        if raw_zip_sha256 != _require_sha256(
            row.get("raw_zip_sha256"), "SI_GENERIC_BINDING_MISSING"
        ):
            raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")
        canonical_markdown_sha, _ = _file_digest(
            project / expected_paths[0], "SI_GENERIC_BINDING_MISSING"
        )
        full_markdown_sha, _ = _file_digest(
            project / expected_paths[3], "SI_GENERIC_BINDING_MISSING"
        )
        parse_markdown_sha, _ = _file_digest(
            project / expected_paths[2], "SI_GENERIC_BINDING_MISSING"
        )
        if canonical_markdown_sha != full_markdown_sha or canonical_markdown_sha != parse_markdown_sha:
            raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")
    except OSError as exc:
        raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING") from exc

    extracted = project / Path("01_evidence/parses/extracted") / slug
    content_lists = sorted(
        path
        for path in extracted.glob("*_content_list.json")
        if not path.name.endswith("_content_list_v2.json")
    )
    content_lists_v2 = sorted(extracted.glob("*_content_list_v2.json"))
    if (
        len(content_lists) != 1
        or len(content_lists_v2) != 1
        or content_lists[0].is_symlink()
        or content_lists_v2[0].is_symlink()
    ):
        raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")
    try:
        content_v2 = json.loads(
            content_lists_v2[0].read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING") from exc
    if (
        not isinstance(content_v2, list)
        or len(content_v2) != page_count
        or not all(
            isinstance(page, list) and all(isinstance(item, dict) for item in page)
            for page in content_v2
        )
    ):
        raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")

    parses = _read_json(project / PARSES_MANIFEST_PATH, "SI_GENERIC_BINDING_MISSING")
    parse_completed = parses.get("completed")
    if not isinstance(parse_completed, list):
        raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")
    parse_matches = [
        item
        for item in parse_completed
        if isinstance(item, dict) and item.get("relative_pdf_path") == expected_pdf
    ]
    if (
        len(parse_matches) != 1
        or parse_matches[0].get("state") != "done"
        or parse_matches[0].get("data_id") != data_id
        or parse_matches[0].get("slug") != slug
        or parse_matches[0].get("source_pdf_sha256") != pdf_sha256
        or parse_matches[0].get("raw_zip_sha256")
        != row.get("raw_zip_sha256")
        or parse_matches[0].get("full_md") != f"extracted/{slug}/full.md"
        or parse_matches[0].get("extracted_dir") != f"extracted/{slug}"
        or parse_matches[0].get("markdown_copy") != f"markdown/{slug}.md"
        or not _si_generic_identity_bound(
            source_id,
            parse_matches[0].get("slug"),
            parse_matches[0].get("data_id"),
        )
    ):
        raise DeliverableFirstMigrationError("SI_GENERIC_BINDING_MISSING")
    return slug


def _validate_si_text_layer(
    project: Path,
    *,
    pdf_sha256: str,
    page_count: int,
    pdf_name: str,
    main_source_ids: set[str],
    expected_source_id: str,
) -> str:
    manifest = _read_json(
        project / TEXT_LAYERS_MANIFEST_PATH, "SI_TEXT_LAYER_BINDING_MISSING"
    )
    rows = manifest.get("sources")
    if not isinstance(rows, list):
        raise DeliverableFirstMigrationError("SI_TEXT_LAYER_BINDING_MISSING")
    matches = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("pdf_sha256") == pdf_sha256
    ]
    if len(matches) != 1:
        raise DeliverableFirstMigrationError("SI_TEXT_LAYER_BINDING_MISSING")
    row = matches[0]
    text_source_id = row.get("source_id")
    if (
        not isinstance(text_source_id, str)
        or not text_source_id.strip()
        or text_source_id in main_source_ids
        or expected_source_id not in text_source_id
        or row.get("page_count") != page_count
        or row.get("pdf_name") != pdf_name
    ):
        raise DeliverableFirstMigrationError("SI_TEXT_LAYER_BINDING_MISSING")
    for path_key, hash_key in (
        ("reading_order_path", "reading_order_sha256"),
        ("layout_path", "layout_sha256"),
    ):
        value = row.get(path_key)
        if (
            not isinstance(value, str)
            or not value
            or "\\" in value
            or value.startswith("/")
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise DeliverableFirstMigrationError("SI_TEXT_LAYER_BINDING_MISSING")
        path = project / Path("01_evidence/text_layers") / Path(value)
        if path.is_symlink() or not path.is_file():
            raise DeliverableFirstMigrationError("SI_TEXT_LAYER_BINDING_MISSING")
        observed, _ = _file_digest(path, "SI_TEXT_LAYER_BINDING_MISSING")
        if observed != _require_sha256(
            row.get(hash_key), "SI_TEXT_LAYER_BINDING_MISSING"
        ):
            raise DeliverableFirstMigrationError("SI_TEXT_LAYER_BINDING_MISSING")
    if row["reading_order_path"] == row["layout_path"]:
        raise DeliverableFirstMigrationError("SI_TEXT_LAYER_BINDING_MISSING")
    return text_source_id


def _required_si_bindings(
    project: Path,
    *,
    receipt: dict[str, Any],
    studies: list[str],
    bundles: dict[str, dict[str, Any]],
    expected_source_project_id: str,
    main_source_ids: set[str],
) -> dict[str, dict[str, Any]]:
    coverage = _read_json(project / SOURCE_COVERAGE_PATH, "SI_AUTHORITY_MISSING")
    coverage_rows = coverage.get("studies")
    if not isinstance(coverage_rows, list):
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
    coverage_by_study = {
        row.get("study_id"): row
        for row in coverage_rows
        if isinstance(row, dict) and isinstance(row.get("study_id"), str)
    }
    required = [
        study_id
        for study_id in studies
        if coverage_by_study.get(study_id, {}).get("si_policy") == "REQUIRED"
    ]
    if not required:
        return {}
    if sorted(required) != sorted(studies):
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
    if (
        coverage.get("schema_version") != "source-coverage.v1"
        or coverage.get("canonical_artifact") != SOURCE_COVERAGE_PATH.as_posix()
    ):
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
    coverage_by_study = _index_study_rows(
        coverage_rows, studies, "SI_AUTHORITY_INVALID"
    )

    input_manifest = _read_json(
        project / INPUT_PROVENANCE_PATH, "SI_AUTHORITY_MISSING"
    )
    counts = input_manifest.get("counts")
    if (
        input_manifest.get("schema_version") != "input-provenance-manifest.v1"
        or input_manifest.get("project_id") != expected_source_project_id
        or input_manifest.get("status") != "CURRENT"
        or not isinstance(counts, dict)
        or counts.get("si") != len(studies)
    ):
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
    _canonical_manifest_digest(input_manifest, "artifact_digest", "SI_AUTHORITY_INVALID")
    manifest_digest = _require_sha256(
        input_manifest.get("manifest_digest"), "SI_AUTHORITY_INVALID"
    )
    if (
        _require_sha256(coverage.get("manifest_digest"), "SI_AUTHORITY_INVALID")
        != manifest_digest
    ):
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
    manifest_by_study = _index_study_rows(
        input_manifest.get("studies"), studies, "SI_AUTHORITY_INVALID"
    )

    registry = _read_json(project / SI_REGISTRY_PATH, "SI_AUTHORITY_MISSING")
    if (
        registry.get("schema_version") != "si-resource-registry.v1"
        or registry.get("project_id") != expected_source_project_id
        or registry.get("integration_status") != "CURRENT"
        or registry.get("raw_scientific_authority") != "CANDIDATE_ONLY"
        or registry.get("manifest_digest") != input_manifest.get("manifest_digest")
    ):
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
    _canonical_manifest_digest(registry, "registry_digest", "SI_AUTHORITY_INVALID")
    registry_by_study = _index_study_rows(
        registry.get("resources"), studies, "SI_AUTHORITY_INVALID"
    )

    acquisition = _read_json(project / SI_ACQUISITION_PATH, "SI_AUTHORITY_MISSING")
    if acquisition.get("schema_version") != "public-corpus-acquisition.v1":
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
    downloads = acquisition.get("downloads")
    download_by_study = _index_study_rows(
        downloads, studies, "SI_AUTHORITY_INVALID"
    )

    manual = _read_json(
        project / MANUAL_IMPORT_RECEIPT_PATH, "SI_AUTHORITY_MISSING"
    )
    results = manual.get("results")
    if not isinstance(results, list) or manual.get("unresolved") != []:
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
    manual_by_study = _index_study_rows(
        results, studies, "SI_AUTHORITY_INVALID"
    )
    manifest_path = project / SI_ACQUISITION_PATH
    if manual.get("manifest_sha256") != _file_digest(
        manifest_path, "SI_AUTHORITY_INVALID"
    )[0]:
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")

    receipt_rows = _index_study_rows(
        receipt.get("studies"), studies, "ACQUISITION_FINAL_RECEIPT_INVALID"
    )
    bindings: dict[str, dict[str, Any]] = {}
    seen_download_ids: set[str] = set()
    seen_source_ids: set[str] = set()
    for study_id in studies:
        input_row = manifest_by_study.get(study_id)
        registry_row = registry_by_study.get(study_id)
        download = download_by_study.get(study_id)
        imported = manual_by_study.get(study_id)
        receipt_row = receipt_rows.get(study_id)
        if not all(isinstance(row, dict) for row in (input_row, registry_row, download, imported, receipt_row)):
            raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
        source_id = input_row.get("source_id")
        si = input_row.get("si")
        main = receipt_row.get("main_pdf")
        bundle = bundles.get(study_id)
        main_sources = [
            source
            for source in (bundle or {}).get("sources", [])
            if isinstance(source, dict) and source.get("document_role") == "MAIN"
        ]
        input_main = input_row.get("main_pdf")
        if (
            not isinstance(source_id, str)
            or SAFE_ASSET_PART_RE.fullmatch(source_id) is None
            or source_id in seen_source_ids
            or not isinstance(si, dict)
            or not isinstance(main, dict)
            or not isinstance(input_main, dict)
            or len(main_sources) != 1
            or receipt_row.get("source_id") != source_id
            or main.get("sha256") != registry_row.get("main_pdf_sha256")
            or input_main.get("sha256") != main.get("sha256")
            or input_main.get("page_count") != main_sources[0].get("page_count")
            or input_main.get("source_truth_bundle_digest")
            != bundle.get("bundle_digest")
            or main_sources[0].get("source_id") != source_id
            or registry_row.get("source_id") != source_id
            or registry_row.get("document_role") != "SI"
            or registry_row.get("status") != "CURRENT"
            or registry_row.get("authority") != "INPUT_PROVENANCE_ONLY"
            or download.get("document_role") != "SI"
            or imported.get("document_role") != "SI"
            or imported.get("status") != "IMPORTED"
        ):
            raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
        seen_source_ids.add(source_id)
        canonical_path, canonical_relative = _project_file(
            project,
            si.get("path"),
            code="SI_AUTHORITY_INVALID",
        )
        if not canonical_relative.startswith("00_sources/supplements/"):
            raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
        if canonical_path.name != f"{source_id}.pdf":
            raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
        canonical_sha, canonical_size = _pdf_file_digest(
            canonical_path, "SI_AUTHORITY_INVALID"
        )
        expected_sha = _require_sha256(si.get("sha256"), "SI_AUTHORITY_INVALID")
        page_count = si.get("page_count")
        size_bytes = si.get("size_bytes")
        if (
            canonical_sha != expected_sha
            or canonical_size != size_bytes
            or si.get("path") != canonical_relative
            or not isinstance(page_count, int)
            or isinstance(page_count, bool)
            or page_count < 1
            or si.get("status") != "current"
            or input_main.get("sha256") != main.get("sha256")
            or input_row.get("si", {}).get("sha256") != expected_sha
            or input_row.get("si", {}).get("page_count") != page_count
            or input_row.get("si", {}).get("size_bytes") != canonical_size
            or registry_row.get("path") != canonical_relative
            or registry_row.get("sha256") != expected_sha
            or registry_row.get("size_bytes") != canonical_size
            or registry_row.get("page_count") != page_count
        ):
            raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")

        target_path = download.get("target_path")
        alias_path, alias_relative = _project_file(
            project,
            target_path,
            code="SI_AUTHORITY_INVALID",
            allow_sources_prefix=True,
        )
        alias_sha, alias_size = _pdf_file_digest(alias_path, "SI_AUTHORITY_INVALID")
        download_id = download.get("download_id")
        if (
            not isinstance(download_id, str)
            or not download_id
            or download_id in seen_download_ids
            or alias_relative == canonical_relative
            or alias_sha != expected_sha
            or alias_size != canonical_size
            or download.get("expected_sha256") != expected_sha
            or _normalise_doi(download.get("doi"))
            != _normalise_doi(receipt_row.get("doi"))
            or imported.get("download_id") != download_id
            or imported.get("target_path") != alias_relative.removeprefix("00_sources/")
            or imported.get("sha256") != expected_sha
            or imported.get("size_bytes") != canonical_size
        ):
            raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
        seen_download_ids.add(download_id)
        if imported.get("expected_sha256") not in {None, expected_sha}:
            raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")

        slug = _validate_si_generic_sidecars(
            project,
            canonical_pdf=canonical_relative,
            pdf_sha256=expected_sha,
            page_count=page_count,
            source_id=source_id,
        )
        text_source_id = _validate_si_text_layer(
            project,
            pdf_sha256=expected_sha,
            page_count=page_count,
            pdf_name=canonical_path.name,
            main_source_ids=main_source_ids,
            expected_source_id=source_id,
        )
        binding = {
            "path": canonical_relative.removeprefix("00_sources/"),
            "sha256": expected_sha,
            "size_bytes": canonical_size,
            "page_count": page_count,
            "document_role": "SI",
            "source_id": source_id,
            "canonical_path": canonical_relative,
            "alias_paths": [alias_relative],
            "duplicate_paths": [alias_relative],
            "download_id": download_id,
            "generic_slug": slug,
            "text_layer_source_id": text_source_id,
        }
        existing = receipt_row.get("si_pdf")
        if existing is not None and (
            not isinstance(existing, dict)
            or any(existing.get(key) != binding.get(key) for key in ("path", "sha256", "size_bytes", "page_count"))
        ):
            raise DeliverableFirstMigrationError("SI_RECEIPT_BINDING_INVALID")
        bindings[study_id] = binding
    return bindings


def _atomic_replace(project: Path, relative: Path, payload: bytes) -> None:
    target = project / relative
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise OSError("invalid migration output parent")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _actor_pair(value: object) -> tuple[object, object]:
    if not isinstance(value, dict):
        return (None, None)
    return value.get("actor_type"), value.get("actor_label")


def _require_simulated_actor(value: object, code: str) -> None:
    actor_type, actor_label = _actor_pair(value)
    if (
        actor_type != "simulated_researcher_agent"
        or not isinstance(actor_label, str)
        or not actor_label.strip()
    ):
        raise DeliverableFirstMigrationError(code)


def _require_preservable_chemical_actor(value: object) -> None:
    pair = _actor_pair(value)
    if pair == LEGACY_SIMULATED_RESIDUAL_ACTOR:
        return
    _require_simulated_actor(value, "LEGACY_CHEMICAL_ACTOR_NOT_ELIGIBLE")


def _candidate_path(study_id: str) -> Path:
    return Path("01_evidence") / study_id / "paper_evidence_candidates.json"


def _source_bundle_path(study_id: str) -> Path:
    return SOURCE_TRUTH_ROOT / study_id / "bundle.json"


def _parse_gate_path(study_id: str) -> Path:
    return SOURCE_TRUTH_ROOT / study_id / "parse_quality.json"


def _chemical_state_path(study_id: str) -> Path:
    return Path("01_evidence/chemical_paper") / study_id / "state.json"


def _dual_binding_path(study_id: str) -> Path:
    return Path("01_evidence/dual_source") / study_id / "binding.json"


def _reconciliation_path(study_id: str) -> Path:
    return Path("01_evidence/parse_reconciliation") / study_id / "registry.json"


def _affected_paths(studies: list[str]) -> tuple[Path, ...]:
    return (
        RECEIPT_PATH,
        INPUT_PROVENANCE_PATH,
        SOURCE_COVERAGE_PATH,
        DECISIONS_PATH,
        PROJECTION_PATH,
        *(_source_bundle_path(study_id) for study_id in studies),
        *(_parse_gate_path(study_id) for study_id in studies),
        *(_chemical_state_path(study_id) for study_id in studies),
        *(_dual_binding_path(study_id) for study_id in studies),
        *(_reconciliation_path(study_id) for study_id in studies),
        *(_candidate_path(study_id) for study_id in studies),
    )


def _snapshot(project: Path, paths: tuple[Path, ...]) -> dict[Path, bytes | None]:
    result: dict[Path, bytes | None] = {}
    for relative in paths:
        path = project / relative
        if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
            raise DeliverableFirstMigrationError("PROJECT_SYMLINK_UNSAFE")
        result[relative] = path.read_bytes() if path.is_file() else None
    return result


def _static_candidate(candidate: object, study_id: str) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID")
    try:
        paper_evidence._validate_schema(
            candidate,
            paper_evidence.PAPER_EVIDENCE_SCHEMA,
            "PAPER_EVIDENCE_SCHEMA_INVALID",
        )
        paper_evidence._identifier(candidate.get("evidence_id"), "EVIDENCE_ID_INVALID")
        paper_evidence._identifier(candidate.get("source_id"), "SOURCE_ID_INVALID")
        locator = candidate.get("locator")
        if not isinstance(locator, dict):
            raise PaperEvidenceError("LOCATOR_INVALID")
        paper_evidence._normalize_locator(locator, str(locator.get("source_mode")))
    except PaperEvidenceError as exc:
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID") from exc
    if (
        candidate.get("study_id") != study_id
        or candidate.get("decision") is not None
        or paper_evidence._candidate_digest(candidate)
        != candidate.get("candidate_digest")
    ):
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID")
    return copy.deepcopy(candidate)


def _load_static_candidates(project: Path, study_id: str) -> list[dict[str, Any]]:
    payload = _read_json(
        project / _candidate_path(study_id), "LEGACY_EVIDENCE_INVALID"
    )
    if (
        set(payload) != {"schema_version", "study_id", "candidates"}
        or payload.get("schema_version") != "paper-evidence-candidate-set.v1"
        or payload.get("study_id") != study_id
        or not isinstance(payload.get("candidates"), list)
        or not payload["candidates"]
    ):
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID")
    return [_static_candidate(row, study_id) for row in payload["candidates"]]


def _strict_rows(
    bundles: dict[str, dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
    decisions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for study_id in sorted(candidates):
        bundle = bundles[study_id]
        sources = {
            row.get("source_id"): row
            for row in bundle.get("sources", [])
            if isinstance(row, dict) and isinstance(row.get("source_id"), str)
        }
        for candidate in candidates[study_id]:
            evidence_id = candidate["evidence_id"]
            source = sources.get(candidate["source_id"])
            decision = decisions.get(evidence_id)
            locator = candidate.get("locator")
            if (
                not isinstance(source, dict)
                or source.get("document_role") not in {"MAIN", "SI"}
                or not isinstance(source.get("pdf"), dict)
                or source["pdf"].get("sha256")
                != candidate.get("source_pdf_sha256")
                or not isinstance(locator, dict)
                or not isinstance(locator.get("page"), int)
                or isinstance(locator.get("page"), bool)
                or locator["page"] < 1
                or locator["page"] > source.get("page_count", 0)
                or not isinstance(locator.get("section_or_item"), str)
                or not locator["section_or_item"].strip()
                or (
                    locator.get("figure_or_table") is not None
                    and (
                        not isinstance(locator.get("figure_or_table"), str)
                        or not locator["figure_or_table"].strip()
                    )
                )
                or not isinstance(locator.get("exact_quote"), str)
                or not locator["exact_quote"].strip()
                or not isinstance(decision, dict)
            ):
                raise DeliverableFirstMigrationError("STRICT_EVIDENCE_TRACE_INVALID")
            bound_decision = decision.get("decision")
            _require_simulated_actor(
                bound_decision,
                "LEGACY_EVIDENCE_ACTOR_NOT_ELIGIBLE",
            )
            if (
                decision.get("candidate_digest") != candidate["candidate_digest"]
                or decision.get("bound_parse_object_digests")
                != candidate["bound_parse_object_digests"]
                or decision.get("source_pdf_sha256")
                != candidate["source_pdf_sha256"]
                or not isinstance(bound_decision, dict)
                or bound_decision.get("bound_object_digest")
                != candidate["candidate_digest"]
                or bound_decision.get("action") not in {
                    "approve",
                    "revise_and_approve",
                }
            ):
                raise DeliverableFirstMigrationError("STRICT_EVIDENCE_TRACE_INVALID")
            locator_body = {
                "source_id": candidate["source_id"],
                "document_role": source["document_role"],
                "source_pdf_sha256": candidate["source_pdf_sha256"],
                "page": locator["page"],
                "section_or_item": locator["section_or_item"],
                "figure_or_table": locator["figure_or_table"],
            }
            rows.append(
                {
                    "schema_version": "deliverable-first-strict-evidence.v1",
                    "evidence_id": evidence_id,
                    "study_id": study_id,
                    **locator_body,
                    "excerpt_hash": hashlib.sha256(
                        locator["exact_quote"].encode("utf-8")
                    ).hexdigest(),
                    "locator_hash": canonical_digest(locator_body),
                    "decision_actor_type": bound_decision["actor_type"],
                    "decision_actor_label": bound_decision["actor_label"],
                    "decision_action": bound_decision["action"],
                }
            )
    rows.sort(key=lambda row: (row["study_id"], row["evidence_id"]))
    if len(rows) != EXPECTED_EVIDENCE_COUNT:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_COUNT_INVALID")
    return rows


def _latest_decisions(project: Path) -> dict[str, dict[str, Any]]:
    try:
        events = paper_evidence._load_decisions(project)
    except PaperEvidenceError as exc:
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_INVALID") from exc
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        evidence_id = event.get("evidence_id")
        if not isinstance(evidence_id, str) or evidence_id in latest:
            raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_HISTORY_NOT_ELIGIBLE")
        latest[evidence_id] = copy.deepcopy(event)
    return latest


def _static_chain(project: Path, *, expected_source_project_id: str) -> dict[str, Any]:
    if (
        not isinstance(expected_source_project_id, str)
        or not expected_source_project_id.strip()
        or expected_source_project_id != expected_source_project_id.strip()
        or project.name == expected_source_project_id
    ):
        raise DeliverableFirstMigrationError("PROJECT_ID_MIGRATION_INVALID")
    receipt = _read_json(project / RECEIPT_PATH, "ACQUISITION_FINAL_RECEIPT_INVALID")
    marker_keys = set(LEGACY_CORPUS_MARKER)
    present_marker_keys = marker_keys.intersection(receipt)
    if present_marker_keys and (
        present_marker_keys != marker_keys
        or any(receipt.get(key) != value for key, value in LEGACY_CORPUS_MARKER.items())
    ):
        raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_MARKER_NOT_ELIGIBLE")
    studies_value = receipt.get("studies")
    if not isinstance(studies_value, list):
        raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_NOT_ELIGIBLE")
    studies = [
        row.get("study_id") for row in studies_value if isinstance(row, dict)
    ]
    if (
        len(studies) != EXPECTED_STUDY_COUNT
        or len(set(studies)) != EXPECTED_STUDY_COUNT
        or any(not isinstance(study_id, str) or not study_id for study_id in studies)
    ):
        raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_NOT_ELIGIBLE")
    studies = sorted(studies)
    try:
        if sorted(declared_study_ids(project)) != studies:
            raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_NOT_ELIGIBLE")
    except SourceTruthError as exc:
        raise DeliverableFirstMigrationError("LEGACY_THREE_PAPER_NOT_ELIGIBLE") from exc

    bundles: dict[str, dict[str, Any]] = {}
    candidates: dict[str, list[dict[str, Any]]] = {}
    chemical_states: dict[str, dict[str, Any]] = {}
    for study_id in studies:
        try:
            bundle = load_source_truth_bundle(project, study_id)
        except SourceTruthError as exc:
            raise DeliverableFirstMigrationError("LEGACY_SOURCE_TRUTH_INVALID") from exc
        if (
            bundle.get("project_id") != expected_source_project_id
            or bundle.get("study_id") != study_id
        ):
            raise DeliverableFirstMigrationError("LEGACY_SOURCE_TRUTH_NOT_ELIGIBLE")
        bundles[study_id] = copy.deepcopy(bundle)

        gate = _read_json(
            project / _parse_gate_path(study_id), "LEGACY_PARSE_QUALITY_INVALID"
        )
        try:
            parse_quality._validate_gate(gate)
        except ParseQualityError as exc:
            raise DeliverableFirstMigrationError("LEGACY_PARSE_QUALITY_INVALID") from exc
        if gate.get("bundle_digest") != bundle.get("bundle_digest"):
            raise DeliverableFirstMigrationError("LEGACY_PARSE_QUALITY_INVALID")
        for row in gate.get("objects", []):
            if isinstance(row, dict) and row.get("decision") is not None:
                _require_simulated_actor(
                    row["decision"], "LEGACY_PARSE_ACTOR_NOT_ELIGIBLE"
                )

        raw_state = _read_json(
            project / _chemical_state_path(study_id),
            "LEGACY_CHEMICAL_STATE_INVALID",
        )
        try:
            state = chemical_paper._validate_state(raw_state)
        except ChemicalPaperError as exc:
            raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_INVALID") from exc
        if (
            state.get("project_id") != expected_source_project_id
            or state.get("study_id") != study_id
            or state.get("source_truth_bundle_digest") != bundle.get("bundle_digest")
            or len(state.get("imports", {})) != 1
        ):
            raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE")
        for event in state["imports"].values():
            _require_simulated_actor(
                event.get("actor"), "LEGACY_CHEMICAL_ACTOR_NOT_ELIGIBLE"
            )
        for event in [*state["field_corrections"], *state["element_reviews"]]:
            _require_preservable_chemical_actor(event.get("actor"))
        chemical_states[study_id] = state

        binding = _read_json(
            project / _dual_binding_path(study_id), "LEGACY_DUAL_BINDING_INVALID"
        )
        registry = _read_json(
            project / _reconciliation_path(study_id),
            "LEGACY_RECONCILIATION_INVALID",
        )
        try:
            dual_source._validate(binding)
            parse_reconciliation._validate(registry)
        except (DualSourceError, ParseReconciliationError) as exc:
            raise DeliverableFirstMigrationError("LEGACY_DUAL_CHAIN_INVALID") from exc
        if (
            binding.get("project_id") != expected_source_project_id
            or registry.get("project_id") != expected_source_project_id
        ):
            raise DeliverableFirstMigrationError("LEGACY_DUAL_CHAIN_NOT_ELIGIBLE")
        for row in registry.get("objects", []):
            if isinstance(row, dict) and row.get("decision") is not None:
                _require_simulated_actor(
                    row["decision"], "LEGACY_RECONCILIATION_ACTOR_NOT_ELIGIBLE"
                )
        candidates[study_id] = _load_static_candidates(project, study_id)

    main_source_ids = {
        source.get("source_id")
        for bundle in bundles.values()
        for source in bundle.get("sources", [])
        if isinstance(source, dict)
        and source.get("document_role") == "MAIN"
        and isinstance(source.get("source_id"), str)
    }
    si_bindings = _required_si_bindings(
        project,
        receipt=receipt,
        studies=studies,
        bundles=bundles,
        expected_source_project_id=expected_source_project_id,
        main_source_ids=main_source_ids,
    )

    if sum(len(rows) for rows in candidates.values()) != EXPECTED_EVIDENCE_COUNT:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_COUNT_INVALID")
    decisions = _latest_decisions(project)
    candidate_ids = {
        row["evidence_id"] for rows in candidates.values() for row in rows
    }
    if set(decisions) != candidate_ids:
        raise DeliverableFirstMigrationError("LEGACY_EVIDENCE_HISTORY_NOT_ELIGIBLE")
    strict_rows = _strict_rows(bundles, candidates, decisions)
    return {
        "receipt": receipt,
        "studies": studies,
        "bundles": bundles,
        "chemical_states": chemical_states,
        "candidates": candidates,
        "decisions": decisions,
        "strict_rows": strict_rows,
        "si_bindings": si_bindings,
    }


def _rebind_chemical_state(
    state: dict[str, Any],
    *,
    project_id: str,
    source_truth_bundle_digest: str,
) -> dict[str, Any]:
    current = chemical_paper._validate_state(copy.deepcopy(state))
    if len(current["imports"]) != 1:
        raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE")
    old_import_digest = current["current_import_digest"]
    old_import = current["imports"][old_import_digest]
    import_body = {
        key: copy.deepcopy(value)
        for key, value in old_import.items()
        if key
        not in {
            "import_digest",
            "imported_at",
            "actor",
            "prior_import_event_digest",
            "import_event_digest",
        }
    }
    import_body["source_truth_bundle_digest"] = source_truth_bundle_digest
    new_import_digest = canonical_digest(import_body)
    new_import = {
        **import_body,
        "import_digest": new_import_digest,
        "imported_at": old_import["imported_at"],
        "actor": copy.deepcopy(old_import["actor"]),
        "prior_import_event_digest": None,
    }
    new_import["import_event_digest"] = canonical_digest(new_import)

    correction_digest_map: dict[str, str] = {}
    corrections: list[dict[str, Any]] = []
    correction_head: str | None = None
    for old_event in current["field_corrections"]:
        if old_event["bound_import_digest"] != old_import_digest:
            raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE")
        event = copy.deepcopy(old_event)
        event["bound_import_digest"] = new_import_digest
        event["prior_event_digest"] = correction_head
        old_event_digest = event.pop("event_digest")
        event["event_digest"] = canonical_digest(event)
        correction_digest_map[old_event_digest] = event["event_digest"]
        correction_head = event["event_digest"]
        corrections.append(event)

    reviews: list[dict[str, Any]] = []
    review_head: str | None = None
    for old_event in current["element_reviews"]:
        if old_event["bound_import_digest"] != old_import_digest:
            raise DeliverableFirstMigrationError("LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE")
        event = copy.deepcopy(old_event)
        event["bound_import_digest"] = new_import_digest
        event["prior_event_digest"] = review_head
        resolution_digest = event.get("bound_resolution_event_digest")
        if resolution_digest is not None:
            replacement = correction_digest_map.get(resolution_digest)
            if replacement is None:
                raise DeliverableFirstMigrationError(
                    "LEGACY_CHEMICAL_STATE_NOT_ELIGIBLE"
                )
            event["bound_resolution_event_digest"] = replacement
        event.pop("event_digest")
        event["event_digest"] = canonical_digest(event)
        review_head = event["event_digest"]
        reviews.append(event)

    rebound = copy.deepcopy(current)
    rebound.update(
        {
            "project_id": project_id,
            "source_truth_bundle_digest": source_truth_bundle_digest,
            "current_import_digest": new_import_digest,
            "imports": {new_import_digest: new_import},
            "field_corrections": corrections,
            "field_correction_head_digest": correction_head,
            "element_reviews": reviews,
            "element_review_head_digest": review_head,
        }
    )
    rebound["state_digest"] = chemical_paper._canonical_state_digest(rebound)
    try:
        return chemical_paper._validate_state(rebound)
    except ChemicalPaperError as exc:
        raise DeliverableFirstMigrationError("CHEMICAL_REBIND_INVALID") from exc


def _candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    excluded = {"candidate_digest", "decision", "dual_parse_bindings"}
    return {
        key: copy.deepcopy(value)
        for key, value in candidate.items()
        if key not in excluded
    }


def _source_truth_main_semantics(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in bundle.items()
        if key not in {"project_id", "bundle_digest", "sources", "warnings"}
    } | {
        "sources": [
            copy.deepcopy(source)
            for source in bundle.get("sources", [])
            if isinstance(source, dict) and source.get("document_role") == "MAIN"
        ]
    }


def _validate_si_source_truth(
    bundle: dict[str, Any],
    *,
    previous: dict[str, Any],
    binding: dict[str, Any],
) -> None:
    if _source_truth_main_semantics(bundle) != _source_truth_main_semantics(previous):
        raise DeliverableFirstMigrationError("SOURCE_TRUTH_SEMANTICS_CHANGED")
    previous_warnings = previous.get("warnings")
    current_warnings = bundle.get("warnings")
    if (
        not isinstance(previous_warnings, list)
        or not isinstance(current_warnings, list)
        or not set(previous_warnings).issubset(current_warnings)
    ):
        raise DeliverableFirstMigrationError("SOURCE_TRUTH_SEMANTICS_CHANGED")
    sources = bundle.get("sources")
    previous_sources = previous.get("sources")
    if not isinstance(sources, list) or not isinstance(previous_sources, list):
        raise DeliverableFirstMigrationError("SOURCE_TRUTH_REBUILD_FAILED")
    si_sources = [
        source
        for source in sources
        if isinstance(source, dict) and source.get("document_role") == "SI"
    ]
    previous_si_sources = [
        source
        for source in previous_sources
        if isinstance(source, dict) and source.get("document_role") == "SI"
    ]
    if len(si_sources) != 1 or len(previous_si_sources) > 1:
        raise DeliverableFirstMigrationError("SOURCE_TRUTH_SI_BINDING_INVALID")
    source = si_sources[0]
    pdf = source.get("pdf")
    if (
        source.get("source_id") != binding.get("text_layer_source_id")
        or source.get("mineru_slug") != binding.get("generic_slug")
        or not isinstance(pdf, dict)
        or pdf.get("path") != f"00_sources/{binding['path']}"
        or pdf.get("sha256") != binding.get("sha256")
        or pdf.get("size_bytes") != binding.get("size_bytes")
        or source.get("page_count") != binding.get("page_count")
    ):
        raise DeliverableFirstMigrationError("SOURCE_TRUTH_SI_BINDING_INVALID")
    if previous_si_sources:
        previous_source = previous_si_sources[0]
        previous_pdf = previous_source.get("pdf")
        if (
            previous_source.get("source_id") != source.get("source_id")
            or previous_source.get("mineru_slug") != source.get("mineru_slug")
            or not isinstance(previous_pdf, dict)
            or previous_pdf.get("path") != pdf.get("path")
            or previous_pdf.get("sha256") != pdf.get("sha256")
            or previous_pdf.get("size_bytes") != pdf.get("size_bytes")
            or previous_source.get("page_count") != source.get("page_count")
        ):
            raise DeliverableFirstMigrationError("SOURCE_TRUTH_SI_BINDING_INVALID")


def _refresh_si_currentness(
    staging: Path,
    *,
    chain: dict[str, Any],
    rebuilt_bundles: dict[str, dict[str, Any]],
    rebuilt_gates: dict[str, dict[str, Any]],
) -> None:
    if not chain["si_bindings"]:
        return
    input_manifest = _read_json(
        staging / INPUT_PROVENANCE_PATH, "SI_AUTHORITY_MISSING"
    )
    if input_manifest.get("schema_version") != "input-provenance-manifest.v1":
        raise DeliverableFirstMigrationError("SI_CURRENTNESS_REFRESH_INVALID")
    manifest_digest = _require_sha256(
        input_manifest.get("manifest_digest"), "SI_CURRENTNESS_REFRESH_INVALID"
    )
    manifest_rows = input_manifest.get("studies")
    if not isinstance(manifest_rows, list):
        raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
    for row in manifest_rows:
        if not isinstance(row, dict):
            raise DeliverableFirstMigrationError("SI_AUTHORITY_INVALID")
        study_id = row.get("study_id")
        if study_id not in chain["si_bindings"]:
            continue
        bundle = rebuilt_bundles.get(study_id)
        gate = rebuilt_gates.get(study_id)
        if not isinstance(bundle, dict) or not isinstance(gate, dict):
            raise DeliverableFirstMigrationError("SI_CURRENTNESS_REFRESH_INVALID")
        main = row.get("main_pdf")
        generic = row.get("generic_parse")
        if not isinstance(main, dict) or not isinstance(generic, dict):
            raise DeliverableFirstMigrationError("SI_CURRENTNESS_REFRESH_INVALID")
        main["source_truth_bundle_digest"] = bundle["bundle_digest"]
        generic["source_truth_bundle_digest"] = bundle["bundle_digest"]
        generic["parse_gate_digest"] = gate["gate_digest"]
    input_manifest["artifact_digest"] = canonical_digest(
        {
            key: value
            for key, value in input_manifest.items()
            if key != "artifact_digest"
        }
    )
    _atomic_replace(staging, INPUT_PROVENANCE_PATH, _json_bytes(input_manifest))

    coverage_path = staging / SOURCE_COVERAGE_PATH
    if not coverage_path.is_file() or coverage_path.is_symlink():
        raise DeliverableFirstMigrationError("SI_CURRENTNESS_REFRESH_INVALID")
    coverage = _read_json(coverage_path, "SI_CURRENTNESS_REFRESH_INVALID")
    coverage_rows = coverage.get("studies")
    if (
        coverage.get("schema_version") != "source-coverage.v1"
        or coverage.get("canonical_artifact") != SOURCE_COVERAGE_PATH.as_posix()
        or _require_sha256(
            coverage.get("manifest_digest"), "SI_CURRENTNESS_REFRESH_INVALID"
        )
        != manifest_digest
        or not isinstance(coverage_rows, list)
    ):
        raise DeliverableFirstMigrationError("SI_CURRENTNESS_REFRESH_INVALID")
    _index_study_rows(
        coverage_rows,
        chain["studies"],
        "SI_CURRENTNESS_REFRESH_INVALID",
    )
    for row in coverage_rows:
        if not isinstance(row, dict):
            raise DeliverableFirstMigrationError("SI_CURRENTNESS_REFRESH_INVALID")
        study_id = row.get("study_id")
        if study_id not in chain["si_bindings"]:
            continue
        bundle = rebuilt_bundles[study_id]
        gate = rebuilt_gates[study_id]
        generic = row.get("generic_parse")
        if generic is None:
            generic = {}
            row["generic_parse"] = generic
        if not isinstance(generic, dict):
            raise DeliverableFirstMigrationError("SI_CURRENTNESS_REFRESH_INVALID")
        generic["status"] = "current"
        generic["source_truth_bundle_digest"] = bundle["bundle_digest"]
        generic["parse_gate_digest"] = gate["gate_digest"]
    _atomic_replace(staging, SOURCE_COVERAGE_PATH, _json_bytes(coverage))


def _rebuild_staging(staging: Path, chain: dict[str, Any]) -> dict[str, Any]:
    receipt = copy.deepcopy(chain["receipt"])
    receipt.update(LEGACY_CORPUS_MARKER)
    for row in receipt.get("studies", []):
        if not isinstance(row, dict):
            raise DeliverableFirstMigrationError("ACQUISITION_FINAL_RECEIPT_INVALID")
        binding = chain["si_bindings"].get(row.get("study_id"))
        if binding is not None:
            row["si_pdf"] = {
                key: copy.deepcopy(value)
                for key, value in binding.items()
                if key
                not in {
                    "generic_slug",
                    "text_layer_source_id",
                }
            }
    _atomic_replace(staging, RECEIPT_PATH, _json_bytes(receipt))

    rebuilt_bundles: dict[str, dict[str, Any]] = {}
    rebuilt_gates: dict[str, dict[str, Any]] = {}
    for study_id in chain["studies"]:
        previous_bundle = chain["bundles"][study_id]
        try:
            bundle = write_source_truth_bundle(staging, study_id)
        except SourceTruthError as exc:
            raise DeliverableFirstMigrationError("SOURCE_TRUTH_REBUILD_FAILED") from exc
        binding = chain["si_bindings"].get(study_id)
        if binding is None:
            previous_semantics = {
                key: value
                for key, value in previous_bundle.items()
                if key not in {"project_id", "bundle_digest"}
            }
            current_semantics = {
                key: value
                for key, value in bundle.items()
                if key not in {"project_id", "bundle_digest"}
            }
            if previous_semantics != current_semantics:
                raise DeliverableFirstMigrationError("SOURCE_TRUTH_SEMANTICS_CHANGED")
        else:
            _validate_si_source_truth(
                bundle,
                previous=previous_bundle,
                binding=binding,
            )
        rebuilt_bundles[study_id] = bundle
        try:
            gate = write_parse_quality_gate(staging, study_id)
        except ParseQualityError as exc:
            raise DeliverableFirstMigrationError("PARSE_QUALITY_REBUILD_FAILED") from exc
        if not gate.get("workflow_can_continue"):
            raise DeliverableFirstMigrationError("PARSE_QUALITY_REBUILD_INVALID")
        for row in gate.get("objects", []):
            if isinstance(row, dict) and row.get("decision") is not None:
                _require_simulated_actor(
                    row["decision"], "LEGACY_PARSE_ACTOR_NOT_ELIGIBLE"
                )
        rebuilt_gates[study_id] = gate

    _refresh_si_currentness(
        staging,
        chain=chain,
        rebuilt_bundles=rebuilt_bundles,
        rebuilt_gates=rebuilt_gates,
    )

    # Source lookup is project-wide: every bundle must carry the target project
    # identity before any one Chemical state can be validated against the index.
    for study_id in chain["studies"]:
        rebound = _rebind_chemical_state(
            chain["chemical_states"][study_id],
            project_id=staging.name,
            source_truth_bundle_digest=str(
                rebuilt_bundles[study_id]["bundle_digest"]
            ),
        )
        chemical_paper._atomic_json(
            staging / _chemical_state_path(study_id), rebound
        )

    try:
        for study_id in chain["studies"]:
            load_chemical_paper_state(staging, study_id)
        # The fixed-309 completion digest is project-wide, so all three states
        # must be current before any downstream binding is derived.
        for study_id in chain["studies"]:
            write_dual_source_binding(staging, study_id)
        for study_id in chain["studies"]:
            write_parse_reconciliation(staging, study_id)
    except (
        ChemicalPaperError,
        DualSourceError,
        ParseReconciliationError,
    ) as exc:
        raise DeliverableFirstMigrationError("DUAL_CHAIN_REBUILD_FAILED") from exc

    for study_id in chain["studies"]:
        (staging / _candidate_path(study_id)).unlink()
    (staging / DECISIONS_PATH).unlink()
    (staging / PROJECTION_PATH).unlink(missing_ok=True)

    rebound_candidates: dict[str, dict[str, Any]] = {}
    try:
        for study_id in chain["studies"]:
            result = register_paper_evidence_candidates(
                staging,
                study_id,
                {
                    "candidates": [
                        _candidate_payload(row)
                        for row in chain["candidates"][study_id]
                    ]
                },
            )
            rebound_candidates.update(
                {row["evidence_id"]: row for row in result["candidates"]}
            )
        for evidence_id in sorted(rebound_candidates):
            candidate = rebound_candidates[evidence_id]
            old_event = chain["decisions"][evidence_id]
            old_decision = old_event["decision"]
            payload = {
                "evidence_id": evidence_id,
                "candidate_digest": candidate["candidate_digest"],
                "bound_parse_object_digests": candidate[
                    "bound_parse_object_digests"
                ],
                "source_pdf_sha256": candidate["source_pdf_sha256"],
                "action": old_decision["action"],
                "reason": old_decision["reason"],
                "actor_type": old_decision["actor_type"],
                "actor_label": old_decision["actor_label"],
            }
            if old_event.get("replacement_statement") is not None:
                payload["replacement_statement"] = old_event["replacement_statement"]
            apply_paper_evidence_decision(staging, payload)
    except PaperEvidenceError as exc:
        raise DeliverableFirstMigrationError("EVIDENCE_REBUILD_FAILED") from exc

    report = strict_evidence_trace(staging)
    if report["rows"] != chain["strict_rows"]:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_TRACE_CHANGED")
    try:
        chemical = project_chemical_completion_state(staging)
    except ChemicalCompletionError as exc:
        raise DeliverableFirstMigrationError("CHEMICAL_COMPLETION_REBUILD_FAILED") from exc
    if chemical.get("confirmed_count"):
        raise DeliverableFirstMigrationError("CONFIRMED_STATE_CREATED")
    return report


def _link_or_copy(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _restore(project: Path, snapshot: dict[Path, bytes | None]) -> None:
    for relative, payload in snapshot.items():
        path = project / relative
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_replace(project, relative, payload)


def _commit(
    project: Path,
    before: dict[Path, bytes | None],
    after: dict[Path, bytes | None],
) -> None:
    try:
        with project_write_lock(project):
            if _snapshot(project, tuple(before)) != before:
                raise DeliverableFirstMigrationError("MIGRATION_VERSION_CHANGED")
            try:
                for relative, payload in after.items():
                    if payload is None:
                        (project / relative).unlink(missing_ok=True)
                    else:
                        _atomic_replace(project, relative, payload)
            except Exception as exc:
                try:
                    _restore(project, before)
                except Exception as rollback_exc:
                    raise DeliverableFirstMigrationError(
                        "MIGRATION_ROLLBACK_FAILED"
                    ) from rollback_exc
                raise DeliverableFirstMigrationError("MIGRATION_WRITE_FAILED") from exc
    except PaperEvidenceStoreError as exc:
        raise DeliverableFirstMigrationError(exc.code) from exc


def strict_evidence_trace(project: Path) -> dict[str, Any]:
    """Validate current Evidence and return hashes without exposing source excerpts."""

    root = _root(project)
    try:
        state = paper_evidence_state(root)
    except PaperEvidenceError as exc:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_NOT_CURRENT") from exc
    if (
        not state.get("workflow_can_continue")
        or len(state.get("rows", [])) != EXPECTED_EVIDENCE_COUNT
        or any(row.get("status") != "approved" for row in state.get("rows", []))
    ):
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_NOT_CURRENT")
    try:
        studies = sorted(declared_study_ids(root))
        bundles = {
            study_id: load_source_truth_bundle(root, study_id)
            for study_id in studies
        }
    except SourceTruthError as exc:
        raise DeliverableFirstMigrationError("STRICT_EVIDENCE_TRACE_INVALID") from exc
    candidates = {
        study_id: _load_static_candidates(root, study_id) for study_id in studies
    }
    decisions = _latest_decisions(root)
    rows = _strict_rows(bundles, candidates, decisions)
    return {
        "schema_version": "deliverable-first-strict-evidence-trace.v1",
        "evidence_count": len(rows),
        "rows": rows,
        "trace_digest": canonical_digest(rows),
    }


def migrate_legacy_three_paper_project(
    project: Path,
    *,
    expected_source_project_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Atomically rebind one renamed, frozen legacy three-paper project."""

    root = _root(project)
    guard_lock = project_read_lock if dry_run else project_write_lock
    try:
        with guard_lock(root):
            chain = _static_chain(
                root, expected_source_project_id=expected_source_project_id
            )
            affected_paths = _affected_paths(chain["studies"])
            before = _snapshot(root, affected_paths)
    except PaperEvidenceStoreError as exc:
        raise DeliverableFirstMigrationError(exc.code) from exc

    try:
        with tempfile.TemporaryDirectory(
            prefix=".deliverable-first-migration-", dir=root.parent
        ) as temporary:
            staging = Path(temporary) / root.name
            shutil.copytree(root, staging, copy_function=_link_or_copy)
            trace = _rebuild_staging(staging, chain)
            after = _snapshot(staging, affected_paths)
    except DeliverableFirstMigrationError:
        raise
    except (OSError, ValueError) as exc:
        raise DeliverableFirstMigrationError("MIGRATION_REBUILD_FAILED") from exc

    changed_paths = sorted(
        relative.as_posix()
        for relative in affected_paths
        if before[relative] != after[relative]
    )
    report = {
        "status": "DRY_RUN_READY" if dry_run else "MIGRATED",
        "reason_code": (
            "DELIVERABLE_FIRST_LEGACY_MIGRATION_READY"
            if dry_run
            else "DELIVERABLE_FIRST_LEGACY_MIGRATED"
        ),
        "source_project_id": expected_source_project_id,
        "project_id": root.name,
        "study_count": len(chain["studies"]),
        "evidence_count": len(chain["strict_rows"]),
        "strict_evidence_count": trace["evidence_count"],
        "strict_trace_digest": trace["trace_digest"],
        "changed_paths": changed_paths,
    }
    if dry_run:
        return report
    _commit(root, before, after)
    current = strict_evidence_trace(root)
    if current["trace_digest"] != trace["trace_digest"]:
        raise DeliverableFirstMigrationError("MIGRATION_COMMIT_INVALID")
    return report
