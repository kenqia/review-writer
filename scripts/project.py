#!/usr/bin/env python3
"""Minimum offline `project validate` and `project status` entrypoint."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.project.manifest import (  # noqa: E402
    CONFIG_AFFECTED_STAGES,
    ManifestResolutionError,
    load_resolved_project_manifest,
)
from review_writer.project.contract import ContractError, snapshot_view, validate_manifest_inputs, validate_snapshot_package  # noqa: E402


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _read_snapshot_hash(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestResolutionError("CONFIG_SNAPSHOT_UNREADABLE", str(exc)) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("resolved_config_sha256"), str):
        raise ManifestResolutionError(
            "CONFIG_SNAPSHOT_HASH_MISSING",
            "snapshot must contain resolved_config_sha256",
        )
    snapshot_hash = payload["resolved_config_sha256"]
    if not SHA256_RE.fullmatch(snapshot_hash):
        raise ManifestResolutionError("CONFIG_SNAPSHOT_HASH_INVALID", "snapshot config hash must be lowercase SHA-256")
    return snapshot_hash


def _validate_report(manifest_path: Path) -> dict[str, Any]:
    try:
        editable = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestResolutionError("PROJECT_MANIFEST_UNREADABLE", str(exc)) from exc
    resolved = validate_manifest_inputs(editable, manifest_path.parent)
    from review_writer.project.manifest import resolved_config_sha256
    config_hash = resolved_config_sha256({key: value for key, value in resolved.items() if key != "source_hashes"})
    return {
        "status": "VALID",
        "validation_scope": "PROJECT_MANIFEST_AND_RESOLVED_CONFIG",
        "project_id": resolved["project_id"],
        "resolved_config_sha256": config_hash,
        "source_hashes": resolved["source_hashes"],
    }


def _status_report(manifest_path: Path, snapshot_path: Path) -> dict[str, Any]:
    validate = _validate_report(manifest_path)
    resolved, config_hash = load_resolved_project_manifest(manifest_path)
    snapshot_hash = _read_snapshot_hash(snapshot_path)
    changed = config_hash != snapshot_hash
    report = {
        "status": "CONFIG_CHANGED" if changed else "CONFIG_CURRENT",
        "status_scope": "RESOLVED_CONFIG_ONLY",
        "project_id": resolved["project_id"],
        "resolved_config_sha256": config_hash,
        "snapshot_config_sha256": snapshot_hash,
        "affected_stages": list(CONFIG_AFFECTED_STAGES) if changed else [],
    }
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        package = payload.get("snapshot_package")
        if not isinstance(package, dict):
            raise ManifestResolutionError("CONFIG_SNAPSHOT_PACKAGE_REQUIRED", "status requires one sealed snapshot_package")
        package_view = validate_snapshot_package(package)
        report["snapshot_summary"] = package_view["summary"]
        report["closure"] = {"closed": package_view["closed"]}
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ManifestResolutionError("CONFIG_SNAPSHOT_CLOSURE_INVALID", str(exc)) from exc
    report["source_hashes"] = validate["source_hashes"]
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and inspect the minimum local project contract")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate and resolve one editable ProjectManifest")
    validate.add_argument("--manifest", type=Path, required=True)

    status = subparsers.add_parser("status", help="Compare current resolved config with an immutable snapshot")
    status.add_argument("--manifest", type=Path, required=True)
    status.add_argument("--snapshot", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            report = _validate_report(args.manifest)
        else:
            report = _status_report(args.manifest, args.snapshot)
    except (ManifestResolutionError, ContractError) as exc:
        print(json.dumps({"status": "INVALID", "error_code": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
