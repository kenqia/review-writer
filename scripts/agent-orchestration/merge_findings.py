#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestration_lib import load_json, merge_findings, validate_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    reports = [load_json(path) for path in args.inputs]
    errors = [error for report in reports for error in validate_contract("findings", report)]
    if errors:
        print("\n".join(errors))
        return 1
    args.output.write_text(json.dumps(merge_findings(reports), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
