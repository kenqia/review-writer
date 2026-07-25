"""Pure DOI supplement identity parsing and non-mutating manifest audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:a-z0-9]+$", re.IGNORECASE)
_SUPPLEMENT_RE = re.compile(r"^(?P<parent>.+)\.(?P<suffix>s\d+|supp\d*)$", re.IGNORECASE)


def normalize_doi(value: str | None) -> str | None:
    """Return a safe normalized DOI, rejecting URL decorations and malformed input."""

    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.lower().startswith("doi:"):
        raw = raw[4:].strip()
    elif "://" in raw:
        parsed = urlsplit(raw)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"doi.org", "dx.doi.org"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return None
        raw = parsed.path.lstrip("/")
    elif any(marker in raw for marker in ("?", "#", "@")):
        return None
    raw = raw.lower().rstrip(".,; ")
    return raw if _DOI_RE.fullmatch(raw) else None


def supplement_parent_relation(
    value: str | None, *, publisher_confirmed_parent_doi: str | None = None
) -> dict[str, str | None]:
    """Classify only terminal supplement suffixes; confirmation requires outside evidence."""

    doi = normalize_doi(value)
    if not doi:
        return {
            "normalized_doi": None,
            "candidate_parent_doi": None,
            "confirmed_parent_doi": None,
            "relation_status": "NOT_A_VALID_TERMINAL_SUPPLEMENT_DOI",
        }
    match = _SUPPLEMENT_RE.fullmatch(doi)
    if not match or not _DOI_RE.fullmatch(match["parent"]):
        return {
            "normalized_doi": doi,
            "candidate_parent_doi": None,
            "confirmed_parent_doi": None,
            "relation_status": "NOT_A_TERMINAL_SUPPLEMENT_SUFFIX",
        }
    parent = match["parent"].lower()
    confirmed = normalize_doi(publisher_confirmed_parent_doi)
    is_confirmed = confirmed == parent
    return {
        "normalized_doi": doi,
        "candidate_parent_doi": parent,
        "confirmed_parent_doi": parent if is_confirmed else None,
        "relation_status": "PUBLISHER_CONFIRMED_PARENT" if is_confirmed else "PARENT_CANDIDATE_STRING_DERIVED",
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_supplement_reports(candidate_pool: Path | str, acquisition_manifest: Path | str) -> dict[str, Any]:
    """Inventory suffix reports without changing either frozen input."""

    pool_path, manifest_path = Path(candidate_pool), Path(acquisition_manifest)
    candidates = [json.loads(line) for line in pool_path.read_text(encoding="utf-8").splitlines() if line]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for record in candidates:
        relation = supplement_parent_relation(record.get("doi"))
        if relation["candidate_parent_doi"]:
            rows.append({
                "source": "candidate_pool",
                "stable_identity": record["candidate_id"],
                "candidate_id": record["candidate_id"],
                "doi": relation["normalized_doi"],
                "report_role": "SUPPLEMENTARY_REPORT",
                "study_count_role": "NOT_AN_INDEPENDENT_STUDY",
                "future_acquisition_document_role": "SI_OR_REPORT_ROLE_REQUIRED",
                **relation,
            })
    for download in manifest.get("downloads", []):
        relation = supplement_parent_relation(download.get("doi"))
        if relation["candidate_parent_doi"]:
            rows.append({
                "source": "acquisition_manifest",
                "stable_identity": download["download_id"],
                "candidate_id": download.get("study_id"),
                "doi": relation["normalized_doi"],
                "frozen_document_role": download.get("document_role"),
                "report_role": "SUPPLEMENTARY_REPORT",
                "study_count_role": "NOT_AN_INDEPENDENT_STUDY",
                "future_acquisition_document_role": "SI_OR_REPORT_ROLE_REQUIRED",
                **relation,
            })
    counts = {
        "candidate_pool_suffix_reports": sum(row["source"] == "candidate_pool" for row in rows),
        "acquisition_manifest_suffix_reports": sum(row["source"] == "acquisition_manifest" for row in rows),
    }
    return {
        "schema_version": "supplement-parent-relation-audit.v1",
        "non_mutating": True,
        "inputs": {
            "candidate_pool": {"path": str(pool_path), "sha256": sha256_file(pool_path)},
            "acquisition_manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        },
        "counts": counts,
        "records": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit terminal DOI supplement reports without mutating inputs.")
    parser.add_argument("--candidate-pool", required=True, type=Path)
    parser.add_argument("--acquisition-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit_supplement_reports(args.candidate_pool, args.acquisition_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
