"""Bounded deterministic import of one researcher-provided source ZIP."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
import urllib.parse
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, BinaryIO

from .public_corpus import (
    ManifestError,
    _matches_format,
    _now,
    _portable_target_components,
    _preflight_manifest,
    _preflight_metadata_destinations,
    _safe_target,
    _sha256_bytes,
    _sha256_file,
    _stage_bytes,
    _validate_existing_target_boundary,
    _validate_target_parent,
)


DEFAULT_MAX_MEMBERS = 1_000
DEFAULT_MAX_MEMBER_BYTES = 250 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
RECEIPT_FILENAME = "manual_import_receipt.json"
FORMAT_EXTENSIONS = {"PDF": "pdf", "DOCX": "docx", "XLSX": "xlsx"}
CHUNK_BYTES = 1024 * 1024
DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")


class ManualArchiveError(ManifestError):
    """The manual archive or its deterministic mapping is unsafe."""


def _validate_policy(max_members: int, max_member_bytes: int, max_total_bytes: int) -> None:
    for name, value in (
        ("max_members", max_members),
        ("max_member_bytes", max_member_bytes),
        ("max_total_bytes", max_total_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ManualArchiveError(f"{name} must be a positive integer")


def _normalized_portable_path(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    try:
        _portable_target_components(normalized)
    except ManifestError as exc:
        raise ManualArchiveError("archive alias is not portable") from exc
    return normalized.casefold()


def _normalized_safe_basename(value: Any) -> str:
    if not isinstance(value, str):
        raise ManualArchiveError("archive aliases must be safe basenames")
    normalized = unicodedata.normalize("NFKC", value)
    try:
        components = _portable_target_components(normalized)
    except ManifestError as exc:
        raise ManualArchiveError("archive aliases must be safe basenames") from exc
    if len(components) != 1:
        raise ManualArchiveError("archive aliases must be safe basenames")
    return normalized.casefold()


def _validate_member(info: zipfile.ZipInfo) -> tuple[str, str] | None:
    name = info.filename
    if not isinstance(name, str) or not name:
        raise ManualArchiveError("archive contains an unsafe member name")
    normalized = unicodedata.normalize("NFKC", name)
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in normalized):
        raise ManualArchiveError("archive contains an unsafe member name")
    if "\\" in normalized or normalized.startswith("/") or DRIVE_PREFIX_RE.match(normalized):
        raise ManualArchiveError("archive contains an unsafe member name")
    is_directory = info.is_dir()
    candidate = normalized[:-1] if is_directory and normalized.endswith("/") else normalized
    if not candidate or "//" in candidate:
        raise ManualArchiveError("archive contains an unsafe member name")
    try:
        components = _portable_target_components(candidate)
    except ManifestError as exc:
        raise ManualArchiveError("archive contains an unsafe member name") from exc
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ManualArchiveError("archive contains a link or special member")
    if (is_directory and file_type == stat.S_IFREG) or (not is_directory and file_type == stat.S_IFDIR):
        raise ManualArchiveError("archive member type is inconsistent")
    normalized_name = "/".join(components).casefold()
    if is_directory:
        return None
    return normalized_name, components[-1].casefold()


def _read_member_bounded(
    source: BinaryIO,
    *,
    max_member_bytes: int,
    max_total_bytes: int,
    total_so_far: int,
    destination: BinaryIO | None = None,
    digest: Any | None = None,
) -> tuple[int, int]:
    member_bytes = 0
    total_bytes = total_so_far
    while True:
        chunk = source.read(CHUNK_BYTES)
        if not chunk:
            break
        member_bytes += len(chunk)
        total_bytes += len(chunk)
        if member_bytes > max_member_bytes or total_bytes > max_total_bytes:
            raise ManualArchiveError("archive exceeds bounded byte policy")
        if destination is not None:
            destination.write(chunk)
        if digest is not None:
            digest.update(chunk)
    return member_bytes, total_bytes


def _preflight_archive(
    archive: zipfile.ZipFile,
    *,
    max_members: int,
    max_member_bytes: int,
    max_total_bytes: int,
) -> list[dict[str, Any]]:
    infos = archive.infolist()
    if len(infos) > max_members:
        raise ManualArchiveError("archive exceeds bounded member policy")
    declared_total = 0
    seen_names: set[str] = set()
    members: list[dict[str, Any]] = []
    for index, info in enumerate(infos):
        if info.flag_bits & 0x1:
            raise ManualArchiveError("encrypted archive members are forbidden")
        if info.file_size < 0 or info.file_size > max_member_bytes:
            raise ManualArchiveError("archive exceeds bounded member byte policy")
        declared_total += info.file_size
        if declared_total > max_total_bytes:
            raise ManualArchiveError("archive exceeds bounded total byte policy")
        normalized = _validate_member(info)
        duplicate_key = unicodedata.normalize("NFKC", info.filename.rstrip("/")).casefold()
        if duplicate_key in seen_names:
            raise ManualArchiveError("archive contains duplicate normalized member names")
        seen_names.add(duplicate_key)
        if normalized is not None:
            members.append(
                {
                    "index": index,
                    "normalized_name": normalized[0],
                    "normalized_basename": normalized[1],
                }
            )

    actual_total = 0
    try:
        for record in members:
            info = infos[record["index"]]
            with archive.open(info, "r") as source:
                actual_member, actual_total = _read_member_bounded(
                    source,
                    max_member_bytes=max_member_bytes,
                    max_total_bytes=max_total_bytes,
                    total_so_far=actual_total,
                )
            if actual_member != info.file_size:
                raise ManualArchiveError("archive member size is inconsistent")
    except (zipfile.BadZipFile, RuntimeError, EOFError, NotImplementedError) as exc:
        raise ManualArchiveError("archive is invalid or unsupported") from exc
    return members


def _url_basename_alias(row: dict[str, Any], expected_extension: str) -> str | None:
    path = urllib.parse.urlsplit(row["url"]).path
    basename = urllib.parse.unquote(path.rsplit("/", 1)[-1])
    if not basename or not basename.casefold().endswith(f".{expected_extension}"):
        return None
    try:
        return _normalized_safe_basename(basename)
    except ManualArchiveError:
        return None


def _build_alias_indexes(
    prepared: list[dict[str, Any]],
) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    full_aliases: dict[str, set[int]] = defaultdict(set)
    basename_aliases: dict[str, set[int]] = defaultdict(set)
    for row_index, item in enumerate(prepared):
        row = item["row"]
        full_aliases[_normalized_portable_path(row["target_path"])].add(row_index)
        basename_aliases[_normalized_safe_basename(row["target_path"].rsplit("/", 1)[-1])].add(row_index)
        basename_aliases[_normalized_safe_basename(item["save_as"])].add(row_index)
        url_alias = _url_basename_alias(row, FORMAT_EXTENSIONS[item["expected_format"]])
        if url_alias is not None:
            basename_aliases[url_alias].add(row_index)
        archive_names = row.get("archive_names", [])
        if not isinstance(archive_names, list):
            raise ManualArchiveError("archive_names must be a list of safe basenames")
        for alias in archive_names:
            basename_aliases[_normalized_safe_basename(alias)].add(row_index)
    return full_aliases, basename_aliases


def _map_members(
    members: list[dict[str, Any]],
    full_aliases: dict[str, set[int]],
    basename_aliases: dict[str, set[int]],
) -> tuple[dict[int, int], set[int], int]:
    row_members: dict[int, list[int]] = defaultdict(list)
    ambiguous_rows: set[int] = set()
    for member_index, member in enumerate(members):
        candidates = set(full_aliases.get(member["normalized_name"], set()))
        candidates.update(basename_aliases.get(member["normalized_basename"], set()))
        if len(candidates) == 1:
            row_members[next(iter(candidates))].append(member_index)
        elif len(candidates) > 1:
            ambiguous_rows.update(candidates)
    for row_index, matches in row_members.items():
        if len(matches) > 1:
            ambiguous_rows.add(row_index)
    resolved = {
        row_index: matches[0]
        for row_index, matches in row_members.items()
        if row_index not in ambiguous_rows and len(matches) == 1
    }
    matched_members = set(resolved.values())
    return resolved, ambiguous_rows, len(members) - len(matched_members)


def _base_result(item: dict[str, Any]) -> dict[str, Any]:
    row = item["row"]
    return {
        "download_id": row["download_id"],
        "study_id": row["study_id"],
        "document_role": row["document_role"],
        "expected_format": item["expected_format"],
        "target_path": row["target_path"],
        "status": None,
        "reason": None,
        "sha256": None,
        "size_bytes": None,
    }


def _inspect_existing(item: dict[str, Any], output_root: Path) -> dict[str, Any] | None:
    target = item["target"]
    if not target.exists() and not target.is_symlink():
        return None
    result = _base_result(item)
    _validate_existing_target_boundary(output_root, target)
    if not target.is_file():
        result.update(status="INVALID_EXISTING", reason="EXISTING_TARGET_NOT_REGULAR")
        return result
    actual_sha256 = _sha256_file(target)
    if item["expected_sha256"] is not None and actual_sha256 != item["expected_sha256"]:
        result.update(status="INVALID_EXISTING", reason="EXISTING_HASH_MISMATCH")
    elif not _matches_format(target, item["expected_format"]):
        result.update(status="INVALID_EXISTING", reason="EXISTING_FORMAT_MISMATCH")
    else:
        result.update(
            status="VERIFIED_EXISTING",
            sha256=actual_sha256,
            size_bytes=target.stat().st_size,
        )
    return result


def _stage_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    item: dict[str, Any],
    output_root: Path,
    *,
    max_member_bytes: int,
    max_total_bytes: int,
    total_so_far: int,
) -> tuple[Path, str, int, int]:
    row = item["row"]
    target, _ = _safe_target(output_root, row["target_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target, _ = _safe_target(output_root, row["target_path"])
    _validate_target_parent(output_root, target)
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".manual-import", dir=target.parent
        )
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            with archive.open(info, "r") as source:
                size_bytes, total_bytes = _read_member_bounded(
                    source,
                    max_member_bytes=max_member_bytes,
                    max_total_bytes=max_total_bytes,
                    total_so_far=total_so_far,
                    destination=destination,
                    digest=digest,
                )
            destination.flush()
            os.fsync(destination.fileno())
        if size_bytes != info.file_size:
            raise ManualArchiveError("archive member size is inconsistent")
        result = temporary
        temporary = None
        return result, digest.hexdigest(), size_bytes, total_bytes
    except (zipfile.BadZipFile, RuntimeError, EOFError, NotImplementedError) as exc:
        raise ManualArchiveError("archive is invalid or unsupported") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _publish_receipt(output_root: Path, receipt: dict[str, Any]) -> None:
    destination = output_root / RECEIPT_FILENAME
    _validate_target_parent(output_root, destination)
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ManualArchiveError("manual import receipt destination is unsafe")
    payload = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    staged = _stage_bytes(destination, payload)
    try:
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise ManualArchiveError("manual import receipt destination is unsafe")
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def import_manual_archive(
    manifest_path: Path | str,
    archive_path: Path | str,
    output_root: Path | str,
    *,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    """Import uniquely mapped files from one bounded ZIP without network access."""

    _validate_policy(max_members, max_member_bytes, max_total_bytes)
    manifest_path = Path(manifest_path)
    archive_path = Path(archive_path)
    output_root = Path(output_root)
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManualArchiveError("manifest is not valid JSON") from exc
    try:
        prepared = _preflight_manifest(manifest, output_root)
        _preflight_metadata_destinations(output_root)
    except ManifestError as exc:
        raise ManualArchiveError("manifest or output targets are unsafe") from exc

    archive_digest = hashlib.sha256()
    try:
        archive_handle = archive_path.open("rb")
    except OSError:
        raise
    with archive_handle:
        for chunk in iter(lambda: archive_handle.read(CHUNK_BYTES), b""):
            archive_digest.update(chunk)
        archive_handle.seek(0)
        try:
            archive = zipfile.ZipFile(archive_handle, "r")
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise ManualArchiveError("archive is not a valid ZIP") from exc
        with archive:
            members = _preflight_archive(
                archive,
                max_members=max_members,
                max_member_bytes=max_member_bytes,
                max_total_bytes=max_total_bytes,
            )
            full_aliases, basename_aliases = _build_alias_indexes(prepared)
            resolved_members, ambiguous_rows, unmatched_count = _map_members(
                members, full_aliases, basename_aliases
            )

            output_root.mkdir(parents=True, exist_ok=True)
            try:
                _preflight_metadata_destinations(output_root)
            except ManifestError as exc:
                raise ManualArchiveError("manual import metadata destination is unsafe") from exc
            infos = archive.infolist()
            results = [_base_result(item) for item in prepared]
            staged: dict[int, tuple[Path, str, int]] = {}
            staged_total = 0
            try:
                for row_index, item in enumerate(prepared):
                    existing = _inspect_existing(item, output_root)
                    if existing is not None:
                        results[row_index] = existing
                        continue
                    if row_index in ambiguous_rows:
                        results[row_index].update(status="AMBIGUOUS", reason="ARCHIVE_ALIAS_AMBIGUOUS")
                        continue
                    member_index = resolved_members.get(row_index)
                    if member_index is None:
                        results[row_index].update(status="MISSING", reason="NO_UNIQUE_ARCHIVE_MEMBER")
                        continue
                    member = members[member_index]
                    staged_path, digest, size_bytes, staged_total = _stage_member(
                        archive,
                        infos[member["index"]],
                        item,
                        output_root,
                        max_member_bytes=max_member_bytes,
                        max_total_bytes=max_total_bytes,
                        total_so_far=staged_total,
                    )
                    if item["expected_sha256"] is not None and digest != item["expected_sha256"]:
                        staged_path.unlink(missing_ok=True)
                        results[row_index].update(status="HASH_MISMATCH", reason="EXPECTED_HASH_MISMATCH")
                        continue
                    if not _matches_format(staged_path, item["expected_format"]):
                        staged_path.unlink(missing_ok=True)
                        results[row_index].update(status="FORMAT_MISMATCH", reason="EXPECTED_FORMAT_MISMATCH")
                        continue
                    staged[row_index] = (staged_path, digest, size_bytes)

                for row_index, (staged_path, digest, size_bytes) in list(staged.items()):
                    item = prepared[row_index]
                    target, _ = _safe_target(output_root, item["row"]["target_path"])
                    existing = _inspect_existing(item, output_root)
                    if existing is not None:
                        results[row_index] = existing
                        continue
                    try:
                        os.link(staged_path, target)
                    except FileExistsError:
                        existing = _inspect_existing(item, output_root)
                        if existing is None:
                            raise ManualArchiveError("target appeared during atomic publication")
                        results[row_index] = existing
                        continue
                    staged_path.unlink()
                    staged.pop(row_index)
                    results[row_index].update(
                        status="IMPORTED",
                        sha256=digest,
                        size_bytes=size_bytes,
                    )
            finally:
                for staged_path, _, _ in staged.values():
                    staged_path.unlink(missing_ok=True)

    counts = Counter(result["status"] for result in results)
    receipt = {
        "schema_version": "manual-archive-import-receipt.v1",
        "created_at": _now(),
        "manifest_basename": manifest_path.name,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "archive_basename": archive_path.name,
        "archive_sha256": archive_digest.hexdigest(),
        "policy": {
            "max_members": max_members,
            "max_member_bytes": max_member_bytes,
            "max_total_bytes": max_total_bytes,
            "network_enabled": False,
            "overwrite_existing": False,
        },
        "results": results,
        "counts": dict(sorted(counts.items())),
        "unmatched_count": unmatched_count,
    }
    _publish_receipt(output_root, receipt)
    return receipt


__all__ = [
    "DEFAULT_MAX_MEMBER_BYTES",
    "DEFAULT_MAX_MEMBERS",
    "DEFAULT_MAX_TOTAL_BYTES",
    "ManualArchiveError",
    "import_manual_archive",
]
