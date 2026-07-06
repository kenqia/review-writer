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
    parser.add_argument("--skills-dir", type=Path, default=SOURCE)
    parser.add_argument("--target", type=Path, dest="target_dir", default=DEFAULT_TARGET)
    parser.add_argument("--target-dir", type=Path, dest="target_dir")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without copying files. This is the default.")
    parser.add_argument("--apply", action="store_true", help="Actually copy files. Default is dry-run.")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run cannot be used together")
    return args


def main() -> int:
    args = parse_args()
    source = args.skills_dir.resolve()
    target = args.target_dir.expanduser()
    if not source.exists():
        raise SystemExit(f"missing source skill directory: {source}")
    skills = sorted(p for p in source.iterdir() if (p / "SKILL.md").exists())
    print(f"source: {source}")
    print(f"target: {target}")
    print(f"mode: {'apply' if args.apply else 'dry-run'}")
    for skill in skills:
        dest = target / skill.name
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
