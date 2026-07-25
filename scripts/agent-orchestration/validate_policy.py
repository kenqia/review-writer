#!/usr/bin/env python3
from __future__ import annotations

import sys

from orchestration_lib import REPO_ROOT, validate_role_policy


def main() -> int:
    result = validate_role_policy(REPO_ROOT)
    if result.errors:
        print("INVALID role policy")
        print("\n".join(result.errors))
        return 1
    print("VALID role policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
