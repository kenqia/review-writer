#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from orchestration_lib import REPO_ROOT, build_owner_command, run_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview-first Implementation Owner launcher")
    parser.add_argument("task_directory")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-workspace-write", action="store_true")
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--reasoning-effort", default="medium")
    args = parser.parse_args()
    plan = build_owner_command(Path(args.task_directory), execute=args.execute, workspace_write=args.allow_workspace_write, allow_workspace_write=args.allow_workspace_write, model=args.model, reasoning_effort=args.reasoning_effort)
    return run_plan(plan, REPO_ROOT / ".agent-orchestration-runs" / "owner")


if __name__ == "__main__":
    raise SystemExit(main())
