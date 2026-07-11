#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

POLLUTED_AUTHOR_TERMS = ["Cite This", "Read Online", "Article Recommendations", "Supporting Information"]
TRUNCATED_ENDINGS = ("-", "–", "—", ",", ";", ":", "and", "or", "of", "the", "with", "for", "to")
PLACEHOLDER_RE = re.compile(r"^<[^>]+>")


class AuditError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = audit_inputs(args.demo_root)
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    print(
        "real-lite-input-audit: "
        f"{report['status']} selected={report['selected_count']} "
        f"trusted_for_quality={report['trusted_for_quality']} "
        f"engineering_fixture={report['trusted_for_engineering_fixture']}"
    )
    return 1 if args.strict and report["blocking_issues"] else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit real-lite input fixture provenance and quality limits.")
    parser.add_argument("--demo-root", type=Path, default=Path("demo_projects/real_lite_allene_review"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/real_lite_input_audit.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/real_lite_input_audit.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def audit_inputs(demo_root: Path) -> dict[str, Any]:
    inputs = demo_root / "inputs"
    if not inputs.exists():
        raise AuditError(f"inputs directory not found: {inputs}")
    selected = load_selected(inputs / "selected_papers.json")
    if not selected:
        raise AuditError("selected_papers.json has no selected papers")

    per_paper = [audit_paper(inputs, row) for row in selected]
    blocking: list[str] = []
    warnings: list[str] = []
    for row in per_paper:
        if row["missing_required_files"]:
            blocking.append(f"{row['paper_id']}: missing files {', '.join(row['missing_required_files'])}")
        warnings.extend(f"{row['paper_id']}: {item}" for item in row["warnings"])

    selected_count = len(per_paper)
    doi_missing_count = sum(1 for row in per_paper if row["doi_missing"])
    human_unchecked_count = sum(1 for row in per_paper if not row["human_checked"])
    needs_human_count = sum(1 for row in per_paper if row["needs_human_check"])
    pointer_only_count = sum(1 for row in per_paper if row["content_list_pointer_only"] and row["figures_pointer_only"])
    trimmed_count = sum(1 for row in per_paper if row["excerpt_is_trimmed"])

    trusted_for_quality = not (
        doi_missing_count > selected_count / 2
        or human_unchecked_count > selected_count / 2
        or needs_human_count > selected_count / 2
        or pointer_only_count > selected_count / 2
        or trimmed_count > selected_count / 2
    )
    trusted_for_engineering_fixture = not blocking and selected_count >= 3
    if not trusted_for_quality:
        warnings.append(
            "real-lite inputs are suitable as an engineering fixture but not as human-verified scientific quality evidence"
        )
    if pointer_only_count:
        warnings.append(f"{pointer_only_count}/{selected_count} papers use pointer-only content and figure assets")

    status = "fail" if blocking else "warn" if warnings else "pass"
    return {
        "status": status,
        "selected_count": selected_count,
        "trusted_for_quality": trusted_for_quality,
        "trusted_for_engineering_fixture": trusted_for_engineering_fixture,
        "summary": {
            "doi_missing_count": doi_missing_count,
            "human_unchecked_count": human_unchecked_count,
            "needs_human_check_count": needs_human_count,
            "pointer_only_count": pointer_only_count,
            "trimmed_excerpt_count": trimmed_count,
        },
        "per_paper_findings": per_paper,
        "blocking_issues": blocking,
        "warnings": warnings,
        "recommended_action": recommended_action(trusted_for_quality, trusted_for_engineering_fixture),
        "safety": {
            "network": "not_used",
            "pdf_read": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
            "upload": "not_used",
        },
    }


def audit_paper(inputs: Path, selected_row: dict[str, Any]) -> dict[str, Any]:
    paper_id = str(selected_row.get("paper_id") or "").strip()
    if not paper_id:
        return {
            "paper_id": "",
            "missing_required_files": ["paper_id"],
            "warnings": ["selected paper is missing paper_id"],
        }
    metadata_path = inputs / "paper_metadata" / f"{paper_id}.metadata.json"
    excerpt_path = inputs / "mineru_markdown" / f"{paper_id}.excerpt.md"
    content_path = inputs / "content_list" / f"{paper_id}.content_list.pointer.json"
    figures_path = inputs / "figures" / f"{paper_id}.figures.pointer.json"
    missing = [str(path.relative_to(inputs)) for path in [metadata_path, excerpt_path, content_path, figures_path] if not path.exists()]
    metadata = load_json(metadata_path, f"{paper_id} metadata") if metadata_path.exists() else {}
    content = load_json(content_path, f"{paper_id} content pointer") if content_path.exists() else {}
    figures = load_json(figures_path, f"{paper_id} figure pointer") if figures_path.exists() else {}
    excerpt = excerpt_path.read_text(encoding="utf-8", errors="ignore") if excerpt_path.exists() else ""

    title = field_value(metadata.get("title")) or selected_row.get("title") or ""
    year = field_value(metadata.get("year")) or selected_row.get("year") or ""
    journal = field_value(metadata.get("journal")) or selected_row.get("journal") or ""
    doi = field_value(metadata.get("doi")) or selected_row.get("doi") or ""
    authors = field_value(metadata.get("authors")) or selected_row.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    if not isinstance(authors, list):
        authors = []

    metadata_confidence = metadata_confidence_score(metadata)
    human_checked = bool(field_flag(metadata.get("human_checked")) or nested_flag(metadata, "human_review", "human_checked"))
    needs_human_check = bool(
        field_flag(metadata.get("needs_human_check"))
        or nested_flag(metadata, "human_review", "needs_human_check")
        or not human_checked
        or metadata_confidence < 0.9
    )
    source_paths = metadata.get("source_paths") if isinstance(metadata.get("source_paths"), dict) else {}
    source_path_values = [str(value) for value in source_paths.values()] if source_paths else []
    source_paths_are_placeholders = bool(source_path_values) and all(PLACEHOLDER_RE.search(value) for value in source_path_values)

    excerpt_text = excerpt.strip()
    excerpt_chars = len(excerpt_text)
    excerpt_is_trimmed = excerpt_chars > 0 and excerpt_chars < 2500
    excerpt_has_image_markdown = "![" in excerpt_text
    excerpt_truncated_sentence = looks_truncated(excerpt_text)
    content_pointer_only = content.get("copied_content") is False or PLACEHOLDER_RE.search(str(content.get("source_path") or "")) is not None
    figures_pointer_only = figures.get("copied_images") is False or PLACEHOLDER_RE.search(str(figures.get("source_path") or "")) is not None
    polluted_authors = [author for author in authors if any(term.lower() in str(author).lower() for term in POLLUTED_AUTHOR_TERMS)]

    warnings: list[str] = []
    if not doi:
        warnings.append("DOI missing")
    if polluted_authors:
        warnings.append("authors appear polluted by page chrome")
    if not human_checked:
        warnings.append("metadata is not human checked")
    if needs_human_check:
        warnings.append("metadata needs human check")
    if excerpt_truncated_sentence:
        warnings.append("excerpt appears to end mid-sentence or at a truncation boundary")
    if content_pointer_only:
        warnings.append("content_list is pointer-only")
    if figures_pointer_only:
        warnings.append("figures are pointer-only")
    if source_paths_are_placeholders:
        warnings.append("source paths are placeholders")

    return {
        "paper_id": paper_id,
        "title": title,
        "year": year,
        "journal": journal,
        "doi_missing": not bool(doi),
        "authors_polluted": bool(polluted_authors),
        "polluted_author_examples": polluted_authors[:3],
        "metadata_confidence": metadata_confidence,
        "human_checked": human_checked,
        "needs_human_check": needs_human_check,
        "excerpt_chars": excerpt_chars,
        "excerpt_is_trimmed": excerpt_is_trimmed,
        "excerpt_truncated_sentence": excerpt_truncated_sentence,
        "excerpt_has_image_markdown": excerpt_has_image_markdown,
        "content_list_pointer_only": bool(content_pointer_only),
        "figures_pointer_only": bool(figures_pointer_only),
        "source_paths_are_placeholders": source_paths_are_placeholders,
        "missing_required_files": missing,
        "warnings": warnings,
    }


def load_selected(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path, "selected_papers")
    selected = payload.get("selected_papers", payload if isinstance(payload, list) else [])
    if not isinstance(selected, list):
        raise AuditError("selected_papers must be a list")
    return [row for row in selected if isinstance(row, dict)]


def load_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise AuditError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuditError(f"{label} is not valid JSON: {path} ({exc})") from exc


def field_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return field_value(value["value"])
    return value


def field_flag(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("value") or value.get("human_checked"))
    return bool(value)


def nested_flag(payload: dict[str, Any], parent: str, key: str) -> bool:
    row = payload.get(parent)
    return bool(row.get(key)) if isinstance(row, dict) else False


def metadata_confidence_score(metadata: dict[str, Any]) -> float:
    values: list[float] = []
    for key in ["title", "year", "journal", "doi", "authors", "abstract"]:
        row = metadata.get(key)
        if isinstance(row, dict) and isinstance(row.get("confidence"), (int, float)):
            values.append(float(row["confidence"]))
    if not values:
        quality = metadata.get("quality")
        if isinstance(quality, dict) and isinstance(quality.get("metadata_confidence"), (int, float)):
            return float(quality["metadata_confidence"])
        return 0.0
    return round(sum(values) / len(values), 3)


def looks_truncated(text: str) -> bool:
    if not text:
        return False
    stripped = " ".join(text.split())
    if stripped.endswith(("...", "…")):
        return True
    last = stripped[-1]
    if last not in ".!?。！？)）]】":
        return True
    tail = stripped.rsplit(" ", 1)[-1].strip().lower()
    return tail in TRUNCATED_ENDINGS


def recommended_action(trusted_for_quality: bool, trusted_for_engineering_fixture: bool) -> str:
    if trusted_for_quality:
        return "Inputs can support stronger review QA after human spot-checking selected claims."
    if trusted_for_engineering_fixture:
        return "Keep this package for engineering regression only; build a clean 3-paper human-verified dataset before judging scientific quality."
    return "Repair missing fixture files before using this package for regression or demo QA."


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Real-Lite Input Reality Audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Selected papers: {report['selected_count']}",
        f"- Trusted for quality: `{str(report['trusted_for_quality']).lower()}`",
        f"- Trusted for engineering fixture: `{str(report['trusted_for_engineering_fixture']).lower()}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Per-Paper Findings", ""])
    for row in report["per_paper_findings"]:
        lines.append(
            f"- `{row['paper_id']}`: DOI missing={row['doi_missing']}, "
            f"human_checked={row['human_checked']}, needs_human_check={row['needs_human_check']}, "
            f"excerpt_chars={row['excerpt_chars']}, pointer_only={row['content_list_pointer_only'] and row['figures_pointer_only']}"
        )
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in report["warnings"]] or ["- None"])
    lines.extend(["", "## Recommended Action", "", report["recommended_action"], ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
