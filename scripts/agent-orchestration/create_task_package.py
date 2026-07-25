#!/usr/bin/env python3
"""Create a minimal safe task package without invoking a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestration_lib import REPO_ROOT, is_safe_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--objective", required=True)
    args = parser.parse_args()
    if not args.task_id.isupper() or not is_safe_path(args.task_id):
        parser.error("task_id must be a safe uppercase identifier")
    task_dir = REPO_ROOT / "docs" / "agent-tasks" / args.task_id
    if task_dir.exists():
        parser.error("task package already exists")
    task_dir.mkdir(parents=True)
    task = {"task_id": args.task_id, "objective": args.objective, "background": "Define before execution.", "frozen_decisions": ["No fallback."], "allowed_paths": ["docs/agent-tasks/"], "forbidden_paths": [".env"], "inputs": ["Leader task package"], "required_outputs": ["Validated task package"], "acceptance_criteria": ["Acceptance matrix is complete."], "verification_commands": ["python3 scripts/agent-orchestration/validate_task_package.py"], "safety_boundaries": ["No nested codex exec."], "network_policy": "Offline by default.", "model_policy": "No fallback.", "stop_conditions": ["Scope expands."], "human_checkpoint": "Leader review required."}
    matrix = {"task_id": args.task_id, "items": [{"id": f"{args.task_id}-A01", "requirement": "Define acceptance", "evidence_required": "Recorded offline result", "verification_command": "python3 scripts/agent-orchestration/validate_task_package.py", "expected_result": "exit 0", "owner": "Implementation Owner", "status": "pending", "severity": "blocker"}]}
    (task_dir / "task_spec.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    (task_dir / "acceptance_matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    print(task_dir.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
