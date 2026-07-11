#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

ALLENE_RE = re.compile(r"\ballen(?:e|es|yl|ic|oates|amides|ynes|enes)\b", re.I)
EXCERPT_CHARS = 1800
LEGACY_REVIEW_ROOT = "/" + "home" + "/" + "ps" + "/" + "review-writer" + "/"


def main() -> int:
    args = parse_args()
    search_root = args.search_root.resolve()
    repo_root = args.repo_root.resolve()
    report = build_manifest(search_root, repo_root, args.max_papers)
    write_json(args.output_json, report)
    write_markdown(args.output_md, report)
    if len(report["selected_papers"]) >= 3:
        build_input_package(repo_root, report)
    else:
        write_gap_report(repo_root, report)
    print(f"real-lite-preflight: {report['status']} ({report['summary']})")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build real-lite asset manifest without reading PDFs or calling APIs.")
    default_repo = Path(__file__).resolve().parents[2]
    parser.add_argument("--search-root", type=Path, default=default_repo.parent)
    parser.add_argument("--repo-root", type=Path, default=default_repo)
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/real_lite_asset_manifest.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/real_lite_asset_manifest.md"))
    parser.add_argument("--max-papers", type=int, default=5)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def build_manifest(search_root: Path, repo_root: Path, max_papers: int) -> dict[str, Any]:
    registry_paths = sorted({*search_root.glob("**/papers.jsonl"), *search_root.glob("**/paper_registry.jsonl")})
    metadata_paths = sorted(search_root.glob("**/*.metadata.json"))
    markdown_paths = sorted(
        path
        for path in search_root.glob("**/*.md")
        if "mineru-outputs" in str(path) or "inputs/mineru_markdown" in str(path)
    )
    content_list_paths = sorted(search_root.glob("**/*content_list*.json"))
    image_dirs = sorted(path for path in search_root.glob("**/images") if path.is_dir() and "mineru-outputs" in str(path))

    metadata_by_id = {path.stem.replace(".metadata", ""): path for path in metadata_paths}
    markdown_by_slug = index_markdown(markdown_paths)
    content_by_slug = index_content_lists(content_list_paths)
    images_by_slug = {path.parent.name: path for path in image_dirs}

    records: list[dict[str, Any]] = []
    for registry_path in registry_paths:
        for row in read_jsonl(registry_path):
            paper_id = str(row.get("paper_id") or "")
            if not paper_id:
                continue
            slug = str(row.get("slug") or "").strip()
            metadata_path = resolve_existing_path(row.get("metadata_path"), search_root, repo_root)
            if not metadata_path and paper_id in metadata_by_id:
                metadata_path = metadata_by_id[paper_id]
            metadata = load_json(metadata_path) if metadata_path else {}
            title = clean_field(row.get("title")) or clean_field(metadata.get("title"))
            year = clean_field(row.get("year")) or clean_field(metadata.get("year"))
            source_pdf = clean_field(row.get("source_pdf") or metadata.get("source_pdf_path") or metadata.get("source_file"))
            markdown_path = resolve_existing_path(row.get("markdown_path"), search_root, repo_root)
            if not markdown_path:
                markdown_path = markdown_by_slug.get(slug)
            if not markdown_path:
                markdown_path = markdown_by_slug.get(paper_id)
            content_path = resolve_existing_path(row.get("content_list_path"), search_root, repo_root)
            if not content_path:
                content_path = content_by_slug.get(slug)
            if not content_path:
                content_path = content_by_slug.get(paper_id)
            image_dir = images_by_slug.get(slug)
            missing = []
            if not title:
                missing.append("title")
            if not year:
                missing.append("year")
            if not metadata_path:
                missing.append("metadata_path")
            if not markdown_path:
                missing.append("mineru_markdown_path")
            if not content_path:
                missing.append("content_list_path")
            if not image_dir:
                missing.append("image_dir")
            score = completeness_score(metadata_path, markdown_path, content_path, image_dir, title, year)
            text_for_topic = " ".join([title or "", slug, json.dumps(extract_safe_tags(metadata), ensure_ascii=False)])
            topic_match = bool(ALLENE_RE.search(text_for_topic))
            records.append(
                {
                    "paper_id": paper_id,
                    "title": title,
                    "year": year,
                    "source_pdf_path": source_pdf,
                    "mineru_markdown_path": str(markdown_path) if markdown_path else "",
                    "content_list_path": str(content_path) if content_path else "",
                    "image_dir": str(image_dir) if image_dir else "",
                    "metadata_path": str(metadata_path) if metadata_path else "",
                    "completeness_score": score,
                    "missing_fields": missing,
                    "slug": slug,
                    "topic_match": topic_match,
                    "registry_path": str(registry_path),
                }
            )
    unique = dedupe_records(records)
    selected = [
        row for row in sorted(unique, key=lambda item: (item["topic_match"], item["completeness_score"], item["paper_id"]), reverse=True)
        if row["topic_match"] and row["mineru_markdown_path"] and row["metadata_path"]
    ][:max_papers]
    status = "ready" if len(selected) >= 3 else "blocked"
    missing_summary = summarize_missing(unique, selected)
    return {
        "status": status,
        "summary": f"{len(selected)} selected from {len(unique)} registry/metadata records",
        "search_root": str(search_root),
        "repo_root": str(repo_root),
        "asset_counts": {
            "registry_jsonl": len(registry_paths),
            "metadata_json": len(metadata_paths),
            "mineru_markdown": len(markdown_paths),
            "content_list_json": len(content_list_paths),
            "image_dirs": len(image_dirs),
        },
        "selected_papers": selected,
        "missing_summary": missing_summary,
        "safety": {
            "pdf_body_read": "not_read",
            "markdown_body_in_manifest": "not_included",
            "api_calls": "not_used",
            "uploads": "not_used",
            "qwen": "not_called",
            "mineru_api": "not_called",
            "image_api": "not_called",
        },
    }


def index_markdown(paths: list[Path]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in paths:
        if path.name == "full.md":
            out.setdefault(path.parent.name, path)
        else:
            out.setdefault(path.stem, path)
            out.setdefault(path.stem.split(".")[0], path)
    return out


def index_content_lists(paths: list[Path]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in paths:
        out.setdefault(path.parent.name, path)
        out.setdefault(path.stem.split(".")[0], path)
    return out


def resolve_existing_path(raw: Any, search_root: Path, repo_root: Path) -> Path | None:
    if not raw:
        return None
    raw_text = str(raw)
    candidates = [Path(raw_text)]
    if raw_text.startswith(LEGACY_REVIEW_ROOT):
        suffix = raw_text.removeprefix(LEGACY_REVIEW_ROOT)
        candidates.extend(
            [
                search_root / "review-writer old" / suffix,
                repo_root / suffix,
                search_root / "review-writer-data" / suffix,
            ]
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        return []
    return rows


def load_json(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def clean_field(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return clean_field(value["value"])
    if isinstance(value, list):
        return [clean_field(item) for item in value]
    if value is None:
        return ""
    return value


def extract_safe_tags(metadata: dict[str, Any]) -> dict[str, Any]:
    tags = metadata.get("structured_tags") or {}
    if not isinstance(tags, dict):
        return {}
    return {key: tags.get(key) for key in sorted(tags) if key in {"topic_tags", "method_tags", "reaction_tags", "compound_tags"}}


def completeness_score(
    metadata_path: Path | None,
    markdown_path: Path | None,
    content_path: Path | None,
    image_dir: Path | None,
    title: Any,
    year: Any,
) -> int:
    return sum(
        [
            bool(metadata_path),
            bool(markdown_path),
            bool(content_path),
            bool(image_dir),
            bool(title),
            bool(year),
        ]
    )


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in records:
        key = row["paper_id"]
        current = best.get(key)
        if current is None or row["completeness_score"] > current["completeness_score"]:
            best[key] = row
    return list(best.values())


def summarize_missing(records: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, Any]:
    all_missing: dict[str, int] = {}
    for row in records:
        for field in row.get("missing_fields", []):
            all_missing[field] = all_missing.get(field, 0) + 1
    return {
        "selected_count": len(selected),
        "missing_field_counts": dict(sorted(all_missing.items())),
        "blocked_reason": "" if len(selected) >= 3 else "Need at least 3 allene-related records with real MinerU markdown and metadata.",
    }


def build_input_package(repo_root: Path, report: dict[str, Any]) -> None:
    package = repo_root / "demo_projects/real_lite_allene_review"
    if package.exists():
        shutil.rmtree(package)
    for rel in [
        "inputs/paper_metadata",
        "inputs/mineru_markdown",
        "inputs/content_list",
        "inputs/figures",
        "outputs",
    ]:
        (package / rel).mkdir(parents=True, exist_ok=True)
    (package / "outputs/.gitkeep").write_text("", encoding="utf-8")
    (package / "README.md").write_text(
        "# Real-Lite Allene Review Input Package\n\n"
        "This package is generated by `scripts/demo/build_real_lite_manifest.py` from already parsed local assets. "
        "It does not include PDFs, full image directories, or API outputs.\n",
        encoding="utf-8",
    )
    (package / "inputs/topic.md").write_text(
        "# Real-Lite Topic\n\nAllene-based chiral ligands in asymmetric catalysis.\n",
        encoding="utf-8",
    )
    selected = [portable_selected_row(row) for row in report["selected_papers"]]
    write_json(package / "inputs/selected_papers.json", {"selected_papers": selected, "source_manifest": "/tmp/real_lite_asset_manifest.json"})
    with (package / "inputs/paper_registry.jsonl").open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    for source_row, row in zip(report["selected_papers"], selected):
        paper_id = row["paper_id"]
        metadata_path = Path(source_row["metadata_path"])
        if metadata_path.exists():
            metadata = load_json(metadata_path)
            write_json(package / "inputs/paper_metadata" / f"{paper_id}.metadata.json", sanitize_metadata(metadata, paper_id))
        markdown_path = Path(source_row["mineru_markdown_path"])
        if markdown_path.exists():
            excerpt = markdown_path.read_text(encoding="utf-8", errors="ignore")[:EXCERPT_CHARS]
            (package / "inputs/mineru_markdown" / f"{paper_id}.excerpt.md").write_text(
                f"<!-- source_path: <MINERU_MARKDOWN_ROOT>/{paper_id}/full.md -->\n<!-- trimmed_chars: {EXCERPT_CHARS} -->\n\n{excerpt}\n",
                encoding="utf-8",
            )
        write_json(
            package / "inputs/content_list" / f"{paper_id}.content_list.pointer.json",
            {
                "paper_id": paper_id,
                "source_path": f"<MINERU_CONTENT_LIST_ROOT>/{paper_id}/content_list.json",
                "copied_content": False,
                "reason": "Real-lite preflight stores pointer only to avoid committing large MinerU content_list outputs.",
            },
        )
        write_json(
            package / "inputs/figures" / f"{paper_id}.figures.pointer.json",
            {
                "paper_id": paper_id,
                "source_path": f"<MINERU_IMAGE_ROOT>/{paper_id}/images",
                "copied_images": False,
                "reason": "Real-lite preflight stores image directory pointer only.",
            },
        )


def portable_selected_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    paper_id = str(row.get("paper_id") or "paper")
    replacements = {
        "source_pdf_path": f"<PAPER_LIBRARY>/{paper_id}.pdf",
        "mineru_markdown_path": f"<MINERU_MARKDOWN_ROOT>/{paper_id}/full.md",
        "content_list_path": f"<MINERU_CONTENT_LIST_ROOT>/{paper_id}/content_list.json",
        "image_dir": f"<MINERU_IMAGE_ROOT>/{paper_id}/images",
        "metadata_path": f"<REVIEW_LIBRARY_METADATA>/{paper_id}.metadata.json",
        "registry_path": "<REVIEW_LIBRARY_REGISTRY>/papers.jsonl",
    }
    out.update(replacements)
    return out


def sanitize_metadata(metadata: dict[str, Any], paper_id: str) -> dict[str, Any]:
    out = json.loads(json.dumps(metadata, ensure_ascii=False))
    out["source_paths"] = {
        "pdf": f"<PAPER_LIBRARY>/{paper_id}.pdf",
        "markdown": f"<MINERU_MARKDOWN_ROOT>/{paper_id}/full.md",
        "content_list": f"<MINERU_CONTENT_LIST_ROOT>/{paper_id}/content_list.json",
        "extracted_dir": f"<MINERU_OUTPUT_ROOT>/{paper_id}",
    }
    if isinstance(out.get("quality"), dict):
        out["quality"]["manifest"] = "<MINERU_OUTPUT_ROOT>/manifest.json"
    extraction = out.get("extraction")
    if isinstance(extraction, dict) and isinstance(extraction.get("inputs"), dict):
        extraction["inputs"]["manifest"] = "<MINERU_OUTPUT_ROOT>/manifest.json"
    return out


def write_gap_report(repo_root: Path, report: dict[str, Any]) -> None:
    path = repo_root / "docs/demo/real_lite_asset_gap_report.md"
    lines = [
        "# Real-Lite Asset Gap Report",
        "",
        f"- status: {report['status']}",
        f"- summary: {report['summary']}",
        f"- blocked_reason: {report['missing_summary']['blocked_reason']}",
        "",
        "## Missing Field Counts",
        "",
    ]
    for key, value in report["missing_summary"]["missing_field_counts"].items():
        lines.append(f"- {key}: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Real-Lite Asset Manifest",
        "",
        f"- status: {report['status']}",
        f"- summary: {report['summary']}",
        f"- registry_jsonl: {report['asset_counts']['registry_jsonl']}",
        f"- metadata_json: {report['asset_counts']['metadata_json']}",
        f"- mineru_markdown: {report['asset_counts']['mineru_markdown']}",
        f"- content_list_json: {report['asset_counts']['content_list_json']}",
        f"- image_dirs: {report['asset_counts']['image_dirs']}",
        "",
        "## Selected Papers",
        "",
        "| paper_id | year | score | title | markdown | content_list | images |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for row in report["selected_papers"]:
        lines.append(
            "| {paper_id} | {year} | {score} | {title} | {md} | {cl} | {img} |".format(
                paper_id=row["paper_id"],
                year=row.get("year") or "",
                score=row["completeness_score"],
                title=str(row.get("title") or "").replace("|", "\\|")[:120],
                md="yes" if row.get("mineru_markdown_path") else "no",
                cl="yes" if row.get("content_list_path") else "no",
                img="yes" if row.get("image_dir") else "no",
            )
        )
    if not report["selected_papers"]:
        lines.append("| none |  |  |  |  |  |  |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- PDF body read: not_read",
            "- Markdown body in manifest: not_included",
            "- API calls: not_used",
            "- Uploads: not_used",
            "- Qwen: not_called",
            "- MinerU API: not_called",
            "- Image API: not_called",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
