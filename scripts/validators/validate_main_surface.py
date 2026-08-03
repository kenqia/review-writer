#!/usr/bin/env python3
"""Validate the boundary between the public main surface and development assets."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "docs" / "product" / "MAIN_SURFACE_CONTRACT.md"
JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


class ContractError(ValueError):
    """Raised when the boundary contract cannot be trusted."""


def _finding(code: str, message: str, *, path: str | None = None, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "message": message}
    if path is not None:
        result["path"] = path
    if details:
        result["details"] = details
    return result


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"cannot read boundary contract: {path}") from exc
    matches = JSON_BLOCK_RE.findall(text)
    if len(matches) != 1:
        raise ContractError("boundary contract must contain exactly one JSON block")
    try:
        contract = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise ContractError("boundary contract JSON is invalid") from exc
    if not isinstance(contract, dict):
        raise ContractError("boundary contract JSON must be an object")
    if contract.get("contract_id") != "main-surface-contract.v0.1":
        raise ContractError("unexpected boundary contract id")
    admission = contract.get("admission")
    if not isinstance(admission, dict) or admission.get("GOLD_DELTA") != "DIRECT" or admission.get("TRACE_DELTA") != "DIRECT":
        raise ContractError("boundary contract must declare DIRECT GOLD_DELTA and TRACE_DELTA")
    for key in (
        "main_commands",
        "main_user_surface",
        "main_documentation",
        "main_runtime_closure",
        "core_development_paths",
        "historical_asset_paths",
        "non_public_runtime_paths",
        "non_public_commands",
    ):
        if key not in contract:
            raise ContractError(f"boundary contract is missing {key}")
    return contract


def _safe_relative_path(raw: Any, *, section: str) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ContractError(f"{section} contains an invalid path")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ContractError(f"{section} contains a non-relative path: {raw}")
    return path.as_posix()


def _entries(contract: dict[str, Any], key: str) -> list[dict[str, str]]:
    raw_entries = contract.get(key)
    if not isinstance(raw_entries, list):
        raise ContractError(f"{key} must be a list")
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise ContractError(f"{key} must contain path objects")
        path = _safe_relative_path(raw_entry.get("path"), section=key)
        kind = raw_entry.get("kind")
        if kind not in {"file", "dir"}:
            raise ContractError(f"{key} has invalid kind for {path}")
        if path in seen:
            raise ContractError(f"{key} contains duplicate path {path}")
        seen.add(path)
        entries.append({"path": path, "kind": kind})
    return entries


def _strings(contract: dict[str, Any], key: str) -> list[str]:
    values = contract.get(key)
    if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
        raise ContractError(f"{key} must be a non-empty string list")
    normalized = [_safe_relative_path(value, section=key) for value in values]
    if len(set(normalized)) != len(normalized):
        raise ContractError(f"{key} contains duplicates")
    return normalized


def _path_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _check_contract_shape(contract: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        main_commands = contract["main_commands"]
        non_public_commands = contract["non_public_commands"]
        if not isinstance(main_commands, list) or not main_commands or not all(isinstance(value, str) for value in main_commands):
            raise ContractError("main_commands must be a non-empty string list")
        if not isinstance(non_public_commands, list) or not all(isinstance(value, str) for value in non_public_commands):
            raise ContractError("non_public_commands must be a string list")
        if len(set(main_commands)) != len(main_commands) or len(set(non_public_commands)) != len(non_public_commands):
            raise ContractError("command lists contain duplicates")
        if set(main_commands) & set(non_public_commands):
            raise ContractError("a command cannot be both public and non-public")
        categories = {
            "main_user_surface": _entries(contract, "main_user_surface"),
            "main_runtime_closure": _entries(contract, "main_runtime_closure"),
            "core_development_paths": _entries(contract, "core_development_paths"),
            "historical_asset_paths": _entries(contract, "historical_asset_paths"),
            "non_public_runtime_paths": _entries(contract, "non_public_runtime_paths"),
        }
        documentation = _strings(contract, "main_documentation")
        user_paths = {item["path"] for item in categories["main_user_surface"]}
        for path in documentation:
            if path not in user_paths:
                raise ContractError(f"main_documentation path is not in main_user_surface: {path}")

        public_paths = [
            item["path"]
            for key in ("main_user_surface", "main_runtime_closure")
            for item in categories[key]
        ]
        non_public_paths = [
            item["path"]
            for key in ("core_development_paths", "historical_asset_paths")
            for item in categories[key]
        ]
        for public_path in public_paths:
            for non_public_path in non_public_paths:
                if _path_overlap(public_path, non_public_path):
                    raise ContractError(f"public and non-public paths overlap: {public_path} / {non_public_path}")
    except (KeyError, TypeError) as exc:
        raise ContractError("boundary contract has an invalid shape") from exc
    except ContractError as exc:
        findings.append(_finding("CONTRACT_INVALID", str(exc)))
    return findings


def _check_path(root: Path, entry: dict[str, str]) -> bool:
    path = root / entry["path"]
    if entry["kind"] == "file":
        return path.is_file()
    return path.is_dir()


def _check_paths(
    root: Path,
    entries: list[dict[str, str]],
    *,
    mode: str,
    missing_code: str,
    present_code: str | None,
    label: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for entry in entries:
        present = _check_path(root, entry)
        if mode == "candidate" and not present:
            findings.append(
                _finding(
                    missing_code,
                    f"{label} path is missing from the candidate",
                    path=entry["path"],
                    expected_kind=entry["kind"],
                )
            )
        elif mode == "main" and present and present_code is not None:
            findings.append(
                _finding(
                    present_code,
                    f"{label} path must not be present on main",
                    path=entry["path"],
                )
            )
        elif mode == "main" and not present and label == "main":
            findings.append(
                _finding(
                    missing_code,
                    "main user-surface path is missing",
                    path=entry["path"],
                    expected_kind=entry["kind"],
                )
            )
    return findings


def _check_main_paths(root: Path, entries: list[dict[str, str]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for entry in entries:
        if not _check_path(root, entry):
            findings.append(
                _finding(
                    "MAIN_REQUIRED_PATH_MISSING",
                    "main user-surface or runtime path is missing",
                    path=entry["path"],
                    expected_kind=entry["kind"],
                )
            )
    return findings


def _check_documentation(root: Path, contract: dict[str, Any], main_commands: list[str], non_public_commands: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def mentions_command(text: str, command: str) -> bool:
        pattern = rf"(?<![A-Za-z0-9_-]){re.escape(command)}(?![A-Za-z0-9_-])"
        return re.search(pattern, text) is not None

    def code_text(text: str) -> str:
        fenced = re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL)
        inline = re.findall(r"`([^`\n]+)`", text)
        return "\n".join([*fenced, *inline])

    for raw_path in _strings(contract, "main_documentation"):
        path = root / raw_path
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for command in main_commands:
            if not mentions_command(text, command):
                findings.append(
                    _finding(
                        "MAIN_COMMAND_NOT_DOCUMENTED",
                        "public command is absent from a main user document",
                        path=raw_path,
                        command=command,
                    )
                )
        executable_text = code_text(text)
        leaked = [command for command in non_public_commands if mentions_command(executable_text, command)]
        if leaked:
            findings.append(
                _finding(
                    "MAIN_DOC_EXPOSES_NON_PUBLIC_COMMAND",
                    "main user document names non-public commands",
                    path=raw_path,
                    commands=leaked,
                )
            )
    return findings


def _entrypoint_help(root: Path, entrypoint: str, main_commands: list[str], non_public_commands: list[str], mode: str) -> tuple[list[dict[str, Any]], list[str]]:
    path = root / entrypoint
    if not path.is_file():
        return [], []
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(root) if not existing_pythonpath else f"{root}{os.pathsep}{existing_pythonpath}"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            [sys.executable, str(path), "--help"],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [_finding("MAIN_ENTRYPOINT_HELP_FAILED", "main CLI help could not be inspected", path=entrypoint, error=str(exc))], []
    if result.returncode != 0:
        return [
            _finding(
                "MAIN_ENTRYPOINT_HELP_FAILED",
                "main CLI help exited non-zero",
                path=entrypoint,
                returncode=result.returncode,
                stderr=result.stderr[-500:],
            )
        ], []
    help_text = f"{result.stdout}\n{result.stderr}"
    findings: list[dict[str, Any]] = []
    def mentions_command(command: str) -> bool:
        pattern = rf"(?<![A-Za-z0-9_-]){re.escape(command)}(?![A-Za-z0-9_-])"
        return re.search(pattern, help_text) is not None

    for command in main_commands:
        if not mentions_command(command):
            findings.append(
                _finding(
                    "MAIN_COMMAND_NOT_EXPOSED",
                    "public command is not exposed by the main CLI help",
                    path=entrypoint,
                    command=command,
                )
            )
    leaked = [command for command in non_public_commands if mentions_command(command)]
    if leaked and mode == "main":
        findings.append(
            _finding(
                "MAIN_HELP_EXPOSES_NON_PUBLIC_COMMAND",
                "main CLI help exposes a non-public command",
                path=entrypoint,
                commands=leaked,
            )
        )
    return findings, leaked


def validate(root: Path, *, mode: str = "candidate", contract_path: Path = CONTRACT_PATH) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if not root.is_dir():
        findings.append(_finding("ROOT_INVALID", "validation root is not a directory", path=str(root)))
        return {"status": "FAIL", "mode": mode, "main_commands": [], "findings": findings}
    try:
        contract = load_contract(contract_path)
        shape_findings = _check_contract_shape(contract)
        findings.extend(shape_findings)
        if shape_findings:
            return {"status": "FAIL", "mode": mode, "main_commands": [], "findings": findings}
        main_commands = list(contract["main_commands"])
        non_public_commands = list(contract["non_public_commands"])
        main_user_surface = _entries(contract, "main_user_surface")
        runtime_closure = _entries(contract, "main_runtime_closure")
        core_paths = _entries(contract, "core_development_paths")
        historical_paths = _entries(contract, "historical_asset_paths")
        non_public_runtime = _entries(contract, "non_public_runtime_paths")
    except ContractError as exc:
        findings.append(_finding("CONTRACT_INVALID", str(exc)))
        return {"status": "FAIL", "mode": mode, "main_commands": [], "findings": findings}

    findings.extend(_check_main_paths(root, main_user_surface + runtime_closure))
    if mode == "candidate":
        findings.extend(
            _check_paths(
                root,
                core_paths,
                mode=mode,
                missing_code="BOUNDARY_INVENTORY_PATH_MISSING",
                present_code=None,
                label="core-development",
            )
        )
        findings.extend(
            _check_paths(
                root,
                historical_paths + non_public_runtime,
                mode=mode,
                missing_code="BOUNDARY_INVENTORY_PATH_MISSING",
                present_code=None,
                label="historical",
            )
        )
    else:
        findings.extend(
            _check_paths(
                root,
                core_paths,
                mode=mode,
                missing_code="BOUNDARY_INVENTORY_PATH_MISSING",
                present_code="CORE_DEVELOPMENT_PATH_PRESENT",
                label="core-development",
            )
        )
        findings.extend(
            _check_paths(
                root,
                historical_paths,
                mode=mode,
                missing_code="BOUNDARY_INVENTORY_PATH_MISSING",
                present_code="HISTORICAL_ASSET_PATH_PRESENT",
                label="historical",
            )
        )
        findings.extend(
            _check_paths(
                root,
                non_public_runtime,
                mode=mode,
                missing_code="BOUNDARY_INVENTORY_PATH_MISSING",
                present_code="NON_PUBLIC_RUNTIME_PATH_PRESENT",
                label="non-public runtime",
            )
        )

    findings.extend(_check_documentation(root, contract, main_commands, non_public_commands))
    entrypoint = next(item["path"] for item in main_user_surface if item["path"].endswith("run_vertical_review.py"))
    help_findings, exposed_non_public_commands = _entrypoint_help(
        root,
        entrypoint,
        main_commands,
        non_public_commands,
        mode,
    )
    findings.extend(help_findings)
    return {
        "status": "PASS" if not findings else "FAIL",
        "mode": mode,
        "main_commands": main_commands,
        "exposed_non_public_commands": exposed_non_public_commands,
        "findings": findings,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the main user-surface boundary.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="candidate or main tree root")
    parser.add_argument("--mode", choices=("candidate", "main"), default="candidate")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = validate(args.root, mode=args.mode)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
