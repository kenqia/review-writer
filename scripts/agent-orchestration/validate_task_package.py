#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from orchestration_lib import validate_task_package


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_task_package.py TASK_DIRECTORY", file=sys.stderr)
        return 2
    result = validate_task_package(Path(sys.argv[1]))
    if result.errors:
        print("INVALID")
        print("\n".join(result.errors))
        return 1
    print("VALID task package")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
