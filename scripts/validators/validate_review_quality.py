#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import unquote


RULE_SOURCE_FIGURE = "CRQ001_SOURCE_FIGURE_TRACEABILITY"
RULE_CITATION_ORDER = "CRQ002_CITATION_CALLOUT_ORDER"
RULE_DUP_CAPTION = "CRQ003_DUPLICATE_CAPTIONS"
RULE_FORMULA = "CRQ004_CHEMICAL_FORMULA_TYPOGRAPHY"
RULE_REFERENCE = "CRQ005_REFERENCE_FORMAT_COMPLETENESS"
RULE_SECTION_TITLE = "CRQ006_SECTION_HEADING_FIT"
RULE_REVIEW_TITLE = "CRQ007_REVIEW_TITLE_FIT"
RULE_LEAKAGE = "CRQ008_PROMPT_WORKFLOW_LEAKAGE"

IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
CITATION_RE = re.compile(r"\[(\d+(?:\s*(?:,|-|–)\s*\d+)*)\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
CAPTION_RE = re.compile(
    r"^\s*(?:\*\*)?\s*((?:Figure|Fig\.|Scheme|Table)\s*\d+[A-Za-z.-]*|图\s*\d+)\s*[.:：]\s*(.+?)\s*$",
    re.I | re.M,
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", re.I)
AUTHOR_SIGNAL_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:,|\sand\s|\set al\.)")
CHEM_FORMULA_PATTERNS = [
    re.compile(r"\b(?:CO2|H2O|O2|N2|H2|CH4|NH3|SO4\s*2-|NO3-|Fe3\+|Fe2\+|Cu2\+|Zn2\+)\b"),
    re.compile(r"\b[A-Z][a-z]?\d+(?:[+-])\b"),
]

DIRECT_LEAKAGE_TERMS = [
    "写作思路",
    "本节应当",
    "请生成",
    "不要直接出现在正文",
]
PROCESS_TERMS = [
    "llm judge",
    "rule pack",
    "blueprint",
    "workflow",
]


@dataclass
class Finding:
    rule_id: str
    status: str
    severity: str
    message: str
    line: int | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        row = {
            "rule_id": self.rule_id,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
        }
        if self.line is not None:
            row["line"] = self.line
        if self.details:
            row["details"] = self.details
        return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate chemistry review manuscript quality gates.")
    parser.add_argument("--draft", type=Path, required=True, help="Markdown draft to validate.")
    parser.add_argument("--figure-manifest", type=Path, default=None)
    parser.add_argument("--references", type=Path, default=None, help="references.md or references.bib")
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failing status.")
    return parser.parse_args()


def read_text_or_error(path: Path, label: str) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, f"{label} not found: {path}"
    if not path.is_file():
        return None, f"{label} is not a file: {path}"
    try:
        return path.read_text(encoding="utf-8", errors="ignore"), None
    except OSError as exc:
        return None, f"cannot read {label}: {path} ({exc})"


def line_number(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def normalize_caption(text: str) -> str:
    text = re.sub(r"^(?:figure|fig\.|scheme|table|图)\s*\d+[a-z.-]*\s*[.:：]\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def is_url_or_data(path: str) -> bool:
    return bool(re.match(r"^(?:[a-z]+:)?//", path, re.I) or path.startswith("data:"))


def resolve_markdown_path(base_dir: Path, raw: str) -> Path:
    clean = unquote(raw.split("#", 1)[0].strip())
    if " " in clean and clean.startswith("<") and clean.endswith(">"):
        clean = clean[1:-1]
    path = Path(clean)
    return path if path.is_absolute() else base_dir / path


def check_citation_order(text: str) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    bad: list[dict[str, Any]] = []
    for match in CITATION_RE.finditer(text):
        raw = match.group(1)
        numbers: list[int] = []
        local_bad = False
        for part in re.split(r"\s*,\s*", raw):
            if "-" in part or "–" in part:
                left_raw, right_raw = re.split(r"\s*[-–]\s*", part, maxsplit=1)
                left, right = int(left_raw), int(right_raw)
                if left > right:
                    local_bad = True
                numbers.extend([left, right])
            else:
                numbers.append(int(part.strip()))
        if numbers != sorted(numbers):
            local_bad = True
        if local_bad:
            row = {"callout": f"[{raw}]", "line": line_number(text, match.start()), "numbers": numbers}
            bad.append(row)
            findings.append(
                Finding(
                    RULE_CITATION_ORDER,
                    "fail",
                    "error",
                    f"Citation callout is not ascending: [{raw}]",
                    line=row["line"],
                    details=row,
                )
            )
    return findings, {"bad_callouts": bad}


def check_captions(text: str) -> tuple[list[Finding], dict[str, Any]]:
    captions = []
    for match in CAPTION_RE.finditer(text):
        full = f"{match.group(1)}. {match.group(2)}"
        captions.append(
            {
                "caption": full.strip(),
                "normalized": normalize_caption(full),
                "line": line_number(text, match.start()),
            }
        )
    findings: list[Finding] = []
    duplicates: list[dict[str, Any]] = []
    similar: list[dict[str, Any]] = []
    for i, left in enumerate(captions):
        for right in captions[i + 1 :]:
            if not left["normalized"] or not right["normalized"]:
                continue
            if left["normalized"] == right["normalized"]:
                row = {"left": left, "right": right}
                duplicates.append(row)
                findings.append(
                    Finding(
                        RULE_DUP_CAPTION,
                        "fail",
                        "error",
                        "Duplicate figure caption after normalization.",
                        line=right["line"],
                        details=row,
                    )
                )
            elif SequenceMatcher(None, left["normalized"], right["normalized"]).ratio() >= 0.93:
                row = {"left": left, "right": right}
                similar.append(row)
                findings.append(
                    Finding(
                        RULE_DUP_CAPTION,
                        "warn",
                        "warning",
                        "Highly similar figure captions may be duplicated.",
                        line=right["line"],
                        details=row,
                    )
                )
    return findings, {"captions": captions, "duplicate_captions": duplicates, "similar_captions": similar}


def collect_manifest_paths(node: Any, found: list[dict[str, str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            low_key = str(key).lower()
            if isinstance(value, str) and value.strip():
                if low_key in {"source_image_path", "source_path", "source_pdf", "source_content_list", "redrawn_image"}:
                    found.append({"key": str(key), "path": value.strip()})
            collect_manifest_paths(value, found)
    elif isinstance(node, list):
        for item in node:
            collect_manifest_paths(item, found)


def check_images(text: str, draft_path: Path, manifest_path: Path | None) -> tuple[list[Finding], dict[str, Any], list[dict[str, Any]]]:
    findings: list[Finding] = []
    human_tasks: list[dict[str, Any]] = []
    images = []
    missing_images = []
    for match in IMAGE_RE.finditer(text):
        raw = match.group(1).strip()
        if is_url_or_data(raw):
            continue
        resolved = resolve_markdown_path(draft_path.parent, raw)
        row = {"path": raw, "resolved": str(resolved), "line": line_number(text, match.start())}
        images.append(row)
        if not resolved.exists():
            missing_images.append(row)
            findings.append(
                Finding(
                    RULE_SOURCE_FIGURE,
                    "fail",
                    "error",
                    f"Markdown image path does not exist: {raw}",
                    line=row["line"],
                    details=row,
                )
            )
    manifest_paths: list[dict[str, str]] = []
    missing_manifest = []
    if manifest_path:
        if not manifest_path.exists():
            findings.append(Finding(RULE_SOURCE_FIGURE, "fail", "error", f"Figure manifest not found: {manifest_path}"))
        else:
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                collect_manifest_paths(payload, manifest_paths)
            except Exception as exc:
                findings.append(Finding(RULE_SOURCE_FIGURE, "fail", "error", f"Figure manifest is not valid JSON: {exc}"))
            for row in manifest_paths:
                if is_url_or_data(row["path"]):
                    continue
                resolved = Path(row["path"]) if Path(row["path"]).is_absolute() else manifest_path.parent / row["path"]
                if not resolved.exists():
                    miss = {**row, "resolved": str(resolved)}
                    missing_manifest.append(miss)
                    findings.append(
                        Finding(
                            RULE_SOURCE_FIGURE,
                            "fail",
                            "error",
                            f"Figure manifest path does not exist: {row['path']}",
                            details=miss,
                        )
                    )
    if images or manifest_paths:
        human_tasks.append(
            {
                "rule_id": RULE_SOURCE_FIGURE,
                "task": "Compare every manuscript/redrawn figure with its source figure and confirm chemistry, labels, conditions, and values are unchanged.",
                "image_count": len(images),
                "manifest_path_count": len(manifest_paths),
            }
        )
    return findings, {"image_count": len(images), "missing_images": missing_images, "manifest_paths": manifest_paths, "missing_manifest_paths": missing_manifest}, human_tasks


def check_leakage(text: str) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    hits = []
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        for term in DIRECT_LEAKAGE_TERMS:
            if term.lower() in low:
                row = {"term": term, "line": idx, "text": stripped}
                hits.append(row)
                findings.append(
                    Finding(RULE_LEAKAGE, "fail", "error", f"Likely prompt/workflow instruction leaked into manuscript: {term}", idx, row)
                )
        for term in PROCESS_TERMS:
            if term in low:
                row = {"term": term, "line": idx, "text": stripped}
                hits.append(row)
                severity = "error" if any(marker in low for marker in ["should", "must", "use ", "follow", "生成", "应当"]) else "warning"
                findings.append(
                    Finding(
                        RULE_LEAKAGE,
                        "fail" if severity == "error" else "warn",
                        severity,
                        f"Process term may have leaked into manuscript prose: {term}",
                        idx,
                        row,
                    )
                )
    return findings, {"leakage_hits": hits}


def check_references(path: Path | None) -> tuple[list[Finding], dict[str, Any]]:
    if not path:
        return [], {"references_checked": False}
    text, error = read_text_or_error(path, "references")
    if error:
        return [Finding(RULE_REFERENCE, "fail", "error", error)], {"references_checked": True, "reference_entry_count": 0}
    assert text is not None
    stripped = text.strip()
    if not stripped:
        return [Finding(RULE_REFERENCE, "warn", "warning", "References file is empty.")], {"references_checked": True, "reference_entry_count": 0}
    if path.suffix.lower() == ".bib":
        entries = re.findall(r"@\w+\s*\{[^@]+", text, flags=re.S)
    else:
        entries = re.findall(r"^\s*(?:\[\d+\]|\d+\.)\s+.+$", text, flags=re.M)
        if not entries:
            entries = [block.strip() for block in re.split(r"\n\s*\n", stripped) if block.strip()]
    findings: list[Finding] = []
    warnings: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        missing = []
        if not YEAR_RE.search(entry):
            missing.append("year")
        if not (DOI_RE.search(entry) or "doi" in entry.lower()):
            missing.append("doi")
        if not AUTHOR_SIGNAL_RE.search(entry):
            missing.append("author_signal")
        if missing:
            row = {"entry_index": idx, "missing": missing, "preview": entry[:180]}
            warnings.append(row)
            findings.append(
                Finding(RULE_REFERENCE, "warn", "warning", f"Reference entry {idx} may be missing: {', '.join(missing)}", details=row)
            )
    return findings, {"references_checked": True, "reference_entry_count": len(entries), "reference_warnings": warnings}


def check_formula_risks(text: str) -> tuple[list[Finding], dict[str, Any], list[dict[str, Any]]]:
    findings: list[Finding] = []
    risks = []
    seen: set[tuple[str, int]] = set()
    for pattern in CHEM_FORMULA_PATTERNS:
        for match in pattern.finditer(text):
            line = line_number(text, match.start())
            key = (match.group(0), line)
            if key in seen:
                continue
            seen.add(key)
            row = {"formula": match.group(0), "line": line}
            risks.append(row)
            findings.append(
                Finding(
                    RULE_FORMULA,
                    "warn",
                    "warning",
                    f"Chemical formula typography may need subscript/superscript review: {match.group(0)}",
                    line,
                    row,
                )
            )
    tasks = [
        {
            "rule_id": RULE_FORMULA,
            "task": "Check formula typography, charges, isotope labels, and journal target formatting.",
            "items": risks,
        }
    ] if risks else []
    return findings, {"formula_risks": risks}, tasks


def body_preview(text: str, start: int, end: int, limit: int = 900) -> str:
    preview = re.sub(r"\s+", " ", text[start:end]).strip()
    return preview[:limit]


def build_llm_title_tasks(text: str) -> list[dict[str, Any]]:
    headings = list(HEADING_RE.finditer(text))
    tasks: list[dict[str, Any]] = []
    title = ""
    if headings and len(headings[0].group(1)) == 1:
        title = headings[0].group(2).strip()
        body_start = headings[0].end()
    else:
        body_start = 0
    tasks.append(
        {
            "rule_id": RULE_REVIEW_TITLE,
            "task": "Judge whether the review title summarizes the chemical topic, scope, and central comparison axis.",
            "title": title or "(missing H1 title)",
            "body_preview": body_preview(text, body_start, min(len(text), body_start + 2500), 1200),
            "rubric": "Warn if the title is generic, overbroad, or inconsistent with the manuscript body.",
        }
    )
    skip_titles = {"references", "reference list", "bibliography", "cited literature", "参考文献", "acknowledgments", "acknowledgements"}
    all_h2 = [h for h in headings if len(h.group(1)) == 2]
    section_heads = [h for h in all_h2 if h.group(2).strip().lower() not in skip_titles]
    for head in section_heads:
        next_start = next((candidate.start() for candidate in all_h2 if candidate.start() > head.start()), len(text))
        tasks.append(
            {
                "rule_id": RULE_SECTION_TITLE,
                "task": "Judge whether the section heading is specific, conceptual, and consistent with the section body.",
                "section_title": head.group(2).strip(),
                "section_body_preview": body_preview(text, head.end(), next_start),
                "rubric": "Warn if the heading is vague, only a paper list, or mismatched with claims and evidence.",
            }
        )
    return tasks


def status_from_findings(findings: list[Finding], strict: bool) -> str:
    if any(f.severity == "error" for f in findings):
        return "fail"
    if any(f.severity == "warning" for f in findings):
        return "fail" if strict else "warn"
    return "pass"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Chemistry Review Quality Report",
        "",
        f"- Status: {payload['status']}",
        f"- Errors: {len(payload['errors'])}",
        f"- Warnings: {len(payload['warnings'])}",
        f"- LLM judge tasks: {len(payload['llm_judge_tasks'])}",
        f"- Human review tasks: {len(payload['human_review_tasks'])}",
        "",
        "## Checks",
        "",
    ]
    for check in payload["checks"]:
        lines.append(f"- `{check['rule_id']}` {check['severity']}: {check['message']}")
        if check.get("line"):
            lines.append(f"  - line: {check['line']}")
    if not payload["checks"]:
        lines.append("No static or heuristic issues found.")
    lines += ["", "## LLM Judge Tasks", ""]
    for task in payload["llm_judge_tasks"]:
        title = task.get("title") or task.get("section_title") or task.get("task")
        lines.append(f"- `{task['rule_id']}` {title}")
    if not payload["llm_judge_tasks"]:
        lines.append("None.")
    lines += ["", "## Human Review Tasks", ""]
    for task in payload["human_review_tasks"]:
        lines.append(f"- `{task['rule_id']}` {task['task']}")
    if not payload["human_review_tasks"]:
        lines.append("None.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any] | None, int]:
    text, error = read_text_or_error(args.draft, "draft")
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None, 2
    assert text is not None
    findings: list[Finding] = []
    summary: dict[str, Any] = {"draft": str(args.draft)}
    llm_tasks = build_llm_title_tasks(text)
    human_tasks: list[dict[str, Any]] = []

    for check_findings, check_summary in [
        check_citation_order(text),
        check_captions(text),
        check_leakage(text),
        check_references(args.references),
    ]:
        findings.extend(check_findings)
        summary.update(check_summary)

    image_findings, image_summary, image_human = check_images(text, args.draft, args.figure_manifest)
    formula_findings, formula_summary, formula_human = check_formula_risks(text)
    findings.extend(image_findings)
    findings.extend(formula_findings)
    summary.update(image_summary)
    summary.update(formula_summary)
    human_tasks.extend(image_human)
    human_tasks.extend(formula_human)

    checks = [f.to_dict() for f in findings]
    errors = [row for row in checks if row["severity"] == "error"]
    warnings = [row for row in checks if row["severity"] == "warning"]
    report = {
        "status": status_from_findings(findings, args.strict),
        "summary": summary,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "llm_judge_tasks": llm_tasks,
        "human_review_tasks": human_tasks,
    }
    return report, 0 if report["status"] in {"pass", "warn"} and not args.strict else (1 if report["status"] == "fail" else 0)


def main() -> int:
    args = parse_args()
    report, code = build_report(args)
    if report is None:
        return code
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    if not args.output_json and not args.output_md:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
