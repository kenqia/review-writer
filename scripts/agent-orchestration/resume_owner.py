#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from orchestration_lib import REPO_ROOT, build_resume_command, run_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit original Owner resume launcher")
    parser.add_argument("task_directory")
    parser.add_argument("session_reference", nargs="?")
    parser.add_argument("--session-file", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-workspace-write", action="store_true")
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--reasoning-effort", default="medium")
    args = parser.parse_args()
    if bool(args.session_reference) == bool(args.session_file):
        parser.error("provide exactly one private session reference or --session-file")
    session_reference = args.session_reference or args.session_file.read_text(encoding="utf-8").strip()
    return run_plan(build_resume_command(Path(args.task_directory), session_reference, execute=args.execute, allow_workspace_write=args.allow_workspace_write, model=args.model, reasoning_effort=args.reasoning_effort), REPO_ROOT / ".agent-orchestration-runs" / "owner")


if __name__ == "__main__":
    raise SystemExit(main())
