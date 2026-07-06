#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "qoderwork" / "skills"
DEFAULT_TARGET = Path.home() / ".qoderwork" / "skills"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install review-writer QoderWork skills.")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--apply", action="store_true", help="Actually copy files. Default is dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not SOURCE.exists():
        raise SystemExit(f"missing source skill directory: {SOURCE}")
    skills = sorted(p for p in SOURCE.iterdir() if (p / "SKILL.md").exists())
    print(f"source: {SOURCE}")
    print(f"target: {args.target}")
    print(f"mode: {'apply' if args.apply else 'dry-run'}")
    for skill in skills:
        dest = args.target / skill.name
        print(f"- {skill.name}: {skill} -> {dest}")
        if args.apply:
            if dest.exists():
                raise SystemExit(f"refusing to overwrite existing skill: {dest}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill, dest)
    if not args.apply:
        print("No files were copied. Re-run with --apply only after explicit confirmation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
