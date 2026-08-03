#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from review_writer.acquisition.manual_archive import (  # noqa: E402
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_MEMBER_BYTES,
    DEFAULT_MAX_MEMBERS,
    DEFAULT_MAX_TOTAL_BYTES,
    ManualArchiveError,
    import_manual_archive,
)


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import one bounded researcher-provided source ZIP using deterministic manifest aliases."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-archive-bytes", type=positive_int, default=DEFAULT_MAX_ARCHIVE_BYTES)
    parser.add_argument("--max-members", type=positive_int, default=DEFAULT_MAX_MEMBERS)
    parser.add_argument("--max-member-bytes", type=positive_int, default=DEFAULT_MAX_MEMBER_BYTES)
    parser.add_argument("--max-total-bytes", type=positive_int, default=DEFAULT_MAX_TOTAL_BYTES)
    args = parser.parse_args()
    try:
        receipt = import_manual_archive(
            args.manifest,
            args.archive,
            args.output_root,
            max_archive_bytes=args.max_archive_bytes,
            max_members=args.max_members,
            max_member_bytes=args.max_member_bytes,
            max_total_bytes=args.max_total_bytes,
        )
    except (ManualArchiveError, OSError):
        print("error: manual archive import failed", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "counts": receipt["counts"],
                "unmatched_count": receipt["unmatched_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
