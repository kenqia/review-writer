#!/usr/bin/env python3
"""Minimum offline project entrypoint.

The public M0 path is intentionally small: initialize a local project, validate
its editable manifest, and compare that manifest with an existing immutable
snapshot. This command never reads PDF semantics, calls a provider, or creates
scientific claims.
"""

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
    resolved_config_sha256,
)
from review_writer.project.contract import ContractError, validate_manifest_inputs, validate_snapshot_package  # noqa: E402


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_NAME = "project.manifest.json"


def _parse_source_spec(value: str) -> dict[str, str]:
    """Parse one explicit ``SOURCE_ID:PAPER_ID:ROLE:RELATIVE_PATH`` value."""

    parts = value.split(":", 3)
    if len(parts) != 4 or any(not part.strip() for part in parts):
        raise ManifestResolutionError(
            "SOURCE_SPEC_INVALID",
            "--source must use SOURCE_ID:PAPER_ID:MAIN|SI:relative/path",
        )
    source_id, paper_id, document_role, relative_path = (part.strip() for part in parts)
    if document_role not in {"MAIN", "SI"}:
        raise ManifestResolutionError(
            "SOURCE_SPEC_INVALID",
            "source document role must be MAIN or SI",
        )
    return {
        "source_id": source_id,
        "paper_id": paper_id,
        "relative_path": relative_path,
        "document_role": document_role,
        "usage_role": "EVIDENCE",
    }


def _init_report(args: argparse.Namespace) -> dict[str, Any]:
    """Create one new project skeleton without overwriting user files."""

    project_root = args.project_root.expanduser()
    if project_root.exists() and not project_root.is_dir():
        raise ManifestResolutionError("PROJECT_ROOT_NOT_DIRECTORY", f"project root is not a directory: {project_root}")
    manifest_path = project_root / MANIFEST_NAME
    if manifest_path.exists():
        raise ManifestResolutionError("PROJECT_MANIFEST_EXISTS", f"refusing to overwrite: {manifest_path}")

    try:
        project_root.mkdir(parents=True, exist_ok=True)
        for relative in ("inputs/papers", "outputs/project-state", "exports"):
            (project_root / relative).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ManifestResolutionError("PROJECT_ROOT_CREATE_FAILED", str(exc)) from exc

    manifest = {
        "manifest_schema_version": "project-manifest-1.0",
        "project_id": args.project_id,
        "project_title": args.project_title,
        "initial_user_intent": {"goal": args.goal, "scope": args.scope},
        "discovery_policy": "CLOSED_CORPUS",
        "output_language": "en",
        "citation_style": "BRACKETED_NUMERIC",
        "paths": {
            "seed_source_root": "inputs/papers",
            "project_data_root": "outputs/project-state",
            "export_root": "exports",
        },
        "initial_source_inputs": [_parse_source_spec(value) for value in args.source],
        "network_policy": "OFFLINE_ONLY",
    }
    resolved = validate_manifest_inputs(manifest, project_root)
    config_hash = resolved_config_sha256({key: value for key, value in resolved.items() if key != "source_hashes"})
    try:
        with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise ManifestResolutionError("PROJECT_MANIFEST_EXISTS", f"refusing to overwrite: {manifest_path}") from exc
    except OSError as exc:
        raise ManifestResolutionError("PROJECT_MANIFEST_WRITE_FAILED", str(exc)) from exc
    return {
        "status": "INITIALIZED",
        "project_id": resolved["project_id"],
        "manifest": str(manifest_path),
        "source_count": len(resolved["initial_source_inputs"]),
        "source_hashes": resolved["source_hashes"],
        "resolved_config_sha256": config_hash,
        "next_step": f"python3 scripts/project.py validate --manifest {manifest_path}",
    }


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
        if package.get("resolved_config_sha256") != snapshot_hash:
            raise ManifestResolutionError("CONFIG_SNAPSHOT_PACKAGE_DRIFT", "sealed package config hash differs from outer snapshot")
        if package.get("project_id") != validate["project_id"]:
            raise ManifestResolutionError("CONFIG_SNAPSHOT_PROJECT_DRIFT", "sealed package project differs from manifest")
        package_sources = {source.get("source_id"): source.get("content_sha256") for source in package.get("sources", [])}
        if package_sources != validate["source_hashes"]:
            raise ManifestResolutionError("CONFIG_SNAPSHOT_CORPUS_DRIFT", "sealed package sources differ from closed corpus")
        report["snapshot_summary"] = package_view["summary"]
        report["closure"] = {"closed": package_view["closed"]}
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ManifestResolutionError("CONFIG_SNAPSHOT_CLOSURE_INVALID", str(exc)) from exc
    report["source_hashes"] = validate["source_hashes"]
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize, validate, and inspect the minimum local project contract")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create a new local project manifest and standard directories")
    init.add_argument("--project-root", type=Path, required=True, help="Directory for the new project")
    init.add_argument("--project-id", required=True, help="Stable ASCII project identifier")
    init.add_argument("--project-title", required=True, help="Human-readable project title")
    init.add_argument("--goal", required=True, help="What the user wants to learn from the supplied corpus")
    init.add_argument("--scope", required=True, help="What the project will and will not use")
    init.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="SOURCE_ID:PAPER_ID:ROLE:PATH",
        help="One source binding; ROLE is MAIN or SI and PATH is relative to inputs/papers",
    )

    validate = subparsers.add_parser("validate", help="Validate and resolve one editable ProjectManifest")
    validate.add_argument("--manifest", type=Path, required=True)

    status = subparsers.add_parser("status", help="Compare current resolved config with an immutable snapshot")
    status.add_argument("--manifest", type=Path, required=True)
    status.add_argument("--snapshot", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            report = _init_report(args)
        elif args.command == "validate":
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
