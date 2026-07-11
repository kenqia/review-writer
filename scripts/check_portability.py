#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCAN_TARGETS = [
    Path("qoderwork"),
    Path("scripts"),
    Path("README.md"),
    Path("AGENTS.md"),
    Path("docs"),
    Path("config"),
]

ALLOW_LOCAL = Path("docs/local/KENQIA_LOCAL_VALIDATION.md")
PR_LOCAL_RE = re.compile(r"local validation record", re.I)

FORBIDDEN_PATTERNS = [
    ("kenqia_home", re.compile(r"/home/kenqia")),
    ("windows_user_mount", re.compile(r"/mnt/c/Users/26960")),
    ("windows_user_path", re.compile(r"C:\\Users\\26960")),
    ("desktop_wrong_root", re.compile(r"Desktop\\review-writer")),
    ("qoderworkcn_default", re.compile(r"\.qoderworkcn")),
]


@dataclass
class Finding:
    path: str
    line: int
    pattern: str
    severity: str
    context: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "pattern": self.pattern,
            "severity": self.severity,
            "context": self.context,
        }


def main() -> int:
    args = parse_args()
    report = build_report()
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    print(
        f"portability-check: {report['status']} "
        f"({len(report['errors'])} errors, {len(report['warnings'])} warnings)"
    )
    return 1 if args.strict and report["errors"] else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check portable docs and scripts for machine-specific paths.")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/portability_report.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/portability_report.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def build_report() -> dict[str, Any]:
    findings: list[Finding] = []
    for path in iter_scan_files():
        text = read_text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for name, pattern in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    severity = classify(path, text)
                    findings.append(Finding(str(path), line_no, name, severity, redact_line(line)))
    errors = [item.to_dict() for item in findings if item.severity == "error"]
    warnings = [item.to_dict() for item in findings if item.severity == "warning"]
    allowed = [item.to_dict() for item in findings if item.severity == "allowed"]
    return {
        "status": "fail" if errors else "warn" if warnings else "pass",
        "summary": {
            "files_scanned": len(list(iter_scan_files())),
            "errors": len(errors),
            "warnings": len(warnings),
            "allowed_local_records": len(allowed),
        },
        "errors": errors,
        "warnings": warnings,
        "allowed": allowed,
        "rules": [name for name, _ in FORBIDDEN_PATTERNS],
        "allowlist": [
            str(ALLOW_LOCAL),
            "docs/pr/* files that contain 'Local validation record'",
        ],
    }


def iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for target in SCAN_TARGETS:
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            for path in sorted(target.rglob("*")):
                if path.is_file() and not should_skip(path):
                    files.append(path)
    return sorted(files)


def should_skip(path: Path) -> bool:
    if path == Path("scripts/check_portability.py"):
        return True
    parts = set(path.parts)
    if "__pycache__" in parts:
        return True
    if path.suffix.lower() in {".pyc", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".svg"}:
        return path.suffix.lower() != ".svg"
    return False


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None


def classify(path: Path, text: str) -> str:
    if path == ALLOW_LOCAL:
        return "allowed"
    if path.parts[:2] == ("docs", "pr") and PR_LOCAL_RE.search(text):
        return "allowed"
    return "error"


def redact_line(line: str) -> str:
    return line.strip()[:240]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Portability Report",
        "",
        f"- status: {report['status']}",
        f"- errors: {len(report['errors'])}",
        f"- warnings: {len(report['warnings'])}",
        f"- allowed local records: {len(report['allowed'])}",
        "",
        "## Errors",
        "",
    ]
    if report["errors"]:
        for item in report["errors"]:
            lines.append(f"- {item['path']}:{item['line']} {item['pattern']}")
    else:
        lines.append("- none")
    lines.extend(["", "## Allowed Local Records", ""])
    if report["allowed"]:
        for item in report["allowed"]:
            lines.append(f"- {item['path']}:{item['line']} {item['pattern']}")
    else:
        lines.append("- none")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
