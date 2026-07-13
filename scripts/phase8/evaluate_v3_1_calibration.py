#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.v3_1_source_first import evaluate_v3_1_calibration


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a V3.1 calibration result against coordinator-private gold.")
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_v3_1_calibration(args.run_root)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["status"] == "PASS" else 1
    except Exception as exc:
        print(f"phase8-v3.1-calibration: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
