#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path("/tmp/bailian_no_upload_corpus_manifest.json")
DEFAULT_PREFLIGHT = REPO_ROOT / "scripts/rag/bailian_preflight.py"
DEFAULT_CONFIG = REPO_ROOT / "rag/bailian/preflight_config.example.yaml"
DEFAULT_UPLOAD_MD = Path("/tmp/bailian_small_kb_upload_payload.md")
MAX_TEXT_CHARS = 1200
FORBIDDEN_RE = re.compile(
    r"(\.pdf\b|\.png\b|\.jpe?g\b|\.webp\b|raw_mineru_markdown|full_pdf_text|"
    r"sk-[A-Za-z0-9]{12,}|api[_-]?key\s*[:=]|token\s*[:=]|secret\s*[:=]|"
    r"(^|[\s\"'])((/[A-Za-z0-9_.-]+){2,}|[A-Za-z]:\\Users\\|/mnt/[a-z]/Users/))",
    re.I,
)


class PayloadError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = build_payload(args.clean_root, args.output_jsonl, args.output_md, args.output_manifest)
    except PayloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        "bailian-small-kb-payload: "
        f"{report['status']} records={report['record_count']} blocked={len(report['blocked_items'])}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build sanitized Bailian small-KB pilot payload.")
    parser.add_argument("--clean-root", type=Path, default=Path("demo_projects/clean_3paper_allene_review"))
    parser.add_argument("--output-jsonl", type=Path, default=Path("/tmp/bailian_small_kb_payload.jsonl"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_small_kb_payload.md"))
    parser.add_argument("--output-manifest", type=Path, default=Path("/tmp/bailian_small_kb_payload_manifest.json"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def build_payload(clean_root: Path, output_jsonl: Path, output_md: Path, output_manifest: Path) -> dict[str, Any]:
    ensure_no_upload_manifest(clean_root)
    source = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    items = source.get("items") or []
    if not items:
        raise PayloadError("no-upload manifest has no items")
    records = [sanitize_item(item) for item in items]
    blocked = validate_records(records)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_jsonl.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    rendered_md = render_payload_md(records)
    output_md.write_text(rendered_md, encoding="utf-8")
    DEFAULT_UPLOAD_MD.write_text(rendered_md, encoding="utf-8")
    report = {
        "status": "fail" if blocked else "pass",
        "record_count": len(records),
        "blocked_items": blocked,
        "allowed_fields": [
            "paper_id",
            "title",
            "year",
            "journal",
            "doi_draft",
            "role",
            "claim_draft",
            "figure_note_draft",
            "known_warnings",
            "compact_text",
            "metadata",
            "needs_human_review",
            "trusted_for_scientific_quality",
            "upload_scope",
        ],
        "output_jsonl": str(output_jsonl),
        "output_md": str(output_md),
        "official_upload_md": str(DEFAULT_UPLOAD_MD),
        "safety": {
            "pdf": "not_included",
            "raw_image": "not_included",
            "full_markdown": "not_included",
            "local_absolute_path": "not_included",
            "secret": "not_included",
            "network": "not_used",
            "upload": "not_used",
            "knowledge_base": "not_created",
        },
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def ensure_no_upload_manifest(clean_root: Path) -> None:
    if DEFAULT_MANIFEST.exists():
        return
    cmd = [
        sys.executable,
        str(DEFAULT_PREFLIGHT),
        "--clean-root",
        str(clean_root),
        "--config",
        str(DEFAULT_CONFIG),
        "--output-json",
        "/tmp/bailian_rag_preflight.json",
        "--output-md",
        "/tmp/bailian_rag_preflight.md",
        "--strict",
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    if result.returncode != 0 or not DEFAULT_MANIFEST.exists():
        raise PayloadError("failed to generate no-upload manifest")


def sanitize_item(item: dict[str, Any]) -> dict[str, Any]:
    paper_id = str(item.get("paper_id") or "")
    known_warnings = str(item.get("warning") or item.get("known_warnings") or "not trusted for scientific quality")
    claim = trim(str(item.get("claim_draft") or ""), 650)
    figure = trim(str(item.get("figure_note_draft") or ""), 350)
    compact_text = trim(
        "\n".join(
            [
                f"Paper ID: {paper_id}",
                f"Title: {item.get('title') or paper_id}",
                f"Role: {item.get('role') or 'unknown'}",
                f"Claim draft: {claim}",
                f"Figure note draft: {figure}",
                f"Known warnings: {known_warnings}",
                "Human review required: true",
                "Trusted for scientific quality: false",
            ]
        ),
        MAX_TEXT_CHARS,
    )
    return {
        "paper_id": paper_id,
        "title": item.get("title") or paper_id,
        "compact_text": compact_text,
        "metadata": {
            "year": item.get("year") or "unknown",
            "journal": item.get("journal") or "unknown",
            "doi_draft": item.get("doi_draft") or "",
            "role": item.get("role") or "unknown",
            "known_warnings": known_warnings,
        },
        "needs_human_review": True,
        "trusted_for_scientific_quality": False,
        "upload_scope": "small_kb_pilot",
    }


def trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + " [trimmed]"


def validate_records(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    blocked: list[dict[str, str]] = []
    for record in records:
        paper_id = str(record.get("paper_id") or "unknown")
        text = json.dumps(record, ensure_ascii=False)
        if FORBIDDEN_RE.search(text):
            blocked.append({"paper_id": paper_id, "reason": "payload contains forbidden field/value"})
        if len(str(record.get("compact_text") or "")) > MAX_TEXT_CHARS:
            blocked.append({"paper_id": paper_id, "reason": "compact_text exceeds max chars"})
        if record.get("needs_human_review") is not True:
            blocked.append({"paper_id": paper_id, "reason": "needs_human_review must be true"})
        if record.get("trusted_for_scientific_quality") is not False:
            blocked.append({"paper_id": paper_id, "reason": "trusted_for_scientific_quality must be false"})
        if record.get("upload_scope") != "small_kb_pilot":
            blocked.append({"paper_id": paper_id, "reason": "upload_scope must be small_kb_pilot"})
    return blocked


def render_payload_md(records: list[dict[str, Any]]) -> str:
    lines = ["# Bailian Small KB Payload", "", "Only sanitized compact records are included.", ""]
    for record in records:
        meta = record["metadata"]
        lines.extend(
            [
                f"## {record['paper_id']}: {record['title']}",
                "",
                f"- year: {meta['year']}",
                f"- journal: {meta['journal']}",
                f"- role: {meta['role']}",
                f"- needs_human_review: {record['needs_human_review']}",
                f"- trusted_for_scientific_quality: {record['trusted_for_scientific_quality']}",
                "",
                record["compact_text"],
                "",
            ]
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
