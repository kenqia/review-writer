#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

MANIFEST_OUTPUT = Path("/tmp/bailian_no_upload_corpus_manifest.json")
REQUIRED_ALLOWED_FIELDS = {
    "paper_id",
    "title",
    "year",
    "journal",
    "doi_draft",
    "role",
    "claim_draft",
    "figure_note_draft",
    "warning",
}
BLOCKED_TOKENS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    "raw_mineru_markdown",
    "full_pdf_text",
}
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{12,}|api[_-]?key\s*[:=]|token\s*[:=]|secret\s*[:=]|auth[_-]?token)",
    re.I,
)
ABS_PATH_RE = re.compile(r"(^|[\s\"'])((/[A-Za-z0-9_.-]+){2,}|[A-Za-z]:\\Users\\|/mnt/[a-z]/Users/)")


class PreflightError(Exception):
    pass


def main() -> int:
    args = parse_args()
    try:
        report = run_preflight(args.clean_root, args.config)
    except PreflightError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    print(
        "bailian-rag-preflight: "
        f"{report['status']} selected={report['selected_count']} "
        f"allowed={len(report['allowed_items'])} blocked={len(report['blocked_items'])}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Bailian RAG no-upload preflight.")
    parser.add_argument("--clean-root", type=Path, default=Path("demo_projects/clean_3paper_allene_review"))
    parser.add_argument("--config", type=Path, default=Path("rag/bailian/preflight_config.example.yaml"))
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_rag_preflight.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_rag_preflight.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_preflight(clean_root: Path, config_path: Path) -> dict[str, Any]:
    config = load_known_yaml(config_path)
    errors, risks = validate_config(config)
    papers = load_clean_papers(clean_root)
    claims = group_by(load_json(clean_root / "expected" / "expected_claims.draft.json").get("claims", []), "paper_id")
    figures = group_by(load_json(clean_root / "expected" / "expected_figures.draft.json").get("figure_notes", []), "paper_id")
    max_papers = int(config.get("max_papers", 0))
    selected = papers[:max_papers]
    if len(papers) > max_papers:
        risks.append(f"clean pack has {len(papers)} papers; manifest limited to {max_papers}")
    if len(selected) > 3:
        errors.append("selected corpus exceeds Phase 6a limit of 3 papers")

    manifest_items = [build_manifest_item(row, claims, figures, config) for row in selected]
    manifest = {
        "mode": "dry_run",
        "provider": "bailian",
        "region": config.get("region"),
        "no_upload": True,
        "selected_count": len(manifest_items),
        "upload_status": "not_uploaded",
        "api_used": False,
        "knowledge_base_created": False,
        "items": manifest_items,
        "safety": {
            "network": "not_used",
            "api": "not_used",
            "upload": "not_used",
            "knowledge_base": "not_created",
            "pdf_read": "not_used",
            "raw_images": "not_used",
            "qwen": "not_used",
            "mineru_api": "not_used",
        },
    }
    write_json(MANIFEST_OUTPUT, manifest)

    manifest_text = json.dumps(manifest, ensure_ascii=False)
    blocked_items = validate_manifest_items(manifest_items, manifest_text)
    errors.extend(issue["reason"] for issue in blocked_items)
    p403 = next((item for item in manifest_items if item.get("paper_id") == "P403"), None)
    if not p403:
        errors.append("P403 warning case is missing from manifest")
    elif "warning" not in p403 or not str(p403["warning"]).strip():
        errors.append("P403 warning was not preserved")

    allowed_items = [item["paper_id"] for item in manifest_items if item["paper_id"] not in {b["paper_id"] for b in blocked_items}]
    status = "fail" if errors else "warn" if risks else "pass"
    return {
        "status": status,
        "selected_count": len(manifest_items),
        "allowed_items": allowed_items,
        "blocked_items": blocked_items,
        "risks": risks,
        "errors": errors,
        "next_actions": next_actions(status),
        "manifest_path": str(MANIFEST_OUTPUT),
        "trusted_for_engineering_preflight": status != "fail",
        "trusted_for_scientific_quality": False,
        "safety": manifest["safety"],
    }


def validate_config(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    risks: list[str] = []
    expected = {
        "mode": "dry_run",
        "no_upload": True,
        "provider": "bailian",
        "max_papers": 3,
    }
    for key, value in expected.items():
        if config.get(key) != value:
            errors.append(f"config {key} must be {value!r}")
    allowed = set(config.get("allowed_fields") or [])
    if not REQUIRED_ALLOWED_FIELDS.issubset(allowed):
        errors.append("config allowed_fields is missing required no-upload fields")
    blocked = set(config.get("blocked_file_types") or [])
    for token in ["pdf", "png", "jpg", "jpeg", "webp", "raw_mineru_markdown", "full_pdf_text"]:
        if token not in blocked:
            errors.append(f"config blocked_file_types missing {token}")
    safety = config.get("safety") or {}
    for key in [
        "upload_requires_explicit_user_confirmation",
        "forbid_local_absolute_paths_in_manifest",
        "forbid_secrets",
        "forbid_raw_pdf",
        "forbid_raw_images",
        "preserve_needs_human_review",
        "preserve_trusted_for_scientific_quality_false",
    ]:
        if safety.get(key) is not True:
            errors.append(f"config safety.{key} must be true")
    retrieval = config.get("retrieval_eval_plan") or {}
    if retrieval.get("citation_required") is not True:
        errors.append("retrieval_eval_plan.citation_required must be true")
    if not Path(str(retrieval.get("expected_questions_file", ""))).exists():
        errors.append("retrieval_eval_plan expected questions file is missing")
    if config.get("workspace_id_env") != "BAILIAN_WORKSPACE_ID":
        risks.append("workspace_id_env differs from documented example")
    if config.get("api_key_env") != "DASHSCOPE_API_KEY":
        risks.append("api_key_env differs from documented example")
    return errors, risks


def load_clean_papers(clean_root: Path) -> list[dict[str, Any]]:
    path = clean_root / "inputs" / "selected_papers.clean_draft.json"
    if not path.exists():
        raise PreflightError(f"missing clean draft selection: {path}")
    payload = load_json(path)
    papers = payload.get("papers") or []
    if payload.get("trusted_for_scientific_quality") is not False:
        raise PreflightError("clean draft dataset must preserve trusted_for_scientific_quality=false")
    if payload.get("needs_human_review") is not True:
        raise PreflightError("clean draft dataset must preserve needs_human_review=true")
    if not papers:
        raise PreflightError("clean draft selection is empty")
    return papers


def build_manifest_item(
    row: dict[str, Any],
    claims_by_id: dict[str, list[dict[str, Any]]],
    figures_by_id: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, Any]:
    paper_id = str(row.get("paper_id") or row.get("candidate_id") or "")
    max_claim_chars = int(config.get("max_claim_chars_per_paper", 800))
    claim_text = " ".join(
        str(claim.get("claim_text_draft") or "").strip()
        for claim in claims_by_id.get(paper_id, [])
        if str(claim.get("claim_text_draft") or "").strip()
    )
    figure_text = " ".join(
        str(note.get("note_draft") or "").strip()
        for note in figures_by_id.get(paper_id, [])
        if str(note.get("note_draft") or "").strip()
    )
    warning_parts = []
    missing = row.get("missing_fields") or []
    conflicts = row.get("source_conflicts") or []
    if missing:
        warning_parts.append("missing fields: " + ", ".join(map(str, missing)))
    if conflicts:
        warning_parts.append("source conflicts require human review")
    warning_parts.append("not trusted for scientific quality")
    return {
        "paper_id": paper_id,
        "title": row.get("title") or row.get("title_draft") or paper_id,
        "year": row.get("year") or row.get("year_draft") or "unknown",
        "journal": row.get("journal") or row.get("journal_draft") or "unknown",
        "doi_draft": row.get("doi") or row.get("doi_draft") or "",
        "role": row.get("role") or "unknown",
        "claim_draft": claim_text[:max_claim_chars],
        "figure_note_draft": figure_text[:500],
        "warning": "; ".join(warning_parts),
        "upload_status": "not_uploaded",
        "api_used": False,
        "knowledge_base_created": False,
        "needs_human_review": True,
        "trusted_for_scientific_quality": False,
    }


def validate_manifest_items(items: list[dict[str, Any]], manifest_text: str) -> list[dict[str, str]]:
    blocked: list[dict[str, str]] = []
    if any(token in manifest_text.lower() for token in BLOCKED_TOKENS):
        blocked.append({"paper_id": "__manifest__", "reason": "manifest contains blocked file/text token"})
    if ABS_PATH_RE.search(manifest_text):
        blocked.append({"paper_id": "__manifest__", "reason": "manifest contains local absolute path"})
    if SECRET_RE.search(manifest_text):
        blocked.append({"paper_id": "__manifest__", "reason": "manifest contains secret-like value"})
    allowed_keys = REQUIRED_ALLOWED_FIELDS | {
        "upload_status",
        "api_used",
        "knowledge_base_created",
        "needs_human_review",
        "trusted_for_scientific_quality",
    }
    for item in items:
        paper_id = str(item.get("paper_id") or "unknown")
        extra = sorted(set(item) - allowed_keys)
        if extra:
            blocked.append({"paper_id": paper_id, "reason": f"manifest item contains unexpected fields: {extra}"})
        if item.get("upload_status") != "not_uploaded":
            blocked.append({"paper_id": paper_id, "reason": "upload_status must be not_uploaded"})
        if item.get("api_used") is not False:
            blocked.append({"paper_id": paper_id, "reason": "api_used must be false"})
        if item.get("knowledge_base_created") is not False:
            blocked.append({"paper_id": paper_id, "reason": "knowledge_base_created must be false"})
        if item.get("needs_human_review") is not True:
            blocked.append({"paper_id": paper_id, "reason": "needs_human_review must be true"})
        if item.get("trusted_for_scientific_quality") is not False:
            blocked.append({"paper_id": paper_id, "reason": "trusted_for_scientific_quality must be false"})
    return blocked


def load_known_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PreflightError(f"config not found: {path}")
    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not raw_line.startswith(" "):
            key, _, value = line.partition(":")
            current_key = key.strip()
            value = value.strip()
            if value:
                data[current_key] = parse_scalar(value)
            else:
                data[current_key] = [] if current_key in {"allowed_fields", "blocked_file_types"} else {}
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if current_key is None:
                raise PreflightError("invalid YAML list without parent key")
            data.setdefault(current_key, []).append(parse_scalar(stripped[2:].strip()))
        elif ":" in stripped:
            if current_key is None:
                raise PreflightError("invalid YAML mapping without parent key")
            key, _, value = stripped.partition(":")
            parent = data.setdefault(current_key, {})
            if not isinstance(parent, dict):
                raise PreflightError(f"invalid YAML mixed container: {current_key}")
            parent[key.strip()] = parse_scalar(value.strip())
    return data


def parse_scalar(value: str) -> Any:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


def group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key)), []).append(row)
    return grouped


def next_actions(status: str) -> list[str]:
    if status == "fail":
        return ["Fix blocking manifest/config issues before any RAG pilot."]
    return [
        "Review /tmp/bailian_no_upload_corpus_manifest.json manually.",
        "Keep this pack as no-upload engineering preflight only.",
        "Do not create a Bailian knowledge base until a later explicit authorization.",
    ]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PreflightError(f"missing required input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Bailian RAG No-upload Preflight",
        "",
        f"- status: `{report['status']}`",
        f"- selected_count: `{report['selected_count']}`",
        f"- manifest_path: `{report['manifest_path']}`",
        f"- allowed_items: `{', '.join(report['allowed_items'])}`",
        f"- blocked_items: `{len(report['blocked_items'])}`",
        f"- trusted_for_scientific_quality: `{report['trusted_for_scientific_quality']}`",
        "",
        "## Risks",
    ]
    lines.extend(f"- {risk}" for risk in report["risks"]) or lines.append("- none")
    lines.append("")
    lines.append("## Next Actions")
    lines.extend(f"- {action}" for action in report["next_actions"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

