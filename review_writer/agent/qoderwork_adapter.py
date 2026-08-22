"""QoderWork CN adapter for the public Review Writer Agent entry.

QoderWork is a host Agent, not a second review engine.  This module keeps the
host-facing contract intentionally small: topic, an explicit project root and
an authorized PDF folder.  All durable state remains in the project root and
all review decisions remain in the existing Dashboard seams.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from review_writer.agent.fresh_bootstrap import (
    FreshAgentBootstrap,
    FreshAgentBootstrapError,
    _start_dashboard as _start_dashboard_process,
)
from review_writer.product_foundation import VersionContext


def start_review(*, topic: str, project_root: str | Path, authorized_pdf_folder: str | Path) -> dict[str, Any]:
    """Start one fresh review through the canonical Agent bootstrap."""
    return FreshAgentBootstrap(project_root).start(
        topic=topic,
        authorized_pdf_folder=authorized_pdf_folder,
    )


def resume_review(*, project_root: str | Path) -> dict[str, Any]:
    """Resume the project authority and return its owned Dashboard URL.

    The adapter deliberately does not edit VersionContext or make a scientific
    decision.  It only reopens the existing project-scoped Dashboard so the
    QoderWork host can continue the public human-gated flow.
    """
    root = Path(project_root).expanduser()
    context = VersionContext.load(root)
    state = context.state()
    dashboard_url, dashboard_pid = _start_dashboard_process(root.parent)
    current = context.view_version(state.current_version_id)
    return {
        "status": "RESUMED",
        "project_id": state.project_id,
        "project_root": str(root.resolve()),
        "dashboard_url": dashboard_url,
        "dashboard_pid": dashboard_pid,
        "current": {
            "version_id": current.version_id,
            "revision": state.revision,
            "snapshot_digest": current.snapshot_digest,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review Writer QoderWork CN adapter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="start a fresh review")
    start.add_argument("--topic", required=True)
    start.add_argument("--project-root", required=True)
    start.add_argument("--authorized-pdf-folder", required=True)
    resume = subparsers.add_parser("resume", help="reopen an existing review")
    resume.add_argument("--project-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "start":
            result = start_review(
                topic=args.topic,
                project_root=args.project_root,
                authorized_pdf_folder=args.authorized_pdf_folder,
            )
        else:
            result = resume_review(project_root=args.project_root)
    except (FreshAgentBootstrapError, OSError, ValueError) as exc:
        print(json.dumps({"status": "HOLD", "code": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
