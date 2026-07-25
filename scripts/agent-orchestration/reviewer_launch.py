#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from orchestration_lib import REPO_ROOT, build_reviewer_command, run_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Fresh read-only reviewer launcher")
    parser.add_argument("task_directory")
    parser.add_argument("role", choices=["scientific-reviewer", "artifact-reviewer", "final-verifier", "explorer"])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--reasoning-effort", default="medium")
    args = parser.parse_args()
    return run_plan(build_reviewer_command(Path(args.task_directory), args.role, execute=args.execute, model=args.model, reasoning_effort=args.reasoning_effort), REPO_ROOT / ".agent-orchestration-runs" / "reviews")


if __name__ == "__main__":
    raise SystemExit(main())
