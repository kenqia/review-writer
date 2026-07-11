#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "offline-ci.yml"
REQUIREMENTS = REPO_ROOT / "requirements-ci.txt"

REQUIRED_TEXT = [
    "name: Offline CI",
    "pull_request:",
    "push:",
    "branches:",
    "feat/chem-review-quality-gates",
    "feat/orchestrator-rag-generation-pilot",
    "permissions:",
    "contents: read",
    "python-version: '3.11'",
    "python -m pip install -r requirements-ci.txt",
    "make offline-ci-workflow-check",
    "make release-readiness-check",
    "make bailian-phase6-final-check BAILIAN_SDK_PYTHON=python",
    "make portability-check",
]

FORBIDDEN_TEXT = [
    "secrets.",
    "actions/upload-artifact",
    "--allow-network",
    "--allow-upload",
    "real-command",
    "deploy",
]


def main() -> int:
    failures: list[str] = []
    if not WORKFLOW.exists():
        failures.append(f"missing workflow: {WORKFLOW.relative_to(REPO_ROOT)}")
        return report(failures)
    if not REQUIREMENTS.exists():
        failures.append(f"missing requirements: {REQUIREMENTS.relative_to(REPO_ROOT)}")

    text = WORKFLOW.read_text(encoding="utf-8")
    for needle in REQUIRED_TEXT:
        if needle not in text:
            failures.append(f"workflow missing required text: {needle}")
    lowered = text.lower()
    for needle in FORBIDDEN_TEXT:
        if needle.lower() in lowered:
            failures.append(f"workflow contains forbidden text: {needle}")

    for structural in ["on:", "jobs:", "steps:", "runs-on: ubuntu-latest"]:
        if structural not in text:
            failures.append(f"workflow missing structural key: {structural}")

    return report(failures)


def report(failures: list[str]) -> int:
    if failures:
        for failure in failures:
            print(f"offline-ci-workflow-check: FAIL {failure}", file=sys.stderr)
        return 1
    print("offline-ci-workflow-check: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
