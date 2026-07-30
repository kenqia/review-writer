"""Fresh, source-only bootstrap and Generic MinerU binding for dual-parse projects."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from review_writer.project.parse_quality import ParseQualityError, write_parse_quality_gate
from review_writer.project.source_truth import SourceTruthError, write_source_truth_bundle


REPO_ROOT = Path(__file__).resolve().parents[2]
REQUEST_SCHEMA = REPO_ROOT / "schemas/project/dual_parse_bootstrap_request.v1.schema.json"


class DualParseBootstrapError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_input(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and not path.is_symlink()


def _validate_request(request: object) -> dict[str, Any]:
    try:
        schema = json.loads(REQUEST_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DualParseBootstrapError("BOOTSTRAP_SCHEMA_INVALID") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(request), key=lambda error: list(error.path))
    if errors or not isinstance(request, dict):
        raise DualParseBootstrapError("BOOTSTRAP_REQUEST_INVALID")
    rows = request["sources"]
    if len({row["study_id"] for row in rows}) != len(rows):
        raise DualParseBootstrapError("DUPLICATE_STUDY_ID")
    if len({row["source_id"] for row in rows}) != len(rows):
        raise DualParseBootstrapError("DUPLICATE_SOURCE_ID")
    return request


def _validated_sources(request: dict[str, Any]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for row in request["sources"]:
        path = Path(row["pdf_input_path"])
        if not _regular_input(path):
            raise DualParseBootstrapError("SOURCE_PDF_INVALID")
        try:
            prefix = path.read_bytes()[:5]
            observed = _sha256(path)
            size = path.stat().st_size
        except OSError as exc:
            raise DualParseBootstrapError("SOURCE_PDF_INVALID") from exc
        if prefix != b"%PDF-":
            raise DualParseBootstrapError("SOURCE_PDF_INVALID")
        if observed != row["expected_pdf_sha256"]:
            raise DualParseBootstrapError("SOURCE_PDF_HASH_MISMATCH")
        if observed in seen_hashes:
            raise DualParseBootstrapError("DUPLICATE_SOURCE_PDF")
        seen_hashes.add(observed)
        validated.append({**row, "input": path, "sha256": observed, "size_bytes": size})
    return validated


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def bootstrap_dual_parse_project(review_root: Path, request: object) -> Path:
    """Validate every PDF, stage a source-only project, and publish exactly once."""
    normalized = _validate_request(request)
    sources = _validated_sources(normalized)
    review_root = Path(review_root)
    target = review_root / normalized["project_id"]
    if os.path.lexists(target):
        raise DualParseBootstrapError("TARGET_EXISTS")
    review_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=review_root))
    published = False
    try:
        studies: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        identities: list[dict[str, Any]] = []
        for row in sources:
            relative_pdf = f"papers/{row['source_id']}.pdf"
            destination = staging / "00_sources" / relative_pdf
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(row["input"], destination)
            descriptor = {
                "path": relative_pdf,
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
            }
            studies.append({
                "study_id": row["study_id"], "source_id": row["source_id"],
                "doi": row["doi"], "title": row["title"], "tier": row["tier"],
                "document_role": "MAIN", "status": "ACQUIRED", "main_pdf": descriptor,
            })
            candidates.append({
                "candidate_id": row["study_id"], "study_id": row["study_id"],
                "source_id": row["source_id"], "doi": row["doi"], "title": row["title"],
                "tier": row["tier"], "document_role": "MAIN",
            })
            identities.append({
                "candidate_id": row["study_id"], "study_id": row["study_id"],
                "source_id": row["source_id"], "doi": row["doi"], "title": row["title"],
                "document_role": "MAIN", "verdict": "PASS",
            })
        _write_json(staging / "00_brief/review_state.json", {
            "schema_version": "vertical-review-state.v1", "project_id": target.name,
            "brief": normalized["brief"], "current_stage": "source_parse",
            "status": "in_progress", "blockers": [],
            "counts": {"sources": len(sources), "evidence": 0, "claims": 0},
        })
        _write_json(staging / "00_discovery/candidate_pool.json", {
            "schema_version": "candidate-pool.v1", "candidates": candidates,
        })
        _write_json(staging / "00_sources/acquisition_final_receipt.json", {
            "schema_version": "acquisition-final-receipt.v1", "studies": studies,
        })
        _write_json(staging / "00_sources/source_identity_audit.json", {
            "schema_version": "source-identity-audit.v1", "results": identities,
        })
        _write_json(staging / "00_sources/source_coverage.json", {
            "schema_version": "source-coverage.v1",
            "canonical_artifact": "00_sources/source_coverage.json",
            "studies": [
                {
                    "study_id": row["study_id"], "available_roles": ["MAIN"],
                    "main_policy": "REQUIRED", "si_policy": "NOT_REQUIRED",
                    "study_status": "READY",
                }
                for row in sources
            ],
        })
        os.replace(staging, target)
        published = True
        return target
    except DualParseBootstrapError:
        raise
    except OSError as exc:
        raise DualParseBootstrapError("BOOTSTRAP_WRITE_FAILED") from exc
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def bind_generic_parse_outputs(project: Path, mineru_output: Path) -> dict[str, object]:
    """Bind only fresh Generic MinerU output matching current project PDF bytes."""
    project = Path(project).resolve(strict=True)
    output = Path(mineru_output).resolve(strict=True)
    if os.path.lexists(project / "01_evidence"):
        raise DualParseBootstrapError("GENERIC_BINDING_TARGET_EXISTS")
    try:
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DualParseBootstrapError("GENERIC_MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict):
        raise DualParseBootstrapError("GENERIC_MANIFEST_INVALID")
    completed = manifest.get("completed")
    failed = manifest.get("failed")
    if (
        manifest.get("completed_count") != 3
        or manifest.get("failed_count") != 0
        or not isinstance(completed, list)
        or len(completed) != 3
        or failed != []
    ):
        raise DualParseBootstrapError("GENERIC_PARSE_INCOMPLETE")
    settings = manifest.get("settings")
    if not isinstance(settings, dict) or settings.get("language") != "en":
        raise DualParseBootstrapError("GENERIC_SETTINGS_INVALID")
    if settings.get("model_version") != "vlm" or settings.get("enable_formula") is not True or settings.get("enable_table") is not True:
        raise DualParseBootstrapError("GENERIC_SETTINGS_INVALID")
    if settings.get("ocr") is not False:
        raise DualParseBootstrapError("GENERIC_SETTINGS_INVALID")

    try:
        receipt = json.loads((project / "00_sources/acquisition_final_receipt.json").read_text(encoding="utf-8"))
        studies = receipt["studies"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID") from exc
    if not isinstance(studies, list) or len(studies) != 3:
        raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID")
    by_pdf = {}
    for row in completed:
        if not isinstance(row, dict) or row.get("state") != "done":
            raise DualParseBootstrapError("GENERIC_PARSE_INCOMPLETE")
        relative = row.get("relative_pdf_path")
        slug = row.get("slug")
        if not isinstance(relative, str) or not isinstance(slug, str) or not slug or "/" in slug or "\\" in slug:
            raise DualParseBootstrapError("GENERIC_MANIFEST_INVALID")
        key = Path(relative).name
        if key in by_pdf:
            raise DualParseBootstrapError("GENERIC_BINDING_AMBIGUOUS")
        by_pdf[key] = row

    stage_root = Path(tempfile.mkdtemp(prefix=f".{project.name}.generic.", dir=project.parent))
    published = False
    try:
        shutil.copytree(project, stage_root, dirs_exist_ok=True, copy_function=shutil.copy2)
        evidence = stage_root / "01_evidence"
        mineru_root = evidence / "mineru"
        parse_root = evidence / "parses"
        layer_root = evidence / "text_layers"
        mineru_rows: list[dict[str, Any]] = []
        parse_rows: list[dict[str, Any]] = []
        layer_rows: list[dict[str, Any]] = []
        for study in studies:
            descriptor = study.get("main_pdf") if isinstance(study, dict) else None
            source_id = study.get("source_id") if isinstance(study, dict) else None
            study_id = study.get("study_id") if isinstance(study, dict) else None
            if not isinstance(descriptor, dict) or not isinstance(source_id, str) or not isinstance(study_id, str):
                raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID")
            relative_pdf = descriptor.get("path")
            expected_hash = descriptor.get("sha256")
            if not isinstance(relative_pdf, str) or not isinstance(expected_hash, str):
                raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID")
            pdf = project / "00_sources" / relative_pdf
            if _sha256(pdf) != expected_hash:
                raise DualParseBootstrapError("SOURCE_PDF_HASH_MISMATCH")
            row = by_pdf.get(Path(relative_pdf).name)
            if row is None:
                raise DualParseBootstrapError("GENERIC_BINDING_MISSING")
            slug = row["slug"]
            source_extracted = output / "extracted" / slug
            source_markdown = output / "markdown" / f"{slug}.md"
            source_zip = output / "raw_zips" / f"{slug}.zip"
            required = [source_markdown, source_zip, source_extracted / "full.md", source_extracted / "layout.json"]
            if not all(_regular_input(path) for path in required) or not source_extracted.is_dir() or source_extracted.is_symlink():
                raise DualParseBootstrapError("GENERIC_OUTPUT_INVALID")
            for path in source_extracted.rglob("*"):
                if path.is_symlink() or (path.is_file() and not _regular_input(path)):
                    raise DualParseBootstrapError("GENERIC_OUTPUT_INVALID")
            v1 = sorted(path for path in source_extracted.glob("*_content_list.json") if not path.name.endswith("_content_list_v2.json"))
            v2 = sorted(source_extracted.glob("*_content_list_v2.json"))
            if len(v1) != 1 or len(v2) != 1:
                raise DualParseBootstrapError("GENERIC_OUTPUT_INVALID")
            try:
                content_v2 = json.loads(v2[0].read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise DualParseBootstrapError("GENERIC_OUTPUT_INVALID") from exc
            if not isinstance(content_v2, list) or not content_v2 or not all(isinstance(page, list) for page in content_v2):
                raise DualParseBootstrapError("GENERIC_OUTPUT_INVALID")
            page_count = len(content_v2)
            destination_extracted = parse_root / "extracted" / slug
            destination_extracted.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_extracted, destination_extracted, copy_function=shutil.copy2)
            for destination in (mineru_root / "markdown" / f"{slug}.md", parse_root / "markdown" / f"{slug}.md"):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_markdown, destination)
            raw_destination = mineru_root / "raw_zips" / f"{slug}.zip"
            raw_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_zip, raw_destination)
            reading = layer_root / f"{source_id}.reading.txt"
            layout = layer_root / f"{source_id}.layout.txt"
            reading.parent.mkdir(parents=True, exist_ok=True)
            markdown_text = source_markdown.read_text(encoding="utf-8")
            layer_text = markdown_text.rstrip() + "\n" + ("\f" * page_count)
            reading.write_text(layer_text, encoding="utf-8")
            layout.write_text(layer_text, encoding="utf-8")
            layer_rows.append({
                "source_id": source_id, "pdf_name": Path(relative_pdf).name,
                "pdf_sha256": expected_hash, "page_count": page_count,
                "reading_order_path": reading.name, "reading_order_sha256": _sha256(reading),
                "reading_order_method": "generic-mineru-canonical-reading-order",
                "layout_path": layout.name, "layout_sha256": _sha256(layout),
                "layout_method": "generic-mineru-layout-visual-locator-only",
            })
            common = {
                "data_id": row.get("data_id"), "slug": slug, "state": "done",
                "relative_pdf_path": relative_pdf,
                "markdown_copy": f"markdown/{slug}.md",
            }
            mineru_rows.append(common)
            parse_rows.append({
                **common, "full_md": f"extracted/{slug}/full.md",
                "extracted_dir": f"extracted/{slug}",
            })
        if len(by_pdf) != len(studies):
            raise DualParseBootstrapError("GENERIC_BINDING_AMBIGUOUS")
        _write_json(mineru_root / "manifest.json", {
            "schema_version": "mineru-parse-manifest.v1", "settings": settings,
            "completed_count": 3, "failed_count": 0, "completed": mineru_rows, "failed": [],
        })
        _write_json(parse_root / "manifest.json", {
            "schema_version": "mineru-batch-parse.v1", "settings": settings,
            "completed_count": 3, "failed_count": 0, "completed": parse_rows, "failed": [],
        })
        _write_json(layer_root / "text_layers.manifest.json", {
            "schema_version": "pdf-text-layers.v1", "sources": layer_rows,
        })
        for study in studies:
            write_source_truth_bundle(stage_root, study["study_id"])
            write_parse_quality_gate(stage_root, study["study_id"])
        os.replace(evidence, project / "01_evidence")
        published = True
    except DualParseBootstrapError:
        raise
    except (SourceTruthError, ParseQualityError) as exc:
        raise DualParseBootstrapError(exc.code) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DualParseBootstrapError("GENERIC_BINDING_FAILED") from exc
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    return {
        "status": "bound", "completed_count": 3, "failed_count": 0,
        "source_truth_count": 3, "parse_quality_count": 3,
    }
