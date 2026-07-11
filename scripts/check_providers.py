#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.config import load_provider_config
from review_writer.providers.base import TextGenerationRequest
from review_writer.providers.offline_provider import OfflineProvider
from review_writer.providers.openai_compatible_provider import OpenAICompatibleProvider
from review_writer.providers.dashscope_provider import DashScopeProvider
from review_writer.retrieval.base import RetrievalQuery
from review_writer.retrieval.bailian_retrieval import BailianRetrieval
from review_writer.image.base import ImageRequest
from review_writer.image.alibaba_image import AlibabaImageAdapter


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*:\s*['\"]?[A-Za-z0-9_./+=-]{16,}"),
]

REQUIRED_MODULES = [
    "review_writer.providers.offline_provider",
    "review_writer.providers.openai_compatible_provider",
    "review_writer.providers.dashscope_provider",
    "review_writer.retrieval.local_library",
    "review_writer.retrieval.bailian_retrieval",
    "review_writer.image.source_figure",
    "review_writer.image.alibaba_image",
    "review_writer.config.load_providers",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline provider adapter safety checker")
    parser.add_argument("--config", default="config/providers.example.yaml")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    report = run_checks(Path(args.config))
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(render_markdown(report), encoding="utf-8")

    print(f"provider-check: {report['status']} ({report['summary']})")
    if args.strict and report["errors"]:
        return 1
    return 0


def run_checks(config_path: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    config: dict[str, Any] = {}

    def add_check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})
        if status == "error":
            errors.append(f"{name}: {detail}")
        elif status == "warning":
            warnings.append(f"{name}: {detail}")

    if not config_path.exists():
        add_check("config_exists", "error", f"missing config: {config_path}")
    else:
        add_check("config_exists", "ok", str(config_path))
        try:
            config = load_provider_config(config_path)
            add_check("config_parse", "ok", "config loaded with standard-library parser")
        except Exception as exc:
            add_check("config_parse", "error", f"could not parse config: {exc}")

    if config:
        providers = config.get("providers", {})
        retrieval = config.get("retrieval", {})
        image = config.get("image", {})
        _check_equals(add_check, "default_provider_offline", config.get("default_provider"), "offline")
        _check_enabled(add_check, "offline_enabled", providers.get("offline", {}), True)
        _check_enabled(add_check, "alibaba_openai_compatible_disabled", providers.get("alibaba_openai_compatible", {}), False)
        _check_enabled(add_check, "bailian_disabled", retrieval.get("bailian", {}), False)
        _check_enabled(add_check, "alibaba_image_disabled", image.get("alibaba_image", {}), False)
        _check_no_secret_like_config(add_check, config_path)

    _check_env_file(add_check)
    _check_required_modules(add_check)
    _check_offline_provider(add_check)
    _check_disabled_adapters(add_check)

    status = "fail" if errors else ("warn" if warnings else "pass")
    return {
        "status": status,
        "summary": f"{len(checks)} checks, {len(errors)} errors, {len(warnings)} warnings",
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "metadata": {
            "network": "not_used",
            "real_api": "not_called",
            "keys_read": "not_read",
            "paper_body_read": "not_read",
        },
    }


def _check_equals(add_check: Any, name: str, actual: Any, expected: Any) -> None:
    if actual == expected:
        add_check(name, "ok", f"{name} is {expected}")
    else:
        add_check(name, "error", f"expected {expected!r}, got {actual!r}")


def _check_enabled(add_check: Any, name: str, section: Any, expected: bool) -> None:
    actual = section.get("enabled") if isinstance(section, dict) else None
    if actual is expected:
        add_check(name, "ok", f"enabled={expected}")
    else:
        add_check(name, "error", f"expected enabled={expected}, got {actual!r}")


def _check_no_secret_like_config(add_check: Any, config_path: Path) -> None:
    text = config_path.read_text(encoding="utf-8", errors="ignore")
    matches = [pattern.search(text) for pattern in SECRET_PATTERNS]
    if any(matches):
        add_check("config_has_no_real_key", "error", "secret-like value found in provider config")
    else:
        add_check("config_has_no_real_key", "ok", "no secret-like values found")


def _check_env_file(add_check: Any) -> None:
    env_path = REPO_ROOT / ".env"
    tracked = _git_ls_files(".env")
    if tracked:
        add_check("env_not_tracked", "error", ".env is tracked by git")
    else:
        add_check("env_not_tracked", "ok", ".env is not tracked by git")
    if env_path.exists():
        add_check("env_presence", "warning", ".env exists locally; values were not read")
    else:
        add_check("env_presence", "ok", ".env is absent")


def _git_ls_files(pathspec: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", pathspec],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _check_required_modules(add_check: Any) -> None:
    for module_name in REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
            add_check(f"import:{module_name}", "ok", "imported")
        except Exception as exc:
            add_check(f"import:{module_name}", "error", f"import failed: {exc}")


def _check_offline_provider(add_check: Any) -> None:
    request = TextGenerationRequest(messages=[{"role": "user", "content": "offline smoke"}])
    first = OfflineProvider().generate_text(request)
    second = OfflineProvider().generate_text(request)
    if first.status == "ok" and first.content == second.content and first.metadata.get("network") == "not_used":
        add_check("offline_provider_mock", "ok", "deterministic mock response returned")
    else:
        add_check("offline_provider_mock", "error", "offline provider did not return deterministic no-network result")


def _check_disabled_adapters(add_check: Any) -> None:
    request = TextGenerationRequest(messages=[{"role": "user", "content": "do not call network"}])
    adapters = [
        ("openai_compatible_disabled", OpenAICompatibleProvider().generate_text(request)),
        ("dashscope_disabled", DashScopeProvider().generate_text(request)),
        ("bailian_disabled_runtime", BailianRetrieval().search(RetrievalQuery(query="test"))),
        ("alibaba_image_disabled_runtime", AlibabaImageAdapter().generate(ImageRequest(prompt="test"))),
    ]
    for name, result in adapters:
        if result.status == "disabled" and result.metadata.get("network") == "not_used":
            add_check(name, "ok", "disabled without network")
        else:
            add_check(name, "error", f"unexpected status={result.status!r}")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Provider Check Report",
        "",
        f"- status: {report['status']}",
        f"- summary: {report['summary']}",
        f"- network: {report['metadata']['network']}",
        f"- real_api: {report['metadata']['real_api']}",
        "",
        "## Checks",
        "",
        "| check | status | detail |",
        "| --- | --- | --- |",
    ]
    for check in report["checks"]:
        detail = str(check["detail"]).replace("|", "\\|")
        lines.append(f"| {check['name']} | {check['status']} | {detail} |")
    if report["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in report["errors"])
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
