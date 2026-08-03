#!/usr/bin/env python3
"""Validate and atomically import a Content Agent candidate result."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.project.content_agent_handoff import (  # noqa: E402
    ContentAgentError,
    import_content_agent_result,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = json.loads(args.result.read_text(encoding="utf-8"))
        imported = import_content_agent_result(args.project, result)
    except (OSError, ValueError, json.JSONDecodeError, ContentAgentError) as exc:
        print(getattr(exc, "code", str(exc)), file=sys.stderr)
        return 1
    print(json.dumps(imported, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
