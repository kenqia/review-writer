#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from review_writer.acquisition.public_corpus import acquire_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire public MAIN/SI files from a frozen manifest without credentials or access-control circumvention.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true", help="Verify/import local files only; make no network requests.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-bytes", type=int, default=150 * 1024 * 1024)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()
    receipt = acquire_manifest(
        args.manifest,
        args.output_root,
        allow_network=not args.verify_only,
        timeout_seconds=args.timeout_seconds,
        max_bytes=args.max_bytes,
        retries=args.retries,
    )
    print(json.dumps({"manifest_sha256": receipt["manifest_sha256"], "counts": receipt["counts"], "manual_queue_count": receipt["manual_queue_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
