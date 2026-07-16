#!/usr/bin/env python3
"""Offline content gate; it never invokes Codex or a network client."""

from __future__ import annotations

import ast
import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from orchestration_lib import (
    REPO_ROOT,
    ROLES,
    load_json,
    validate_assignments,
    validate_contract,
    validate_role_policy,
    validate_task_package,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-directory", default="docs/agent-tasks/ORCH-001")
    args = parser.parse_args(argv)
    task_dir = (REPO_ROOT / args.task_directory).resolve()
    errors = list(validate_role_policy(REPO_ROOT).errors)
    errors.extend(validate_task_package(task_dir).errors)
    errors.extend(validate_assignments(load_json(task_dir / "agent_assignments.json")))
    for role in sorted(ROLES):
        descriptor = f".codex/agents/{role}.toml"
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--", descriptor],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if ignored.returncode == 0:
            errors.append(f"required role descriptor is ignored: {descriptor}")
        elif ignored.returncode != 1:
            errors.append(
                f"could not determine ignore status for {descriptor}: {ignored.stderr.strip()}"
            )
    for schema in (REPO_ROOT / "docs" / "agent-contracts" / "schemas").glob("*.json"):
        try:
            import json
            json.loads(schema.read_text(encoding="utf-8"))
        except Exception as error:  # pragma: no cover - defensive gate
            errors.append(f"invalid schema {schema}: {error}")
    for name in ("findings", "worker_result"):
        import json
        payload = json.loads((REPO_ROOT / "docs" / "agent-contracts" / "examples" / f"{name}.example.json").read_text(encoding="utf-8"))
        errors.extend(validate_contract(name, payload))
        template = json.loads((REPO_ROOT / "docs" / "agent-contracts" / "templates" / f"{name.upper()}.template.json").read_text(encoding="utf-8"))
        errors.extend(validate_contract(name, template))
    for path in (REPO_ROOT / "scripts" / "agent-orchestration").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run":
                for keyword in node.keywords:
                    if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                        errors.append(f"shell=True is forbidden: {path}")
    scan_roots = [REPO_ROOT / name for name in ("docs/agent-orchestration", "docs/agent-contracts", "docs/agent-roles", "docs/agent-tasks", "scripts/agent-orchestration", ".codex/agents")]
    leaked_session = re.compile(r'(?:session_id|session|thread_id|thread)"?\s*[:=]\s*"[A-Za-z0-9._-]{12,}"')
    for root in scan_roots:
        for path in root.rglob("*") if root.exists() else []:
            if not path.is_file() or ".agent-orchestration-runs" in path.parts:
                continue
            ignored = subprocess.run(["git", "check-ignore", "-q", "--", str(path.relative_to(REPO_ROOT))], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
            if ignored.returncode == 0:
                continue
            if leaked_session.search(path.read_text(encoding="utf-8", errors="replace")):
                errors.append(f"orchestration content leaks a session reference: {path.relative_to(REPO_ROOT)}")
    if (REPO_ROOT / ".agent-orchestration-runs").exists() and "/.agent-orchestration-runs/" not in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8"):
        errors.append("runtime directory is not ignored")
    if errors:
        print("INVALID orchestration gate")
        print("\n".join(errors))
        return 1
    print("VALID offline orchestration gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
