#!/usr/bin/env python3
"""Archive an already parsed standard corpus with a portable hash manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas/quality/standard_corpus_manifest.v1.schema.json"
DEFAULT_SOURCE_ZIP_SHA256 = "92d2546f71d8751d2d150f125cca0e19c801e7c2fffed6ecca2e61c104d90d3e"


class StandardArchiveError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(attributes & reparse_flag)
    except OSError:
        return False


def _validated_files(root: Path) -> list[Path]:
    if not root.is_dir() or _is_reparse(root):
        raise StandardArchiveError("STANDARD_PARSE_SOURCE_INVALID")
    files: list[Path] = []
    for path in root.rglob("*"):
        if _is_reparse(path):
            raise StandardArchiveError("STANDARD_PARSE_SOURCE_INVALID")
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise StandardArchiveError("STANDARD_PARSE_SOURCE_INVALID") from exc
        if stat.S_ISREG(mode):
            files.append(path)
        elif not stat.S_ISDIR(mode):
            raise StandardArchiveError("STANDARD_PARSE_SOURCE_INVALID")
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _mineru_counts(manifest_path: Path) -> tuple[int, int]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StandardArchiveError("MINERU_MANIFEST_INVALID") from exc
    batches = manifest.get("batches") if isinstance(manifest, dict) else None
    if not isinstance(batches, list):
        raise StandardArchiveError("MINERU_MANIFEST_INVALID")
    jobs = [
        job
        for batch in batches
        if isinstance(batch, dict) and isinstance(batch.get("jobs"), list)
        for job in batch["jobs"]
        if isinstance(job, dict)
    ]
    succeeded = sum(job.get("state") == "done" for job in jobs)
    failed = sum(job.get("state") != "done" for job in jobs)
    if not jobs:
        raise StandardArchiveError("MINERU_MANIFEST_INVALID")
    return succeeded, failed


def _validate_manifest(payload: dict[str, Any]) -> None:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StandardArchiveError("STANDARD_SCHEMA_INVALID") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        raise StandardArchiveError("STANDARD_ARCHIVE_MANIFEST_INVALID")


def archive_standard_corpus(
    source: Path,
    target: Path,
    *,
    source_zip: Path,
    expected_source_zip_sha256: str = DEFAULT_SOURCE_ZIP_SHA256,
) -> dict[str, Any]:
    source = Path(source)
    target = Path(target)
    source_zip = Path(source_zip)
    if os.path.lexists(target):
        raise StandardArchiveError("TARGET_EXISTS")
    if not source_zip.is_file() or _is_reparse(source_zip):
        raise StandardArchiveError("SOURCE_ZIP_INVALID")
    if _sha256_file(source_zip) != expected_source_zip_sha256:
        raise StandardArchiveError("SOURCE_ZIP_HASH_MISMATCH")
    source_files = _validated_files(source)
    success_count, failure_count = _mineru_counts(source / "manifest.json")
    pdf_count = sum(path.suffix.casefold() == ".pdf" for path in source_files)
    if pdf_count != 14 or success_count != 14 or failure_count != 0:
        raise StandardArchiveError("STANDARD_PARSE_INCOMPLETE")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    published = False
    try:
        copied_root = temporary / "mineru-outputs"
        shutil.copytree(source, copied_root, copy_function=shutil.copy2)
        zip_target = temporary / "source" / "standard.zip"
        zip_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_zip, zip_target)
        copied_files = _validated_files(copied_root)
        file_rows = [
            {
                "path": f"mineru-outputs/{path.relative_to(copied_root).as_posix()}",
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in copied_files
        ]
        if len(file_rows) != len(source_files):
            raise StandardArchiveError("STANDARD_ARCHIVE_COPY_MISMATCH")
        manifest = {
            "schema_version": "standard-corpus-manifest.v1",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_zip": {
                "path": "source/standard.zip",
                "sha256": expected_source_zip_sha256,
                "size_bytes": zip_target.stat().st_size,
            },
            "source_zip_sha256": expected_source_zip_sha256,
            "pdf_count": pdf_count,
            "mineru_success_count": success_count,
            "mineru_failure_count": failure_count,
            "file_count": len(file_rows),
            "files": file_rows,
        }
        _validate_manifest(manifest)
        manifest_path = temporary / "standard_corpus_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
        published = True
        return manifest
    except StandardArchiveError:
        raise
    except OSError as exc:
        raise StandardArchiveError("STANDARD_ARCHIVE_WRITE_FAILED") from exc
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive a completed MinerU standard corpus.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--source-zip", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--expected-source-zip-sha256", default=DEFAULT_SOURCE_ZIP_SHA256)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        manifest = archive_standard_corpus(
            args.source,
            args.target,
            source_zip=args.source_zip,
            expected_source_zip_sha256=args.expected_source_zip_sha256,
        )
    except StandardArchiveError as exc:
        print(json.dumps({"status": "ERROR", "reason_code": exc.code}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "ARCHIVED",
                "pdf_count": manifest["pdf_count"],
                "file_count": manifest["file_count"],
                "mineru_success_count": manifest["mineru_success_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
