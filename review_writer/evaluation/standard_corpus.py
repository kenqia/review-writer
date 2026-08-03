"""Read-only validation for the archived external review benchmark corpus."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas/quality/standard_corpus_manifest.v1.schema.json"
MANIFEST_NAME = "standard_corpus_manifest.json"
REVIEW_SLUGS = (
    "angew-chem-int-ed-2018-marzo-visiblelight-photocatalysis-does-it-make-a-difference-in-organic-synthesis",
    "cr300503r",
    "cr6b00018",
    "cr6b00057",
    "d3gc03291d",
    "d5cs00181a",
    "d5cs00670h",
    "s41570-017-0052",
)
GUIDE_SLUGS = (
    "chreay_authguide",
    "natrev-articleformatguide-perspective",
    "natrev-articleformatguide-review",
    "natrev-artworkguide_ps",
    "nr-chemical-structures-guide",
    "writing-for-nature-reviews",
)
STYLESHEET_NAME = "nr-chemdraw-stylesheet.cds"


class StandardCorpusError(ValueError):
    """A stable, fail-closed standard corpus error."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise StandardCorpusError("STANDARD_CORPUS_FILE_INVALID") from exc
    return digest.hexdigest()


def _safe_root(root: Path) -> Path:
    supplied = Path(root)
    if _is_reparse(supplied) or not supplied.is_dir():
        raise StandardCorpusError("STANDARD_CORPUS_ROOT_INVALID")
    try:
        return supplied.resolve(strict=True)
    except OSError as exc:
        raise StandardCorpusError("STANDARD_CORPUS_ROOT_INVALID") from exc


def _is_reparse(path: Path) -> bool:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except OSError:
        return False


def _read_json(path: Path, code: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise StandardCorpusError(code)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StandardCorpusError(code) from exc


def _manifest_validator() -> Draft202012Validator:
    schema = _read_json(SCHEMA_PATH, "STANDARD_CORPUS_SCHEMA_INVALID")
    if not isinstance(schema, dict):
        raise StandardCorpusError("STANDARD_CORPUS_SCHEMA_INVALID")
    return Draft202012Validator(schema)


def _resolve_declared_file(root: Path, relative: str) -> Path:
    candidate = root / relative
    current = root
    for part in Path(relative).parts:
        current = current / part
        if _is_reparse(current):
            raise StandardCorpusError("STANDARD_CORPUS_FILE_INVALID")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise StandardCorpusError("STANDARD_CORPUS_FILE_INVALID") from exc
    if not resolved.is_file():
        raise StandardCorpusError("STANDARD_CORPUS_FILE_INVALID")
    return resolved


def _validate_manifest_files(root: Path, manifest: dict[str, Any]) -> set[str]:
    rows = manifest["files"]
    declared = [row["path"] for row in rows]
    if (
        len(rows) != 1071
        or len(declared) != len(set(declared))
        or manifest["file_count"] != 1071
        or manifest["file_count"] != len(rows)
    ):
        raise StandardCorpusError("STANDARD_CORPUS_MANIFEST_INVALID")
    for row in rows:
        path = _resolve_declared_file(root, row["path"])
        if path.stat().st_size != row["size_bytes"] or _sha256(path) != row["sha256"]:
            raise StandardCorpusError("STANDARD_CORPUS_HASH_MISMATCH")
    mineru_root = root / "mineru-outputs"
    if mineru_root.is_symlink() or not mineru_root.is_dir():
        raise StandardCorpusError("STANDARD_CORPUS_LAYOUT_INVALID")
    actual = {
        path.relative_to(root).as_posix()
        for path in mineru_root.rglob("*")
        if path.is_file() and not _is_reparse(path)
    }
    if any(_is_reparse(path) for path in mineru_root.rglob("*")):
        raise StandardCorpusError("STANDARD_CORPUS_FILE_INVALID")
    if actual != set(declared):
        raise StandardCorpusError("STANDARD_CORPUS_FILE_SET_MISMATCH")
    return set(declared)


def _jobs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    batches = manifest.get("batches") if isinstance(manifest, dict) else None
    if not isinstance(batches, list):
        raise StandardCorpusError("STANDARD_CORPUS_MINERU_INVALID")
    jobs = [
        job
        for batch in batches
        if isinstance(batch, dict) and isinstance(batch.get("jobs"), list)
        for job in batch["jobs"]
        if isinstance(job, dict)
    ]
    if len(jobs) != 14 or any(job.get("state") != "done" for job in jobs):
        raise StandardCorpusError("STANDARD_CORPUS_MINERU_INCOMPLETE")
    return jobs


def _validate_layers(root: Path, declared: set[str]) -> tuple[int, int]:
    mineru = _read_json(root / "mineru-outputs/manifest.json", "STANDARD_CORPUS_MINERU_INVALID")
    jobs = _jobs(mineru)
    slugs = [job.get("slug") for job in jobs]
    expected = {*REVIEW_SLUGS, *GUIDE_SLUGS}
    if len(slugs) != len(set(slugs)) or set(slugs) != expected:
        raise StandardCorpusError("STANDARD_CORPUS_LAYER_INVALID")
    for slug in slugs:
        markdown = f"mineru-outputs/markdown/{slug}.md"
        pdf_prefix = f"mineru-outputs/extracted/{slug}/"
        origin_pdfs = [
            path
            for path in declared
            if path.startswith(pdf_prefix) and path.endswith("_origin.pdf")
        ]
        if markdown not in declared or len(origin_pdfs) != 1:
            raise StandardCorpusError("STANDARD_CORPUS_MINERU_INCOMPLETE")
    return len(REVIEW_SLUGS), len(GUIDE_SLUGS)


def _validate_source_zip(root: Path, manifest: dict[str, Any]) -> int:
    source = manifest["source_zip"]
    if source["sha256"] != manifest["source_zip_sha256"]:
        raise StandardCorpusError("STANDARD_CORPUS_MANIFEST_INVALID")
    archive = _resolve_declared_file(root, source["path"])
    if archive.stat().st_size != source["size_bytes"] or _sha256(archive) != source["sha256"]:
        raise StandardCorpusError("STANDARD_CORPUS_HASH_MISMATCH")
    try:
        with ZipFile(archive) as package:
            stylesheet = [
                info
                for info in package.infolist()
                if not info.is_dir() and Path(info.filename).name.casefold() == STYLESHEET_NAME
            ]
    except (OSError, BadZipFile) as exc:
        raise StandardCorpusError("STANDARD_CORPUS_SOURCE_ZIP_INVALID") from exc
    if len(stylesheet) != 1:
        raise StandardCorpusError("STANDARD_CORPUS_STYLESHEET_MISSING")
    return 1


def load_standard_corpus(root: Path) -> dict[str, Any]:
    """Verify the archived corpus without returning or copying benchmark text."""
    corpus_root = _safe_root(root)
    manifest_path = corpus_root / MANIFEST_NAME
    manifest = _read_json(manifest_path, "STANDARD_CORPUS_MANIFEST_INVALID")
    if not isinstance(manifest, dict):
        raise StandardCorpusError("STANDARD_CORPUS_MANIFEST_INVALID")
    errors = sorted(_manifest_validator().iter_errors(manifest), key=lambda error: list(error.path))
    if errors:
        raise StandardCorpusError("STANDARD_CORPUS_MANIFEST_INVALID")
    if (
        manifest["file_count"] != 1071
        or len(manifest["files"]) != 1071
        or manifest["pdf_count"] != 14
        or manifest["mineru_success_count"] != 14
        or manifest["mineru_failure_count"] != 0
    ):
        raise StandardCorpusError("STANDARD_CORPUS_MINERU_INCOMPLETE")
    declared = _validate_manifest_files(corpus_root, manifest)
    if sum(path.casefold().endswith(".pdf") for path in declared) != 14:
        raise StandardCorpusError("STANDARD_CORPUS_MINERU_INCOMPLETE")
    review_count, guide_count = _validate_layers(corpus_root, declared)
    stylesheet_count = _validate_source_zip(corpus_root, manifest)
    return {
        "schema_version": "standard-corpus-binding.v1",
        "manifest_sha256": _sha256(manifest_path),
        "source_zip_sha256": manifest["source_zip_sha256"],
        "file_count": manifest["file_count"],
        "pdf_count": manifest["pdf_count"],
        "mineru_success_count": manifest["mineru_success_count"],
        "mineru_failure_count": manifest["mineru_failure_count"],
        "review_count": review_count,
        "guide_count": guide_count,
        "stylesheet_count": stylesheet_count,
    }
