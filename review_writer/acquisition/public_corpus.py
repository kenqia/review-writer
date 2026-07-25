from __future__ import annotations

import csv
import hashlib
import html
import io
import ipaddress
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USER_AGENT = "review-writer-public-acquisition/1.0"
SENSITIVE_QUERY_KEYS = {"access_token", "api_key", "apikey", "auth", "authorization", "bearer", "cookie", "credential", "key", "pass", "passwd", "password", "pwd", "secret", "session", "sessionid", "sig", "signature", "token"}
SENSITIVE_QUERY_MARKERS = ("auth", "cookie", "credential", "passwd", "password", "secret", "session", "signature", "token")
SENSITIVE_QUERY_SEGMENTS = frozenset({"key", "pass", "pwd", "sig"})
MANUAL_STATUS = "MANUAL_OR_AUTHORIZED_ACCESS_REQUIRED"
METADATA_FILENAMES = frozenset({"acquisition_receipt.json", "manual_acquisition.tsv", "manual_acquisition.html"})
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)
OOXML_CONTENT_TYPES_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/content-types"
OOXML_REQUIREMENTS = {
    "DOCX": ("word/document.xml", b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
    "XLSX": ("xl/workbook.xml", b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
}
MAX_OOXML_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_CONTENT_TYPES_BYTES = 1024 * 1024


class ManifestError(ValueError):
    """The acquisition manifest is unsafe or structurally invalid."""


class _DownloadLimitExceeded(Exception):
    pass


class _NetworkFailure(Exception):
    pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201 - stdlib handler contract
        return None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_target(output_root: Path, relative: str) -> tuple[Path, Path]:
    if not isinstance(relative, str) or not relative.strip():
        raise ManifestError("target_path must be a nonempty relative path")
    if any(ord(character) <= 0x1F or ord(character) == 0x7F for character in relative):
        raise ManifestError("target_path contains an ASCII control character")
    raw = Path(relative)
    if raw.is_absolute():
        raise ManifestError(f"absolute target_path is forbidden: {relative}")
    root = output_root.resolve()
    target = Path(os.path.abspath(root / raw))
    resolved_target = target.resolve()
    if resolved_target == root or root not in resolved_target.parents:
        raise ManifestError(f"target_path escapes output root: {relative}")
    lexical_relative = target.relative_to(root)
    canonical_relative = resolved_target.relative_to(root)
    top_level_components = {lexical_relative.parts[0].casefold(), canonical_relative.parts[0].casefold()}
    if top_level_components & METADATA_FILENAMES:
        raise ManifestError("target_path collides with acquisition metadata")
    return target, resolved_target


def _validate_target_parent(output_root: Path, target: Path) -> None:
    root = output_root.resolve()
    parent = target.parent.resolve()
    if parent != root and root not in parent.parents:
        raise ManifestError("target parent escapes output root")


def _validate_existing_target_boundary(output_root: Path, target: Path) -> None:
    _validate_target_parent(output_root, target)
    if target.is_symlink():
        raise ManifestError("existing target symlinks are forbidden")


def _preflight_manifest(manifest: dict[str, Any], output_root: Path) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        raise ManifestError("manifest must be a JSON object")
    downloads = manifest.get("downloads")
    if manifest.get("schema_version") != "public-corpus-acquisition.v1" or not isinstance(downloads, list):
        raise ManifestError("manifest must use public-corpus-acquisition.v1 with a downloads list")
    prepared: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_targets: set[str] = set()
    for row in downloads:
        required = {"download_id", "study_id", "document_role", "url", "target_path", "source_class"}
        if not isinstance(row, dict) or not required.issubset(row):
            raise ManifestError("every download requires download_id, study_id, document_role, url, target_path, and source_class")
        download_id = row["download_id"]
        if not isinstance(download_id, str) or not download_id.strip():
            raise ManifestError("download_id must be nonempty")
        if not isinstance(row["study_id"], str) or not row["study_id"].strip():
            raise ManifestError("study_id must be a nonempty string")
        for field in ("url", "target_path", "source_class"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ManifestError(f"{field} must be a nonempty string")
        normalized_id = download_id.strip()
        if normalized_id in seen_ids:
            raise ManifestError("download_id values must be unique")
        seen_ids.add(normalized_id)
        if not isinstance(row["document_role"], str) or row["document_role"] not in {"MAIN", "SI"}:
            raise ManifestError("document_role must be MAIN or SI")
        expected_format = row.get("expected_format", "PDF")
        if not isinstance(expected_format, str) or expected_format not in {"PDF", "DOCX", "XLSX"}:
            raise ManifestError("expected_format must be PDF, DOCX, or XLSX")
        expected_sha256 = row.get("expected_sha256")
        if expected_sha256 is not None:
            if not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(expected_sha256):
                raise ManifestError("expected_sha256 must be exactly 64 hexadecimal characters")
            expected_sha256 = expected_sha256.lower()
        target, canonical_target = _safe_target(output_root, row["target_path"])
        if target.is_symlink():
            raise ManifestError("target_path must not be a pre-existing symlink")
        normalized_target = canonical_target.as_posix().casefold()
        if normalized_target in seen_targets:
            raise ManifestError("normalized target_path values must be unique")
        seen_targets.add(normalized_target)
        try:
            allowed, url_reason, report_url = _safe_url(row["url"])
            landing_report_url = None
            if row.get("landing_page_url") is not None:
                _, _, landing_report_url = _safe_url(str(row["landing_page_url"]))
        except ValueError as exc:
            raise ManifestError("manifest contains an invalid URL") from exc
        prepared.append({"row": row, "target": target, "expected_format": expected_format, "expected_sha256": expected_sha256, "allowed": allowed, "url_reason": url_reason, "report_url": report_url, "landing_report_url": landing_report_url})
    return prepared


def _valid_hostname(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    dns_name = hostname[:-1] if hostname.endswith(".") else hostname
    if not dns_name:
        return False
    try:
        ascii_name = dns_name.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if len(ascii_name) > 253 or all(character.isdigit() or character == "." for character in ascii_name):
        return False
    return all(DNS_LABEL_RE.fullmatch(label) for label in ascii_name.split("."))


def _safe_url(url: str) -> tuple[bool, str | None, str]:
    if any(character.isspace() or ord(character) <= 0x1F or ord(character) == 0x7F for character in url):
        raise ValueError("URL contains whitespace or control characters")
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("URL has an invalid host or port") from exc
    if not hostname or not _valid_hostname(hostname):
        raise ValueError("URL requires a valid hostname")
    keys = {key.lower() for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)}
    has_sensitive_query = any(_is_sensitive_query_key(key) for key in keys)
    safe_netloc = parsed.netloc.rsplit("@", 1)[-1]
    safe_query = "[REDACTED]" if has_sensitive_query else parsed.query
    report_url = urllib.parse.urlunsplit((parsed.scheme, safe_netloc, parsed.path, safe_query, ""))
    if parsed.username or parsed.password:
        return False, "URL_USERINFO_FORBIDDEN", report_url
    hostname = hostname.lower()
    local_http = parsed.scheme == "http" and hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not local_http:
        return False, "INSECURE_NONLOCAL_HTTP", report_url
    if has_sensitive_query:
        return False, "SENSITIVE_URL_PARAMETER_FORBIDDEN", report_url
    return True, None, report_url


def _is_sensitive_query_key(key: str) -> bool:
    normalized = key.casefold()
    segments = {segment for segment in re.split(r"[^a-z0-9]+", normalized) if segment}
    return (
        normalized in SENSITIVE_QUERY_KEYS
        or any(marker in normalized for marker in SENSITIVE_QUERY_MARKERS)
        or bool(segments & SENSITIVE_QUERY_SEGMENTS)
        or normalized.endswith(("_key", "-key"))
    )


def _open_without_redirect(request: urllib.request.Request, timeout_seconds: float):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        return opener.open(request, timeout=timeout_seconds)  # noqa: S310 - callers apply explicit URL safety checks.
    except urllib.error.HTTPError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise _NetworkFailure from exc


def _read_network_chunk(response: Any, size: int) -> bytes:
    try:
        return response.read(size)
    except (OSError, urllib.error.URLError) as exc:
        raise _NetworkFailure from exc


def _robots_allowed(url: str, timeout_seconds: float, cache: dict[str, urllib.robotparser.RobotFileParser | str]) -> tuple[bool, str | None]:
    parsed = urllib.parse.urlsplit(url)
    robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    cached = cache.get(origin)
    if isinstance(cached, str):
        return False, cached
    if cached is None:
        parser = urllib.robotparser.RobotFileParser(robots_url)
        try:
            request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain"})
            with _open_without_redirect(request, timeout_seconds) as response:
                parser.parse(response.read(1024 * 1024).decode("utf-8", errors="replace").splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                parser.disallow_all = True
            elif 400 <= exc.code <= 499:
                parser.allow_all = True
            else:
                cache[origin] = "ROBOTS_CHECK_FAILED"
                return False, "ROBOTS_CHECK_FAILED"
        except (OSError, urllib.error.URLError, _NetworkFailure):
            cache[origin] = "ROBOTS_CHECK_FAILED"
            return False, "ROBOTS_CHECK_FAILED"
        cache[origin] = parser
    else:
        parser = cached
    return (True, None) if parser.can_fetch(USER_AGENT, url) else (False, "ROBOTS_DISALLOWED")


def _matches_format(path: Path, expected_format: str) -> bool:
    if expected_format == "PDF":
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    required_part, required_content_type = OOXML_REQUIREMENTS[expected_format]
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if any(info.flag_bits & 0x1 for info in infos):
                return False
            if sum(info.file_size for info in infos) > MAX_OOXML_UNCOMPRESSED_BYTES:
                return False
            names = {info.filename for info in infos}
            if "[Content_Types].xml" not in names or required_part not in names:
                return False
            content_types_info = archive.getinfo("[Content_Types].xml")
            if content_types_info.file_size > MAX_CONTENT_TYPES_BYTES:
                return False
            if archive.testzip() is not None:
                return False
            content_types = archive.read(content_types_info)
            try:
                root = ET.fromstring(content_types)
            except ET.ParseError:
                return False
            if root.tag != f"{{{OOXML_CONTENT_TYPES_NAMESPACE}}}Types":
                return False
            required_part_name = f"/{required_part}"
            required_content_type_text = required_content_type.decode("ascii")
            return any(
                element.tag == f"{{{OOXML_CONTENT_TYPES_NAMESPACE}}}Override"
                and element.attrib.get("PartName") == required_part_name
                and element.attrib.get("ContentType") == required_content_type_text
                for element in root
            )
    except (KeyError, RuntimeError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return False


def _download_source(url: str, target: Path, output_root: Path, robots_cache: dict[str, urllib.robotparser.RobotFileParser | str], *, expected_format: str, expected_sha256: str | None, timeout_seconds: float, max_bytes: int, retries: int) -> tuple[str, str | None, str | None, int | None, str]:
    _validate_target_parent(output_root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _validate_target_parent(output_root, target)
    accept = {"PDF": "application/pdf", "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[expected_format]
    for attempt in range(retries + 1):
        current_url = url
        report_url = _safe_url(url)[2]
        redirect_count = 0
        while True:
            partial: Path | None = None
            try:
                request = urllib.request.Request(current_url, headers={"User-Agent": USER_AGENT, "Accept": accept + ",application/octet-stream;q=0.8"})
                with _open_without_redirect(request, timeout_seconds) as response:
                    status = getattr(response, "status", 200)
                    length = response.headers.get("Content-Length")
                    if length and int(length) > max_bytes:
                        return MANUAL_STATUS, "FILE_EXCEEDS_SIZE_LIMIT", None, status, report_url
                    digest = hashlib.sha256()
                    size = 0
                    descriptor, partial_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
                    partial = Path(partial_name)
                    with os.fdopen(descriptor, "wb") as handle:
                        while True:
                            chunk = _read_network_chunk(response, 1024 * 1024)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                raise _DownloadLimitExceeded
                            digest.update(chunk)
                            handle.write(chunk)
                    actual_sha256 = digest.hexdigest()
                    if expected_sha256 is not None and actual_sha256 != expected_sha256:
                        return MANUAL_STATUS, "DOWNLOADED_HASH_MISMATCH", actual_sha256, status, report_url
                    if not _matches_format(partial, expected_format):
                        reason = "RESPONSE_NOT_PDF" if expected_format == "PDF" else "RESPONSE_FORMAT_MISMATCH"
                        return MANUAL_STATUS, reason, None, status, report_url
                    _validate_target_parent(output_root, target)
                    os.replace(partial, target)
                    partial = None
                    return "DOWNLOADED", None, actual_sha256, status, report_url
            except _DownloadLimitExceeded:
                return MANUAL_STATUS, "FILE_EXCEEDS_SIZE_LIMIT", None, None, report_url
            except urllib.error.HTTPError as exc:
                status = exc.code
                headers = exc.headers
                exc.close()
                if status in REDIRECT_STATUS_CODES:
                    location = headers.get("Location") if headers else None
                    if not location:
                        return MANUAL_STATUS, "REDIRECT_LOCATION_MISSING", None, status, report_url
                    if redirect_count >= MAX_REDIRECTS:
                        return MANUAL_STATUS, "TOO_MANY_REDIRECTS", None, status, report_url
                    redirected_url = urllib.parse.urljoin(current_url, location)
                    try:
                        allowed, reason, redirected_report_url = _safe_url(redirected_url)
                    except ValueError:
                        return MANUAL_STATUS, "INVALID_REDIRECT_URL", None, status, report_url
                    report_url = redirected_report_url
                    if not allowed:
                        return MANUAL_STATUS, reason, None, status, report_url
                    robots_ok, robots_reason = _robots_allowed(redirected_url, timeout_seconds, robots_cache)
                    if not robots_ok:
                        return MANUAL_STATUS, robots_reason, None, status, report_url
                    current_url = redirected_url
                    redirect_count += 1
                    continue
                if status in {401, 403}:
                    return MANUAL_STATUS, "AUTHORIZATION_REQUIRED", None, status, report_url
                transient = status == 429 or 500 <= status <= 599
                if transient and attempt < retries:
                    retry_after = headers.get("Retry-After") if headers else None
                    delay = min(float(retry_after), 5.0) if retry_after and retry_after.isdigit() else float(attempt + 1)
                    time.sleep(delay)
                    break
                return MANUAL_STATUS, f"HTTP_{status}", None, status, report_url
            except _NetworkFailure:
                if attempt < retries:
                    time.sleep(float(attempt + 1))
                    break
                return MANUAL_STATUS, "NETWORK_FAILURE", None, None, report_url
            finally:
                if partial is not None:
                    partial.unlink(missing_ok=True)
    raise AssertionError("unreachable")


def _stage_bytes(path: Path, content: bytes) -> Path:
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        result = temporary
        temporary = None
        return result
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _render_manual_queue(rows: list[dict[str, Any]]) -> tuple[str, str]:
    fields = ["study_id", "doi", "document_role", "landing_page_url", "source_url", "target_path", "reason"]
    tsv = io.StringIO(newline="")
    writer = csv.DictWriter(tsv, fieldnames=fields, delimiter="\t", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    body_rows = []
    for row in rows:
        cells = []
        for field in fields:
            value = str(row.get(field) or "")
            if field in {"landing_page_url", "source_url"} and value.startswith(("https://", "http://")):
                rendered = f'<a href="{html.escape(value, quote=True)}">{html.escape(value)}</a>'
            else:
                rendered = html.escape(value)
            cells.append(f"<td>{rendered}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    document = "<!doctype html><meta charset=\"utf-8\"><title>Manual acquisition queue</title><table><thead><tr>" + "".join(f"<th>{html.escape(field)}</th>" for field in fields) + "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>\n"
    return tsv.getvalue(), document


def _publish_metadata(output_root: Path, rows: list[dict[str, Any]], receipt: dict[str, Any]) -> None:
    tsv, html_document = _render_manual_queue(rows)
    payloads = {
        output_root / "manual_acquisition.tsv": tsv.encode("utf-8"),
        output_root / "manual_acquisition.html": html_document.encode("utf-8"),
        output_root / "acquisition_receipt.json": (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }
    staged: dict[Path, Path] = {}
    published: list[Path] = []
    previous: dict[Path, bytes | None] = {}
    try:
        for destination, content in payloads.items():
            staged[destination] = _stage_bytes(destination, content)
        for destination in payloads:
            if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                raise OSError("metadata destination must be a regular file")
            previous[destination] = destination.read_bytes() if destination.is_file() else None
        try:
            for destination in payloads:
                os.replace(staged[destination], destination)
                staged.pop(destination)
                published.append(destination)
        except BaseException as publication_error:
            rollback_error: BaseException | None = None
            for destination in reversed(published):
                try:
                    old_content = previous[destination]
                    if old_content is None:
                        destination.unlink(missing_ok=True)
                    else:
                        restore = _stage_bytes(destination, old_content)
                        try:
                            os.replace(restore, destination)
                        finally:
                            restore.unlink(missing_ok=True)
                except BaseException as exc:
                    rollback_error = rollback_error or exc
            if rollback_error is not None:
                raise OSError("metadata publication rollback failed") from publication_error
            raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def acquire_manifest(manifest_path: Path | str, output_root: Path | str, *, allow_network: bool = True, timeout_seconds: float = 30.0, max_bytes: int = 150 * 1024 * 1024, retries: int = 1) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    output_root = Path(output_root)
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestError("manifest is not valid JSON") from exc
    prepared = _preflight_manifest(manifest, output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    results = []
    robots_cache: dict[str, urllib.robotparser.RobotFileParser | str] = {}
    for item in prepared:
        row = item["row"]
        target = item["target"]
        expected_format = item["expected_format"]
        expected_sha256 = item["expected_sha256"]
        allowed = item["allowed"]
        url_reason = item["url_reason"]
        report_url = item["report_url"]
        result = {"download_id": row["download_id"], "study_id": row["study_id"], "doi": row.get("doi"), "document_role": row["document_role"], "expected_format": expected_format, "target_path": row["target_path"], "source_url": report_url, "landing_page_url": item["landing_report_url"], "source_class": row["source_class"], "status": None, "reason": None, "sha256": None, "size_bytes": None, "http_status": None}
        _validate_existing_target_boundary(output_root, target)
        if target.is_file():
            _validate_existing_target_boundary(output_root, target)
            actual = _sha256_file(target)
            if expected_sha256 is not None and expected_sha256 != actual:
                result.update(status=MANUAL_STATUS, reason="EXISTING_HASH_MISMATCH")
            else:
                _validate_existing_target_boundary(output_root, target)
                if not _matches_format(target, expected_format):
                    reason = "EXISTING_FILE_NOT_PDF" if expected_format == "PDF" else "EXISTING_FILE_FORMAT_MISMATCH"
                    result.update(status=MANUAL_STATUS, reason=reason)
                else:
                    _validate_existing_target_boundary(output_root, target)
                    result.update(status="VERIFIED_EXISTING", sha256=actual, size_bytes=target.stat().st_size)
        elif row["source_class"] != "PUBLIC_DIRECT":
            result.update(status=MANUAL_STATUS, reason="NO_PUBLIC_DIRECT_PDF")
        elif not allow_network:
            result.update(status=MANUAL_STATUS, reason="LOCAL_FILE_MISSING")
        elif not allowed:
            result.update(status=MANUAL_STATUS, reason=url_reason)
        else:
            robots_ok, robots_reason = _robots_allowed(row["url"], timeout_seconds, robots_cache)
            if not robots_ok:
                result.update(status=MANUAL_STATUS, reason=robots_reason)
            else:
                status, reason, digest, http_status, final_report_url = _download_source(row["url"], target, output_root, robots_cache, expected_format=expected_format, expected_sha256=expected_sha256, timeout_seconds=timeout_seconds, max_bytes=max_bytes, retries=retries)
                result.update(status=status, reason=reason, sha256=digest, http_status=http_status, source_url=final_report_url)
                _validate_existing_target_boundary(output_root, target)
                if target.is_file():
                    _validate_existing_target_boundary(output_root, target)
                    result["size_bytes"] = target.stat().st_size
        results.append(result)
    manual = [row for row in results if row["status"] == MANUAL_STATUS]
    counts = Counter(row["status"] for row in results)
    receipt = {"schema_version": "public-corpus-acquisition-receipt.v1", "created_at": _now(), "manifest_path": manifest_path.name, "manifest_sha256": _sha256_bytes(manifest_bytes), "results": results, "counts": dict(sorted(counts.items())), "manual_queue_count": len(manual), "policy": {"public_direct_only": True, "network_enabled": allow_network, "robots_respected": True, "credentials_or_sessions_used": False, "bounded_retries": retries, "max_bytes": max_bytes}}
    _publish_metadata(output_root, manual, receipt)
    return receipt
