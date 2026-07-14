#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from validation_core import validate_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate V3.1.1 Layer B exact-claim results.")
    parser.add_argument("--results", type=Path, default=Path("output/results.jsonl"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    results = args.results if args.results.is_absolute() else root / args.results
    issues, stats = validate_results(root, results)
    report = {"status": "PASS" if not issues else "FAIL", "issues": issues, **stats}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
