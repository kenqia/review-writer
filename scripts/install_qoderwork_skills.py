#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "qoderwork" / "skills"
DEFAULT_TARGET = Path.home() / ".qoderwork" / "skills"
WINDOWS_TARGET = Path("/mnt/c/Users/26960/.qoderwork/skills")
WINDOWS_CN_TARGET = Path("/mnt/c/Users/26960/.qoderworkcn/skills")
WINDOWS_CN_PROJECT_TARGET = Path("/mnt/d/qodework/QoderWork CN/skills")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install review-writer QoderWork skills.")
    parser.add_argument("--skills-dir", type=Path, default=SOURCE)
    parser.add_argument("--target", type=Path, dest="target_dir", default=DEFAULT_TARGET)
    parser.add_argument("--target-dir", type=Path, dest="target_dir")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without copying files. This is the default.")
    parser.add_argument("--apply", action="store_true", help="Actually copy files. Default is dry-run.")
    parser.add_argument("--list-candidates", action="store_true", help="List likely QoderWork skill directories without copying files.")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run cannot be used together")
    return args


def list_candidates() -> None:
    candidates = [
        ("wsl", DEFAULT_TARGET.expanduser()),
        ("windows", WINDOWS_TARGET),
        ("windows-cn", WINDOWS_CN_TARGET),
        ("windows-cn-project", WINDOWS_CN_PROJECT_TARGET),
    ]
    for label, path in candidates:
        print(
            f"{label}: {path} "
            f"(exists={path.exists()}, parent_exists={path.parent.exists()}, skill_count={skill_count(path)})"
        )


def skill_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for child in path.iterdir() if child.is_dir() and (child / "SKILL.md").exists())


def main() -> int:
    args = parse_args()
    if args.list_candidates:
        list_candidates()
        return 0
    source = args.skills_dir.resolve()
    target = args.target_dir.expanduser()
    if not source.exists():
        raise SystemExit(f"missing source skill directory: {source}")
    skills = sorted(p for p in source.iterdir() if (p / "SKILL.md").exists())
    print(f"source: {source}")
    print(f"target: {target}")
    print(f"target exists: {target.exists()}")
    print(f"target parent exists: {target.parent.exists()}")
    print(f"mode: {'apply' if args.apply else 'dry-run'}")
    for skill in skills:
        dest = target / skill.name
        print(f"- {skill.name}: {skill} -> {dest} (exists={dest.exists()})")
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
