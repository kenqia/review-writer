#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

FORBIDDEN_RE = re.compile(
    r"(\.pdf\b|\.png\b|\.jpe?g\b|\.webp\b|raw_mineru_markdown|full_pdf_text|"
    r"sk-[A-Za-z0-9]{12,}|api[_-]?key\s*[:=]|token\s*[:=]|secret\s*[:=]|"
    r"(^|[\s\"'])((/[A-Za-z0-9_.-]+){2,}|[A-Za-z]:\\Users\\|/mnt/[a-z]/Users/))",
    re.I,
)
SMOKE_FACT = "review-writer Phase 6c smoke test"


def main() -> int:
    args = parse_args()
    report = check_payload(args.payload_md)
    write_outputs(report, args.output_json, args.output_md)
    print(f"bailian-payload-parse-readiness: {report['status']} errors={len(report['errors'])} warnings={len(report['warnings'])}")
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Bailian small-KB upload markdown parse readiness.")
    parser.add_argument("--payload-md", type=Path, default=Path("/tmp/bailian_small_kb_upload_payload.md"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_payload_parse_readiness.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_payload_parse_readiness.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def check_payload(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    text = ""
    if not path.exists():
        errors.append("payload markdown missing")
    else:
        text = path.read_text(encoding="utf-8")
    if path.suffix.lower() != ".md":
        errors.append("payload extension must be .md")
    if text and SMOKE_FACT not in text:
        errors.append("payload missing Phase 6c smoke fact")
    if text and FORBIDDEN_RE.search(text):
        errors.append("payload contains forbidden content marker")
    if text and not re.search(r"^# .+", text, re.M):
        errors.append("payload missing H1 title")
    if text and len(re.findall(r"^## .+", text, re.M)) < 2:
        errors.append("payload needs simple Markdown section headings")
    if text and "Project name:" not in text:
        errors.append("payload missing explicit fact line")
    size = path.stat().st_size if path.exists() else 0
    if size and size < 200:
        warnings.append("payload is very small; parser may lack enough context")
    if size > 20000:
        errors.append("payload is too large for the small smoke pilot")
    return {
        "status": "fail" if errors else "pass",
        "payload_md": str(path),
        "exists": path.exists(),
        "extension": path.suffix.lower(),
        "size_bytes": size,
        "contains_smoke_fact": bool(text and SMOKE_FACT in text),
        "has_h1_title": bool(text and re.search(r"^# .+", text, re.M)),
        "section_heading_count": len(re.findall(r"^## .+", text, re.M)) if text else 0,
        "has_explicit_fact_line": bool(text and "Project name:" in text),
        "forbidden_marker_found": bool(text and FORBIDDEN_RE.search(text)),
        "network": "not_used",
        "upload": "not_used",
        "errors": errors,
        "warnings": warnings,
    }


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bailian Payload Parse Readiness",
        "",
        f"- status: `{report['status']}`",
        f"- payload_md: `{report['payload_md']}`",
        f"- exists: `{report['exists']}`",
        f"- extension: `{report['extension']}`",
        f"- size_bytes: `{report['size_bytes']}`",
        f"- contains_smoke_fact: `{report['contains_smoke_fact']}`",
        f"- has_h1_title: `{report['has_h1_title']}`",
        f"- section_heading_count: `{report['section_heading_count']}`",
        f"- has_explicit_fact_line: `{report['has_explicit_fact_line']}`",
        f"- forbidden_marker_found: `{report['forbidden_marker_found']}`",
        f"- network: `{report['network']}`",
        f"- upload: `{report['upload']}`",
        "",
        "## Errors",
    ]
    if report["errors"]:
        lines.extend(f"- {item}" for item in report["errors"])
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Warnings")
    if report["warnings"]:
        lines.extend(f"- {item}" for item in report["warnings"])
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
