#!/usr/bin/env python3
"""Create a clean three-paper project without carrying legacy downstream state."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any


COPY_ROOTS = (
    Path("00_brief"),
    Path("00_discovery"),
    Path("00_sources"),
    Path("01_evidence/mineru"),
    Path("01_evidence/parses"),
    Path("01_evidence/text_layers"),
)
FORBIDDEN_ROOTS = (
    Path("01_evidence/evidence_cards.jsonl"),
    Path("02_claims"),
    Path("03_review"),
    Path("03_figure_redraw"),
    Path("04_first_draft"),
    Path("05_final_audit"),
)
REQUIRED_FILES = (
    Path("00_sources/acquisition_final_receipt.json"),
    Path("01_evidence/mineru/manifest.json"),
    Path("01_evidence/parses/manifest.json"),
    Path("01_evidence/text_layers/text_layers.manifest.json"),
)


class BootstrapError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _is_reparse(path: Path) -> bool:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(attributes & reparse_flag)
    except OSError:
        return False


def _validate_tree(root: Path) -> None:
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise BootstrapError("SOURCE_MISSING") from exc
    if _is_reparse(root) or not stat.S_ISDIR(root_stat.st_mode):
        raise BootstrapError("SOURCE_REPARSE_POINT")
    for path in root.rglob("*"):
        if _is_reparse(path):
            raise BootstrapError("SOURCE_REPARSE_POINT")
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise BootstrapError("SOURCE_INVALID") from exc
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise BootstrapError("SOURCE_INVALID")


def _validate_copy(project: Path) -> dict[str, Any]:
    for relative in REQUIRED_FILES:
        if not (project / relative).is_file():
            raise BootstrapError("REQUIRED_INPUT_MISSING")
    for relative in FORBIDDEN_ROOTS:
        if os.path.lexists(project / relative):
            raise BootstrapError("LEGACY_OUTPUT_COPIED")
    papers = sorted((project / "00_sources/papers").glob("*.pdf"))
    if len(papers) != 3 or not all(path.is_file() for path in papers):
        raise BootstrapError("THREE_PAPERS_REQUIRED")
    return {
        "project_id": project.name,
        "pdf_count": len(papers),
        "copied_roots": [relative.as_posix() for relative in COPY_ROOTS],
        "legacy_outputs_copied": False,
    }


def _rewrite_project_identity(project: Path, project_id: str) -> None:
    state_path = project / "00_brief/review_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("REVIEW_STATE_INVALID") from exc
    if not isinstance(state, dict):
        raise BootstrapError("REVIEW_STATE_INVALID")
    state["project_id"] = project_id
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


def create_complete_loop_project(source: Path, target: Path) -> dict[str, Any]:
    source = Path(source)
    target = Path(target)
    if os.path.lexists(target):
        raise BootstrapError("TARGET_EXISTS")
    _validate_tree(source)
    try:
        source_root = source.resolve(strict=True)
    except OSError as exc:
        raise BootstrapError("SOURCE_MISSING") from exc
    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target_parent))
    published = False
    try:
        for relative in COPY_ROOTS:
            source_path = source_root / relative
            if not source_path.exists():
                continue
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_path, destination, copy_function=shutil.copy2)
        _rewrite_project_identity(temporary, target.name)
        result = _validate_copy(temporary)
        os.replace(temporary, target)
        published = True
        return {**result, "project_id": target.name, "target_created": True}
    except BootstrapError:
        raise
    except OSError as exc:
        raise BootstrapError("BOOTSTRAP_WRITE_FAILED") from exc
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a clean three-paper evidence-to-release project.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result = create_complete_loop_project(args.source, args.target)
    except BootstrapError as exc:
        print(json.dumps({"status": "ERROR", "reason_code": exc.code}, sort_keys=True))
        return 2
    print(json.dumps({"status": "CREATED", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
