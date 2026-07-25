from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USER_AGENT = "review-writer-public-acquisition/1.0"
SENSITIVE_QUERY_KEYS = {"access_token", "api_key", "apikey", "auth", "authorization", "cookie", "credential", "key", "session", "sessionid", "signature", "token"}
MANUAL_STATUS = "MANUAL_OR_AUTHORIZED_ACCESS_REQUIRED"


class ManifestError(ValueError):
    """The acquisition manifest is unsafe or structurally invalid."""


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


def _safe_target(output_root: Path, relative: str) -> Path:
    raw = Path(relative)
    if raw.is_absolute():
        raise ManifestError(f"absolute target_path is forbidden: {relative}")
    target = (output_root / raw).resolve()
    root = output_root.resolve()
    if target != root and root not in target.parents:
        raise ManifestError(f"target_path escapes output root: {relative}")
    return target


def _safe_url(url: str) -> tuple[bool, str | None, str]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        return False, "URL_USERINFO_FORBIDDEN", urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
    hostname = (parsed.hostname or "").lower()
    local_http = parsed.scheme == "http" and hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not local_http:
        return False, "INSECURE_NONLOCAL_HTTP", url
    keys = {key.lower() for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)}
    if any(key in SENSITIVE_QUERY_KEYS or any(marker in key for marker in ("auth", "cookie", "credential", "session", "signature", "token")) or key.endswith(("_key", "-key")) for key in keys):
        redacted = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "[REDACTED]", ""))
        return False, "SENSITIVE_URL_PARAMETER_FORBIDDEN", redacted
    return True, None, url


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
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - same validated public origin as the manifest URL.
                parser.parse(response.read(1024 * 1024).decode("utf-8", errors="replace").splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                parser.disallow_all = True
            elif 400 <= exc.code <= 499:
                parser.allow_all = True
            else:
                cache[origin] = "ROBOTS_CHECK_FAILED"
                return False, "ROBOTS_CHECK_FAILED"
        except (OSError, urllib.error.URLError):
            cache[origin] = "ROBOTS_CHECK_FAILED"
            return False, "ROBOTS_CHECK_FAILED"
        cache[origin] = parser
    else:
        parser = cached
    return (True, None) if parser.can_fetch(USER_AGENT, url) else (False, "ROBOTS_DISALLOWED")


def _matches_format(prefix: bytes, expected_format: str) -> bool:
    if expected_format == "PDF":
        return prefix.startswith(b"%PDF-")
    return prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))


def _download_source(url: str, target: Path, *, expected_format: str, timeout_seconds: float, max_bytes: int, retries: int) -> tuple[str, str | None, str | None, int | None]:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    for attempt in range(retries + 1):
        try:
            accept = {"PDF": "application/pdf", "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[expected_format]
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept + ",application/octet-stream;q=0.8"})
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - manifest URLs pass explicit scheme/safety checks.
                status = getattr(response, "status", 200)
                length = response.headers.get("Content-Length")
                if length and int(length) > max_bytes:
                    return MANUAL_STATUS, "FILE_EXCEEDS_SIZE_LIMIT", None, status
                digest = hashlib.sha256()
                size = 0
                prefix = b""
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            raise ManifestError("download exceeded max_bytes")
                        if len(prefix) < 5:
                            prefix += chunk[: 5 - len(prefix)]
                        digest.update(chunk)
                        handle.write(chunk)
                if not _matches_format(prefix, expected_format):
                    partial.unlink(missing_ok=True)
                    reason = "RESPONSE_NOT_PDF" if expected_format == "PDF" else "RESPONSE_FORMAT_MISMATCH"
                    return MANUAL_STATUS, reason, None, status
                os.replace(partial, target)
                return "DOWNLOADED", None, digest.hexdigest(), status
        except ManifestError:
            partial.unlink(missing_ok=True)
            return MANUAL_STATUS, "FILE_EXCEEDS_SIZE_LIMIT", None, None
        except urllib.error.HTTPError as exc:
            partial.unlink(missing_ok=True)
            if exc.code in {401, 403}:
                return MANUAL_STATUS, "AUTHORIZATION_REQUIRED", None, exc.code
            transient = exc.code == 429 or 500 <= exc.code <= 599
            if transient and attempt < retries:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = min(float(retry_after), 5.0) if retry_after and retry_after.isdigit() else float(attempt + 1)
                time.sleep(delay)
                continue
            return MANUAL_STATUS, f"HTTP_{exc.code}", None, exc.code
        except (OSError, TimeoutError, urllib.error.URLError):
            partial.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(float(attempt + 1))
                continue
            return MANUAL_STATUS, "NETWORK_FAILURE", None, None
    raise AssertionError("unreachable")


def _write_manual_queue(output_root: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["study_id", "doi", "document_role", "landing_page_url", "source_url", "target_path", "reason"]
    with (output_root / "manual_acquisition.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
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
    (output_root / "manual_acquisition.html").write_text(document, encoding="utf-8")


def acquire_manifest(manifest_path: Path | str, output_root: Path | str, *, allow_network: bool = True, timeout_seconds: float = 30.0, max_bytes: int = 150 * 1024 * 1024, retries: int = 1) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    output_root = Path(output_root)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    downloads = manifest.get("downloads")
    if manifest.get("schema_version") != "public-corpus-acquisition.v1" or not isinstance(downloads, list):
        raise ManifestError("manifest must use public-corpus-acquisition.v1 with a downloads list")
    output_root.mkdir(parents=True, exist_ok=True)
    results = []
    robots_cache: dict[str, urllib.robotparser.RobotFileParser | str] = {}
    for row in downloads:
        required = {"download_id", "study_id", "document_role", "url", "target_path", "source_class"}
        if not isinstance(row, dict) or not required.issubset(row):
            raise ManifestError("every download requires download_id, study_id, document_role, url, target_path, and source_class")
        if row["document_role"] not in {"MAIN", "SI"}:
            raise ManifestError(f"unsupported document_role: {row['document_role']}")
        expected_format = row.get("expected_format", "PDF")
        if expected_format not in {"PDF", "DOCX", "XLSX"}:
            raise ManifestError(f"unsupported expected_format: {expected_format}")
        target = _safe_target(output_root, str(row["target_path"]))
        allowed, url_reason, report_url = _safe_url(str(row["url"]))
        result = {"download_id": row["download_id"], "study_id": row["study_id"], "doi": row.get("doi"), "document_role": row["document_role"], "expected_format": expected_format, "target_path": row["target_path"], "source_url": report_url, "landing_page_url": row.get("landing_page_url"), "source_class": row["source_class"], "status": None, "reason": None, "sha256": None, "size_bytes": None, "http_status": None}
        if target.is_file():
            actual = _sha256_file(target)
            if row.get("expected_sha256") and row["expected_sha256"] != actual:
                result.update(status=MANUAL_STATUS, reason="EXISTING_HASH_MISMATCH")
            elif not _matches_format(target.read_bytes()[:5], expected_format):
                reason = "EXISTING_FILE_NOT_PDF" if expected_format == "PDF" else "EXISTING_FILE_FORMAT_MISMATCH"
                result.update(status=MANUAL_STATUS, reason=reason)
            else:
                result.update(status="VERIFIED_EXISTING", sha256=actual, size_bytes=target.stat().st_size)
        elif row["source_class"] != "PUBLIC_DIRECT":
            result.update(status=MANUAL_STATUS, reason="NO_PUBLIC_DIRECT_PDF")
        elif not allow_network:
            result.update(status=MANUAL_STATUS, reason="LOCAL_FILE_MISSING")
        elif not allowed:
            result.update(status=MANUAL_STATUS, reason=url_reason)
        else:
            robots_ok, robots_reason = _robots_allowed(str(row["url"]), timeout_seconds, robots_cache)
            if not robots_ok:
                result.update(status=MANUAL_STATUS, reason=robots_reason)
            else:
                status, reason, digest, http_status = _download_source(str(row["url"]), target, expected_format=expected_format, timeout_seconds=timeout_seconds, max_bytes=max_bytes, retries=retries)
                result.update(status=status, reason=reason, sha256=digest, http_status=http_status)
                if target.is_file():
                    result["size_bytes"] = target.stat().st_size
        results.append(result)
    manual = [row for row in results if row["status"] == MANUAL_STATUS]
    _write_manual_queue(output_root, manual)
    counts = Counter(row["status"] for row in results)
    receipt = {"schema_version": "public-corpus-acquisition-receipt.v1", "created_at": _now(), "manifest_path": manifest_path.name, "manifest_sha256": _sha256_bytes(manifest_bytes), "results": results, "counts": dict(sorted(counts.items())), "manual_queue_count": len(manual), "policy": {"public_direct_only": True, "network_enabled": allow_network, "robots_respected": True, "credentials_or_sessions_used": False, "bounded_retries": retries, "max_bytes": max_bytes}}
    (output_root / "acquisition_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt
