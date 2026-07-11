from __future__ import annotations

from pathlib import Path
from typing import Any


def load_provider_config(path: str | Path) -> dict[str, Any]:
    """Load the small YAML subset used by config/providers.example.yaml.

    This intentionally avoids a PyYAML dependency for offline smoke tests. It
    supports nested mappings with two-space indentation and scalar values.
    """

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"provider config not found: {config_path}")
    return _parse_simple_yaml(config_path.read_text(encoding="utf-8"))


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        if indent % 2:
            raise ValueError(f"invalid indentation at line {line_number}")
        stripped = line_without_comment.strip()
        if ":" not in stripped:
            raise ValueError(f"expected key/value pair at line {line_number}")
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value_text = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"invalid nesting at line {line_number}")
        parent = stack[-1][1]
        if value_text == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value_text)
    return root


def _parse_scalar(value: str) -> Any:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(value)
    except ValueError:
        return value
