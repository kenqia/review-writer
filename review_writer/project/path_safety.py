"""Standard-library-only portable source-path validation for M0."""
from __future__ import annotations
import re
from pathlib import Path

class PathSafetyError(ValueError): pass

def validate_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value) or value.startswith("//"):
        raise PathSafetyError("noncanonical or absolute path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts): raise PathSafetyError("dot/traversal path")
    return "/".join(parts)

def validate_source_file(root: Path, relative: str) -> Path:
    relative = validate_relative_path(relative); root = root.resolve(strict=True)
    candidate = root.joinpath(*relative.split("/"))
    if candidate.is_symlink(): raise PathSafetyError("source input is reparse point")
    actual = candidate.resolve(strict=True)
    try: actual.relative_to(root)
    except ValueError as exc: raise PathSafetyError("reparse escape") from exc
    if not actual.is_file(): raise PathSafetyError("not ordinary file")
    return actual
