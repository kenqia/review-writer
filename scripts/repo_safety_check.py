#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TRACKED_PATTERNS = (
    "skills/mineru-precise-parse-review-writer/config/mineru_api_token.txt",
    "review-library/metadata/",
    "review-library/registry/",
    "review-library/dashboard/",
    "mineru-outputs/",
    "review-projects/",
)

FORBIDDEN_TEXT_PATTERNS = (
    "/home/" + "ps/review-writer",
    "/home/" + "ps/",
)


def git_ls_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    tracked = git_ls_files()
    failures: list[str] = []
    for path in tracked:
        if path.endswith(".env") or "/.env" in path:
            failures.append(f"tracked env file: {path}")
        if any(path == pattern or path.startswith(pattern) for pattern in FORBIDDEN_TRACKED_PATTERNS):
            failures.append(f"tracked generated or secret-prone file: {path}")
        full_path = ROOT / path
        if full_path.is_file() and full_path.stat().st_size < 1_000_000:
            try:
                text = full_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            for pattern in FORBIDDEN_TEXT_PATTERNS:
                if pattern in text:
                    failures.append(f"hard-coded legacy path in tracked file: {path}")
                    break
    if failures:
        print("repo safety check failed:")
        for item in failures:
            print(f"- {item}")
        return 1
    print("repo safety check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
