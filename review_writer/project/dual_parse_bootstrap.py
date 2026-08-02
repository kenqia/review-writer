"""Fresh, source-only bootstrap and Generic MinerU binding for dual-parse projects."""

from __future__ import annotations

import hashlib
import json
import os
import re
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


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CANONICAL_ANCHOR_DIRECTORY = ".dual_parse_authority"
CANONICAL_ANCHOR_SCHEMA_VERSION = "dual-parse-canonical-anchor.v1"
ACQUISITION_RECEIPT_RELATIVE_PATH = "00_sources/acquisition_final_receipt.json"
CANONICAL_ANCHOR_KEYS = frozenset(
    {
        "schema_version",
        "project_id",
        "project_relative_path",
        "receipt_relative_path",
        "receipt",
        "receipt_sha256",
        "anchor_digest",
    }
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _lexical_absolute(path: Path) -> Path:
    """Return an absolute path without resolving any symlink component."""
    return Path(os.path.abspath(os.fspath(path)))


def _safe_existing_path(path: Path, code: str, *, directory: bool) -> Path:
    lexical = _lexical_absolute(path)
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise DualParseBootstrapError(code) from exc
        if stat.S_ISLNK(mode):
            raise DualParseBootstrapError(code)
        if current != lexical and not stat.S_ISDIR(mode):
            raise DualParseBootstrapError(code)
    try:
        mode = lexical.lstat().st_mode
    except OSError as exc:
        raise DualParseBootstrapError(code) from exc
    if directory and not stat.S_ISDIR(mode):
        raise DualParseBootstrapError(code)
    if not directory and not stat.S_ISREG(mode):
        raise DualParseBootstrapError(code)
    return lexical


def _ensure_safe_directory(path: Path, code: str) -> Path:
    lexical = _lexical_absolute(path)
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            try:
                current.mkdir()
            except OSError as exc:
                raise DualParseBootstrapError(code) from exc
            mode = current.lstat().st_mode
        except OSError as exc:
            raise DualParseBootstrapError(code) from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise DualParseBootstrapError(code)
    return lexical


def _safe_project_path(
    project: Path, relative: Path, code: str, *, directory: bool
) -> Path:
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise DualParseBootstrapError(code)
    root = _safe_existing_path(project, code, directory=True)
    return _safe_existing_path(root.joinpath(*relative.parts), code, directory=directory)


def _canonical_anchor_path(project: Path) -> Path:
    return project.parent / CANONICAL_ANCHOR_DIRECTORY / f"{project.name}.json"


def _canonical_anchor_body(project: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": CANONICAL_ANCHOR_SCHEMA_VERSION,
        "project_id": project.name,
        "project_relative_path": project.name,
        "receipt_relative_path": ACQUISITION_RECEIPT_RELATIVE_PATH,
        "receipt": receipt,
        "receipt_sha256": _canonical_digest(receipt),
    }


def _path_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    return info.st_dev, info.st_ino


def _write_json_exclusive(path: Path, value: object, code: str) -> tuple[int, int]:
    temporary: Path | None = None
    anchor_identity: tuple[int, int] | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        anchor_identity = _path_identity(path)
        return anchor_identity
    except OSError as exc:
        if anchor_identity is not None:
            try:
                if _path_identity(path) == anchor_identity:
                    path.unlink()
            except OSError:
                pass
        raise DualParseBootstrapError(code) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _remove_owned_anchor(path: Path, expected_identity: tuple[int, int]) -> None:
    """Remove our anchor without unlinking a competing replacement."""
    try:
        if _path_identity(path) != expected_identity:
            return
    except OSError:
        return

    quarantine: Path | None = None
    try:
        descriptor, quarantine_name = tempfile.mkstemp(
            prefix=f".{path.name}.rollback.", dir=path.parent
        )
        os.close(descriptor)
        quarantine = Path(quarantine_name)
        quarantine.unlink()
        os.rename(path, quarantine)
        moved_identity = _path_identity(quarantine)
        if moved_identity == expected_identity:
            quarantine.unlink()
            quarantine = None
            return
        try:
            os.link(quarantine, path)
        except FileExistsError:
            if _path_identity(path) != moved_identity:
                return
        quarantine.unlink()
        quarantine = None
    except OSError:
        return
    finally:
        if quarantine is not None:
            try:
                if _path_identity(quarantine) == expected_identity:
                    quarantine.unlink()
            except OSError:
                pass


def _read_canonical_anchor(project: Path) -> dict[str, Any]:
    path = _safe_existing_path(
        _canonical_anchor_path(project),
        "ACQUISITION_FINAL_RECEIPT_INVALID",
        directory=False,
    )
    try:
        anchor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID") from exc
    if (
        not isinstance(anchor, dict)
        or set(anchor) != CANONICAL_ANCHOR_KEYS
        or anchor.get("schema_version") != CANONICAL_ANCHOR_SCHEMA_VERSION
        or anchor.get("project_id") != project.name
        or anchor.get("project_relative_path") != project.name
        or anchor.get("receipt_relative_path") != ACQUISITION_RECEIPT_RELATIVE_PATH
        or not isinstance(anchor.get("receipt"), dict)
        or not isinstance(anchor.get("receipt_sha256"), str)
        or SHA256_RE.fullmatch(anchor["receipt_sha256"]) is None
        or not isinstance(anchor.get("anchor_digest"), str)
        or SHA256_RE.fullmatch(anchor["anchor_digest"]) is None
    ):
        raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID")
    body = {key: value for key, value in anchor.items() if key != "anchor_digest"}
    if (
        anchor["receipt_sha256"] != _canonical_digest(anchor["receipt"])
        or anchor["anchor_digest"] != _canonical_digest(body)
    ):
        raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID")
    return anchor


def _read_bound_receipt(project: Path) -> dict[str, Any]:
    receipt_path = _safe_project_path(
        project,
        Path(ACQUISITION_RECEIPT_RELATIVE_PATH),
        "ACQUISITION_FINAL_RECEIPT_INVALID",
        directory=False,
    )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID") from exc
    if not isinstance(receipt, dict):
        raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID")
    return receipt


def _validate_bound_receipt(receipt: dict[str, Any], anchor: dict[str, Any]) -> None:
    if (
        receipt != anchor["receipt"]
        or _canonical_digest(receipt) != anchor["receipt_sha256"]
    ):
        raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID")


def _generic_source_pdf_sha256(row: dict[str, Any]) -> str:
    source_pdf_sha256 = row.get("source_pdf_sha256")
    pdf_sha256 = row.get("pdf_sha256")
    if (
        not isinstance(source_pdf_sha256, str)
        or SHA256_RE.fullmatch(source_pdf_sha256) is None
        or (
            "pdf_sha256" in row
            and (
                not isinstance(pdf_sha256, str)
                or SHA256_RE.fullmatch(pdf_sha256) is None
                or pdf_sha256 != source_pdf_sha256
            )
        )
    ):
        raise DualParseBootstrapError("GENERIC_SOURCE_BINDING_INVALID")
    return source_pdf_sha256


def _validate_generic_source_bindings(
    project: Path,
    studies: list[dict[str, Any]],
    by_pdf: dict[str, dict[str, Any]],
) -> None:
    """Validate current project PDFs and Generic provenance before staging."""
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
        pdf = _safe_project_path(
            project,
            Path("00_sources") / relative_pdf,
            "ACQUISITION_FINAL_RECEIPT_INVALID",
            directory=False,
        )
        if _sha256(pdf) != expected_hash:
            raise DualParseBootstrapError("SOURCE_PDF_HASH_MISMATCH")
        row = by_pdf.get(Path(relative_pdf).name)
        if row is None:
            raise DualParseBootstrapError("GENERIC_BINDING_MISSING")
        if _generic_source_pdf_sha256(row) != expected_hash:
            raise DualParseBootstrapError("GENERIC_SOURCE_PDF_HASH_MISMATCH")


def _regular_input(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and not path.is_symlink()


def _regular_external_input(path: Path) -> bool:
    """Reject symlinks and non-regular components in an external PDF path."""
    try:
        if path.is_absolute():
            current = Path(path.anchor)
            components = path.parts[1:]
        else:
            current = Path.cwd()
            components = path.parts
        if not components:
            return False
        root_mode = current.lstat().st_mode
        if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
            return False
        for index, component in enumerate(components):
            current /= component
            mode = current.lstat().st_mode
            if stat.S_ISLNK(mode):
                return False
            if index == len(components) - 1:
                return stat.S_ISREG(mode) and os.access(current, os.R_OK)
            if not stat.S_ISDIR(mode):
                return False
    except (OSError, ValueError):
        return False
    return False


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
        if not _regular_external_input(path):
            raise DualParseBootstrapError("SOURCE_PDF_INVALID")
        try:
            prefix = path.read_bytes()[:5]
        except OSError as exc:
            raise DualParseBootstrapError("SOURCE_PDF_INVALID") from exc
        if not _regular_external_input(path):
            raise DualParseBootstrapError("SOURCE_PDF_INVALID")
        try:
            observed = _sha256(path)
        except OSError as exc:
            raise DualParseBootstrapError("SOURCE_PDF_INVALID") from exc
        if not _regular_external_input(path):
            raise DualParseBootstrapError("SOURCE_PDF_INVALID")
        try:
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
    anchor_path = _canonical_anchor_path(target)
    authority_directory = anchor_path.parent
    authority_directory_preexisting = os.path.lexists(authority_directory)
    authority_directory_created = False
    anchor_identity: tuple[int, int] | None = None
    try:
        studies: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        identities: list[dict[str, Any]] = []
        for row in sources:
            relative_pdf = f"papers/{row['source_id']}.pdf"
            destination = staging / "00_sources" / relative_pdf
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not _regular_external_input(row["input"]):
                raise DualParseBootstrapError("SOURCE_PDF_INVALID")
            try:
                shutil.copy2(row["input"], destination)
            except OSError as exc:
                if not _regular_external_input(row["input"]):
                    raise DualParseBootstrapError("SOURCE_PDF_INVALID") from exc
                raise
            try:
                copied_sha256 = _sha256(destination)
                copied_size_bytes = destination.stat().st_size
            except OSError as exc:
                raise DualParseBootstrapError("BOOTSTRAP_WRITE_FAILED") from exc
            if copied_sha256 != row["sha256"] or copied_size_bytes != row["size_bytes"]:
                raise DualParseBootstrapError("SOURCE_PDF_HASH_MISMATCH")
            descriptor = {
                "path": relative_pdf,
                "sha256": copied_sha256,
                "size_bytes": copied_size_bytes,
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
        receipt = {
            "schema_version": "acquisition-final-receipt.v1", "studies": studies,
        }
        _write_json(staging / ACQUISITION_RECEIPT_RELATIVE_PATH, receipt)
        _write_json(staging / "00_sources/source_identity_audit.json", {
            "schema_version": "source-identity-audit.v1", "results": identities,
        })
        _write_json(staging / "00_sources/source_coverage.json", {
            "schema_version": "source-coverage.v1",
            "canonical_artifact": "00_sources/source_coverage.json",
            "studies": [
                {
                    "study_id": row["study_id"], "available_roles": ["MAIN"],
                    "main_policy": "REQUIRED",
                    "si_policy": "REQUIRED" if row["tier"] == "core" else "NOT_REQUIRED",
                    "study_status": "PARTIAL" if row["tier"] == "core" else "READY",
                    "blocked_claim_ids": [],
                    "blocking_reasons": (
                        ["SI_REQUIRED_FOR_DECLARED_CLAIMS"]
                        if row["tier"] == "core" else []
                    ),
                    "limitations": [],
                }
                for row in sources
            ],
        })
        _ensure_safe_directory(authority_directory, "BOOTSTRAP_WRITE_FAILED")
        authority_directory_created = not authority_directory_preexisting
        if os.path.lexists(anchor_path):
            raise DualParseBootstrapError("TARGET_EXISTS")
        anchor_body = _canonical_anchor_body(target, receipt)
        anchor_identity = _write_json_exclusive(
            anchor_path,
            {**anchor_body, "anchor_digest": _canonical_digest(anchor_body)},
            "BOOTSTRAP_WRITE_FAILED",
        )
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
            if anchor_identity is not None:
                _remove_owned_anchor(anchor_path, anchor_identity)
            if authority_directory_created:
                try:
                    authority_directory.rmdir()
                except OSError:
                    pass


def bind_generic_parse_outputs(project: Path, mineru_output: Path) -> dict[str, object]:
    """Bind only fresh Generic MinerU output matching current project PDF bytes."""
    project = _safe_existing_path(
        Path(project), "ACQUISITION_FINAL_RECEIPT_INVALID", directory=True
    )
    output = Path(mineru_output).resolve(strict=True)
    if os.path.lexists(project / "01_evidence"):
        raise DualParseBootstrapError("GENERIC_BINDING_TARGET_EXISTS")
    anchor = _read_canonical_anchor(project)
    receipt = _read_bound_receipt(project)
    studies = receipt.get("studies")
    if not isinstance(studies, list) or len(studies) != 3:
        raise DualParseBootstrapError("ACQUISITION_FINAL_RECEIPT_INVALID")
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

    by_pdf = {}
    for row in completed:
        if not isinstance(row, dict) or row.get("state") != "done":
            raise DualParseBootstrapError("GENERIC_PARSE_INCOMPLETE")
        relative = row.get("relative_pdf_path")
        slug = row.get("slug")
        if not isinstance(relative, str) or not isinstance(slug, str) or not slug or "/" in slug or "\\" in slug:
            raise DualParseBootstrapError("GENERIC_MANIFEST_INVALID")
        _generic_source_pdf_sha256(row)
        key = Path(relative).name
        if key in by_pdf:
            raise DualParseBootstrapError("GENERIC_BINDING_AMBIGUOUS")
        by_pdf[key] = row

    _validate_generic_source_bindings(project, studies, by_pdf)
    _validate_bound_receipt(receipt, anchor)

    staging_parent = Path(
        tempfile.mkdtemp(prefix=f".{project.name}.generic.", dir=project.parent)
    )
    stage_root = staging_parent / project.name
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
            pdf = _safe_project_path(
                project,
                Path("00_sources") / relative_pdf,
                "ACQUISITION_FINAL_RECEIPT_INVALID",
                directory=False,
            )
            if _sha256(pdf) != expected_hash:
                raise DualParseBootstrapError("SOURCE_PDF_HASH_MISMATCH")
            row = by_pdf.get(Path(relative_pdf).name)
            if row is None:
                raise DualParseBootstrapError("GENERIC_BINDING_MISSING")
            if _generic_source_pdf_sha256(row) != expected_hash:
                raise DualParseBootstrapError("GENERIC_SOURCE_PDF_HASH_MISMATCH")
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
                "source_pdf_sha256": expected_hash,
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
        shutil.rmtree(staging_parent, ignore_errors=True)
    return {
        "status": "bound", "completed_count": 3, "failed_count": 0,
        "source_truth_count": 3, "parse_quality_count": 3,
    }
