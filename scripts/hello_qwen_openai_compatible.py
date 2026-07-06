#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

EXPECTED_REPLY = "QWEN_HELLO_OK"
PROMPT = f"Reply with exactly: {EXPECTED_REPLY}"
REGION_HOSTS = {
    "cn-beijing": "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "ap-northeast-1": "https://{workspace_id}.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1",
    "ap-southeast-1": "https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled hello Qwen check through Alibaba OpenAI-compatible endpoint")
    parser.add_argument("--dry-run", action="store_true", help="Render safe endpoint metadata without calling network")
    parser.add_argument("--allow-network", action="store_true", help="Allow the single real hello Qwen request")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    args = parser.parse_args()

    if args.allow_network:
        report = run_real_call()
    else:
        report = build_dry_run_report(explicit_dry_run=args.dry_run)

    write_outputs(report, args.output_json, args.output_md)
    print(f"hello-qwen: {report['status']} ({report['summary']})")
    return 0 if report["status"] in {"pass", "dry_run"} else 1


def build_dry_run_report(*, explicit_dry_run: bool) -> dict[str, Any]:
    env = read_safe_env()
    base_url = build_base_url(env["workspace_id"] or "<workspace_id>", env["region"])
    status = "dry_run"
    summary = "dry-run only; no network call was made"
    if not explicit_dry_run:
        summary = "network disabled; pass --allow-network only after explicit user approval"
    return {
        "status": status,
        "summary": summary,
        "error_type": None,
        "model": env["model"],
        "region": env["region"],
        "base_url": base_url,
        "env": env["presence"],
        "response_matches_expected": False,
        "content": "",
        "warnings": ["API key value was not printed", "network was not used"],
        "metadata": {
            "network": "not_used",
            "files_uploaded": "not_used",
            "knowledge_base_created": "not_used",
            "image_api": "not_used",
            "prompt": PROMPT,
            "max_tokens": 8,
        },
    }


def run_real_call() -> dict[str, Any]:
    env = read_safe_env()
    missing = [name for name in ("DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID") if env["presence"][name] == "MISSING"]
    if missing:
        return error_report("missing_env", f"missing required env: {', '.join(missing)}", env)
    try:
        base_url = build_base_url(env["workspace_id"], env["region"])
    except ValueError as exc:
        return error_report("unexpected_error", str(exc), env)

    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return error_report("missing_dependency", "Python package 'openai' is not installed; not installing automatically", env)

    try:
        client = OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=base_url, timeout=20.0)
        response = client.chat.completions.create(
            model=env["model"],
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=8,
            temperature=0,
        )
        raw_content = response.choices[0].message.content or ""
        content = raw_content.strip()
        matched = content == EXPECTED_REPLY
        return {
            "status": "pass" if matched else "fail",
            "summary": "received expected hello reply" if matched else "response did not exactly match expected text",
            "error_type": None,
            "model": env["model"],
            "region": env["region"],
            "base_url": base_url,
            "env": env["presence"],
            "response_matches_expected": matched,
            "content": EXPECTED_REPLY if matched else "",
            "warnings": [] if matched else ["raw non-matching response was intentionally not printed"],
            "metadata": {
                "network": "used_once",
                "files_uploaded": "not_used",
                "knowledge_base_created": "not_used",
                "image_api": "not_used",
                "prompt": PROMPT,
                "max_tokens": 8,
            },
        }
    except Exception as exc:
        return error_report(classify_exception(exc), safe_exception_summary(exc), env, base_url=base_url)


def read_safe_env() -> dict[str, Any]:
    region = os.environ.get("BAILIAN_REGION") or "cn-beijing"
    model = os.environ.get("BAILIAN_MODEL") or "qwen-plus"
    workspace_id = os.environ.get("BAILIAN_WORKSPACE_ID") or ""
    return {
        "region": region,
        "model": model,
        "workspace_id": workspace_id,
        "presence": {
            "DASHSCOPE_API_KEY": "SET" if os.environ.get("DASHSCOPE_API_KEY") else "MISSING",
            "BAILIAN_WORKSPACE_ID": "SET" if workspace_id else "MISSING",
            "BAILIAN_REGION": "SET" if os.environ.get("BAILIAN_REGION") else "MISSING_DEFAULT_CN_BEIJING",
            "BAILIAN_MODEL": "SET" if os.environ.get("BAILIAN_MODEL") else "MISSING_DEFAULT_QWEN_PLUS",
        },
    }


def build_base_url(workspace_id: str, region: str) -> str:
    template = REGION_HOSTS.get(region)
    if not template:
        supported = ", ".join(sorted(REGION_HOSTS))
        raise ValueError(f"unsupported region {region!r}; supported regions: {supported}")
    return template.format(workspace_id=workspace_id)


def error_report(error_type: str, summary: str, env: dict[str, Any], *, base_url: str | None = None) -> dict[str, Any]:
    safe_base_url = base_url
    if safe_base_url is None:
        try:
            safe_base_url = build_base_url(env["workspace_id"] or "<workspace_id>", env["region"])
        except ValueError:
            safe_base_url = ""
    return {
        "status": "fail",
        "summary": summary,
        "error_type": error_type,
        "model": env["model"],
        "region": env["region"],
        "base_url": safe_base_url,
        "env": env["presence"],
        "response_matches_expected": False,
        "content": "",
        "warnings": ["API key value was not printed"],
        "metadata": {
            "network": "not_used" if error_type in {"missing_env", "missing_dependency", "unexpected_error"} else "attempted_once",
            "files_uploaded": "not_used",
            "knowledge_base_created": "not_used",
            "image_api": "not_used",
            "prompt": PROMPT,
            "max_tokens": 8,
        },
    }


def classify_exception(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code == 401:
        return "auth_error_401"
    if status_code == 429:
        return "rate_limit_or_quota_429"
    if isinstance(status_code, int) and 500 <= status_code <= 599:
        return "server_error_5xx"
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return "timeout"
    if any(token in name or token in text for token in ("connection", "network", "dns", "ssl")):
        return "network_error"
    return "unexpected_error"


def safe_exception_summary(exc: Exception) -> str:
    error_type = classify_exception(exc)
    if error_type == "auth_error_401":
        return "authentication failed with HTTP 401"
    if error_type == "rate_limit_or_quota_429":
        return "rate limit or quota error with HTTP 429"
    if error_type == "server_error_5xx":
        return "server returned a 5xx error"
    if error_type == "timeout":
        return "request timed out"
    if error_type == "network_error":
        return "network error during the single hello request"
    return f"unexpected error: {exc.__class__.__name__}"


def write_outputs(report: dict[str, Any], output_json: str | None, output_md: str | None) -> None:
    if output_json:
        Path(output_json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if output_md:
        Path(output_md).write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Hello Qwen Report",
        "",
        f"- status: {report['status']}",
        f"- summary: {report['summary']}",
        f"- error_type: {report['error_type']}",
        f"- model: {report['model']}",
        f"- region: {report['region']}",
        f"- base_url: {report['base_url']}",
        f"- response_matches_expected: {report['response_matches_expected']}",
        f"- content: {report['content']}",
        f"- network: {report['metadata']['network']}",
        f"- files_uploaded: {report['metadata']['files_uploaded']}",
        f"- knowledge_base_created: {report['metadata']['knowledge_base_created']}",
        f"- image_api: {report['metadata']['image_api']}",
        "",
        "## Environment Presence",
        "",
    ]
    for key, value in report["env"].items():
        lines.append(f"- {key}: {value}")
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
