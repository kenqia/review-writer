#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from validation_core import sha256_file, verify_input_package


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues = verify_input_package(root)
    report = {
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "input_manifest_hash": sha256_file(root / "INPUT_MANIFEST.json") if (root / "INPUT_MANIFEST.json").is_file() else None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
