#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

REQUIRED_MODULES = [
    "alibabacloud_bailian20231229",
    "alibabacloud_tea_openapi",
    "alibabacloud_tea_util",
    "requests",
]
REQUIRED_ENV = [
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "WORKSPACE_ID",
]


def main() -> int:
    args = parse_args()
    report = build_report()
    if args.output_json:
        write_json(args.output_json, report)
    if args.output_md:
        write_markdown(args.output_md, report)
    print(
        "bailian-sdk-env-check: "
        f"{report['status']} modules_missing={len(report['missing_modules'])} "
        f"env_missing={len(report['missing_env'])}"
    )
    return 1 if args.strict and report["status"] != "pass" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Bailian official SDK import and env presence without printing secrets.")
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_sdk_env_check.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_sdk_env_check.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def build_report() -> dict[str, Any]:
    modules = module_presence()
    env = env_presence()
    missing_modules = [name for name, status in modules.items() if status == "MISSING"]
    missing_env = [name for name, status in env.items() if status == "MISSING"]
    status = "pass" if not missing_modules and not missing_env else "warn"
    return {
        "status": status,
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "conda": {
            "CONDA_DEFAULT_ENV": os.environ.get("CONDA_DEFAULT_ENV") or "",
            "CONDA_PREFIX_SET": bool(os.environ.get("CONDA_PREFIX")),
            "inside_conda": bool(os.environ.get("CONDA_PREFIX") or os.environ.get("CONDA_DEFAULT_ENV")),
        },
        "modules": modules,
        "env": env,
        "missing_modules": missing_modules,
        "missing_env": missing_env,
        "safe_repair_suggestions": repair_suggestions(missing_modules, missing_env),
        "safety": {
            "network": "not_used",
            "bailian_api": "not_used",
            "upload": "not_used",
            "knowledge_base": "not_created",
            "key_values_printed": "no",
        },
    }


def module_presence() -> dict[str, str]:
    result: dict[str, str] = {}
    for module in REQUIRED_MODULES:
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                importlib.import_module(module)
            result[module] = "INSTALLED"
        except Exception:
            result[module] = "MISSING"
    return result


def env_presence() -> dict[str, str]:
    return {name: "SET" if os.environ.get(name) else "MISSING" for name in REQUIRED_ENV}


def repair_suggestions(missing_modules: list[str], missing_env: list[str]) -> list[str]:
    suggestions: list[str] = []
    if missing_modules:
        suggestions.extend(
            [
                "Create an isolated conda env instead of installing into the base environment.",
                "Suggested commands: conda create -n review-writer-bailian python=3.11 -y",
                "Then: conda activate review-writer-bailian",
                "Then: python -m pip install -U pip",
                "Then: python -m pip install alibabacloud-bailian20231229 alibabacloud-tea-openapi alibabacloud-tea-util requests",
            ]
        )
    if missing_env:
        suggestions.extend(
            [
                "Use a temporary local secret file or manual zsh -ic wrapper for a one-off run.",
                "Do not copy cloud AccessKey values into .zshenv, repo files, .env, logs, or reports.",
                "Only print SET/MISSING status, never actual values.",
            ]
        )
    return suggestions


def write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Bailian SDK Environment Check",
        "",
        f"- status: `{report['status']}`",
        f"- python executable: `{report['python']['executable']}`",
        f"- python version: `{report['python']['version']}`",
        f"- inside conda: `{report['conda']['inside_conda']}`",
        "",
        "## Modules",
    ]
    lines.extend(f"- {name}: {status}" for name, status in report["modules"].items())
    lines.extend(["", "## Environment Presence"])
    lines.extend(f"- {name}: {status}" for name, status in report["env"].items())
    lines.extend(["", "## Safety"])
    lines.extend(f"- {name}: {value}" for name, value in report["safety"].items())
    if report["safe_repair_suggestions"]:
        lines.extend(["", "## Safe Repair Suggestions"])
        lines.extend(f"- {item}" for item in report["safe_repair_suggestions"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

