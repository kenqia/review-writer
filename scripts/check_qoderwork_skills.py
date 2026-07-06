#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


BROAD_DESCRIPTION_RE = re.compile(r"\b(all tasks|anything|always use|every request|any request)\b", re.I)
SECRET_VALUE_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{12,}|api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_-]{12,}|token\s*[:=]\s*['\"]?[A-Za-z0-9_-]{12,})"
)
FORBIDDEN_RE = re.compile(
    r"(?i)(auto\s+push|delete\s+~/.codex|rewrite\s+auth\.json|overwrite\s+~/.qoderwork/skills|upload\s+to\s+baidu\s+pan|source\s+token)"
)
DISALLOWED_ABSOLUTE_PATHS = (
    "/home/" + "ps/",
    "/mnt/c/" + "Users/",
    "C:" + "\\Users\\",
)
SCRIPT_REF_RE = re.compile(r"(?i)(scripts?/|make\s+|python\s+|deterministic script|validate_review_quality|final_audit_scan|project_status|install_qoderwork)")
HUMAN_RE = re.compile(r"(?i)(human checkpoint|human approval|human audit|human verification|human review|人工|人审)")
QUALITY_RE = re.compile(r"(?i)(quality gate|quality-check|quality report|validate_review_quality|final audit|质量)")
OFFLINE_RE = re.compile(r"(?i)(offline|dry-run|no real API|do not call real|local-only|deterministic|smoke)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check QoderWork skill pack metadata and safety.")
    parser.add_argument("--skills-dir", type=Path, default=Path("qoderwork/skills"))
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--strict", action="store_true", help="Return non-zero when errors are found.")
    return parser.parse_args()


def parse_frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    if not text.startswith("---\n"):
        return {}, ["missing_frontmatter"]
    end = text.find("\n---", 4)
    if end == -1:
        return {}, ["unterminated_frontmatter"]
    raw = text[4:end].strip()
    meta: dict[str, str] = {}
    for idx, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        if ":" not in line:
            errors.append(f"frontmatter_line_{idx}_missing_colon")
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, errors


def add_issue(target: list[dict[str, Any]], rule: str, path: Path, message: str) -> None:
    target.append({"rule": rule, "path": str(path), "message": message})


def check_skill(skill_dir: Path) -> dict[str, Any]:
    path = skill_dir / "SKILL.md"
    result: dict[str, Any] = {
        "skill": skill_dir.name,
        "path": str(path),
        "status": "pass",
        "frontmatter": False,
        "name": "",
        "description": "",
        "checks": {
            "trigger_clear": False,
            "human_checkpoint": False,
            "quality_gate": False,
            "offline_smoke": False,
            "scripts_reference": False,
        },
        "errors": [],
        "warnings": [],
    }
    errors: list[dict[str, Any]] = result["errors"]
    warnings: list[dict[str, Any]] = result["warnings"]
    if not path.exists():
        add_issue(errors, "missing_skill_md", path, "SKILL.md is missing")
        result["status"] = "fail"
        return result
    text = path.read_text(encoding="utf-8", errors="ignore")
    meta, fm_errors = parse_frontmatter(text)
    result["frontmatter"] = bool(meta) and not fm_errors
    for err in fm_errors:
        add_issue(errors, err, path, "frontmatter is not parseable")
    name = meta.get("name", "").strip()
    description = meta.get("description", "").strip()
    result["name"] = name
    result["description"] = description
    if not name:
        add_issue(errors, "missing_name", path, "frontmatter name is required")
    if not description:
        add_issue(errors, "missing_description", path, "frontmatter description is required")
    elif len(description) < 40:
        add_issue(errors, "description_too_short", path, "description should include a clear trigger condition")
    if description and not re.search(r"\b(use when|when|after|before)\b", description, re.I):
        add_issue(warnings, "description_trigger_unclear", path, "description should say when the skill should trigger")
    else:
        result["checks"]["trigger_clear"] = bool(description)
    if BROAD_DESCRIPTION_RE.search(description):
        add_issue(errors, "description_too_broad", path, "description appears too broad and may over-trigger")
    for match in SECRET_VALUE_RE.finditer(text):
        add_issue(errors, "secret_like_value", path, f"secret-like value near character {match.start()}")
    if FORBIDDEN_RE.search(text):
        add_issue(errors, "forbidden_operation_text", path, "contains forbidden operation wording")
    if any(pattern in text for pattern in DISALLOWED_ABSOLUTE_PATHS):
        add_issue(errors, "disallowed_absolute_path", path, "contains disallowed machine-specific absolute path")
    result["checks"]["human_checkpoint"] = bool(HUMAN_RE.search(text))
    result["checks"]["quality_gate"] = bool(QUALITY_RE.search(text))
    result["checks"]["offline_smoke"] = bool(OFFLINE_RE.search(text))
    result["checks"]["scripts_reference"] = bool(SCRIPT_REF_RE.search(text))
    for key, rule, message in [
        ("human_checkpoint", "missing_human_checkpoint", "must explicitly preserve human checkpoints"),
        ("quality_gate", "missing_quality_gate", "must explicitly mention quality gates or quality checks"),
        ("offline_smoke", "missing_offline_smoke", "must explicitly mention offline/dry-run/no-real-API behavior"),
        ("scripts_reference", "missing_scripts_reference", "should route deterministic work to scripts or Makefile targets"),
    ]:
        if not result["checks"][key]:
            add_issue(errors, rule, path, message)
    if errors:
        result["status"] = "fail"
    elif warnings:
        result["status"] = "warn"
    return result


def build_report(skills_dir: Path) -> dict[str, Any]:
    skills_dir = skills_dir.resolve()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    skill_results: list[dict[str, Any]] = []
    if not skills_dir.exists():
        errors.append({"rule": "missing_skills_dir", "path": str(skills_dir), "message": "skills directory does not exist"})
    else:
        dirs = sorted(path for path in skills_dir.iterdir() if path.is_dir())
        if not dirs:
            errors.append({"rule": "empty_skills_dir", "path": str(skills_dir), "message": "no skill directories found"})
        for skill_dir in dirs:
            result = check_skill(skill_dir)
            skill_results.append(result)
            errors.extend(result["errors"])
            warnings.extend(result["warnings"])
    status = "fail" if errors else "warn" if warnings else "pass"
    return {
        "status": status,
        "skills_dir": str(skills_dir),
        "summary": {
            "skills": len(skill_results),
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "skills": skill_results,
        "errors": errors,
        "warnings": warnings,
    }


def write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_md(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# QoderWork Skill Check",
        "",
        f"- Status: {report['status']}",
        f"- Skills directory: `{report['skills_dir']}`",
        f"- Skills: {report['summary']['skills']}",
        f"- Errors: {report['summary']['errors']}",
        f"- Warnings: {report['summary']['warnings']}",
        "",
        "| skill | status | trigger | human checkpoint | quality gate | offline smoke | scripts | errors | warnings |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for skill in report["skills"]:
        checks = skill["checks"]
        lines.append(
            "| {skill} | {status} | {trigger} | {human} | {quality} | {offline} | {scripts} | {errors} | {warnings} |".format(
                skill=skill["skill"],
                status=skill["status"],
                trigger="yes" if checks["trigger_clear"] else "no",
                human="yes" if checks["human_checkpoint"] else "no",
                quality="yes" if checks["quality_gate"] else "no",
                offline="yes" if checks["offline_smoke"] else "no",
                scripts="yes" if checks["scripts_reference"] else "no",
                errors=len(skill["errors"]),
                warnings=len(skill["warnings"]),
            )
        )
    if report["errors"]:
        lines += ["", "## Errors", ""]
        for issue in report["errors"]:
            lines.append(f"- `{issue['rule']}` in `{issue['path']}`: {issue['message']}")
    if report["warnings"]:
        lines += ["", "## Warnings", ""]
        for issue in report["warnings"]:
            lines.append(f"- `{issue['rule']}` in `{issue['path']}`: {issue['message']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    report = build_report(args.skills_dir)
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_md(args.output_md, report)
    print(f"qoderwork skill check {report['status']}: {report['summary']['skills']} skills, {report['summary']['errors']} errors, {report['summary']['warnings']} warnings")
    return 1 if args.strict and report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
