#!/usr/bin/env python3
"""Validate the task-local assignment registry without invoking Codex."""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestration_lib import load_json, validate_assignments


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("assignments", type=Path)
    args = parser.parse_args()
    errors = validate_assignments(load_json(args.assignments))
    if errors:
        print("INVALID assignments")
        print("\n".join(errors))
        return 1
    print("VALID assignments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
