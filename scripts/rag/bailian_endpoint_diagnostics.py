#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

PROXY_ENV_NAMES = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
]


def main() -> int:
    args = parse_args()
    report = run_diagnostics(args.endpoint, args.port)
    write_outputs(report, args.output_json, args.output_md)
    print(
        "bailian-endpoint-diagnostics: "
        f"{report['status']} dns={report['dns_status']} tcp={report['tcp_status']} tls={report['tls_status']} "
        f"https={report.get('https_status_code')}"
    )
    return 1 if args.strict and report["status"] == "fail" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unauthenticated Bailian endpoint transport diagnostics.")
    parser.add_argument("--endpoint", default="bailian.cn-beijing.aliyuncs.com")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--output-json", type=Path, default=Path("/tmp/bailian_endpoint_diagnostics.json"))
    parser.add_argument("--output-md", type=Path, default=Path("/tmp/bailian_endpoint_diagnostics.md"))
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def run_diagnostics(endpoint: str, port: int) -> dict[str, Any]:
    report: dict[str, Any] = {
        "endpoint": endpoint,
        "port": port,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV") or None,
        "proxy_env_set_names": [name for name in PROXY_ENV_NAMES if os.environ.get(name)],
        "dns_status": "not_run",
        "tcp_status": "not_run",
        "tls_status": "not_run",
        "https_status_code": None,
        "exception_class": None,
        "exception_message_redacted": None,
        "certificate": {},
    }
    try:
        infos = socket.getaddrinfo(endpoint, port, type=socket.SOCK_STREAM)
        addresses = sorted({info[4][0] for info in infos})
        report.update({"dns_status": "ok", "resolved_address_count": len(addresses)})
    except Exception as exc:  # noqa: BLE001 - diagnostic must classify transport failures safely.
        return _fail(report, "dns_failed", exc, "Fix DNS/proxy resolution for the Bailian endpoint.")

    try:
        with socket.create_connection((endpoint, port), timeout=10):
            report["tcp_status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        return _fail(report, "tcp_failed", exc, "Fix TCP/proxy reachability to endpoint:443.")

    try:
        context = ssl.create_default_context()
        with socket.create_connection((endpoint, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=endpoint) as tls:
                cert = tls.getpeercert() or {}
                report["tls_status"] = "ok"
                report["certificate"] = {
                    "subject": _name_tuple_to_text(cert.get("subject")),
                    "issuer": _name_tuple_to_text(cert.get("issuer")),
                    "notAfter": cert.get("notAfter"),
                }
    except Exception as exc:  # noqa: BLE001
        return _fail(report, "tls_failed", exc, "Fix TLS/proxy/certificate trust before SDK calls.")

    try:
        req = request.Request(f"https://{endpoint}/", method="HEAD")
        with request.urlopen(req, timeout=10) as response:  # noqa: S310 - endpoint is explicit CLI input.
            report["https_status_code"] = response.status
            report["https_status"] = "ok"
    except error.HTTPError as exc:
        report["https_status_code"] = exc.code
        report["https_status"] = "http_error_response"
    except Exception as exc:  # noqa: BLE001
        report["https_status"] = "https_failed"
        report["exception_class"] = type(exc).__name__
        report["exception_message_redacted"] = redact_transport_message(str(exc))

    report["status"] = "pass" if report["dns_status"] == report["tcp_status"] == report["tls_status"] == "ok" else "fail"
    if report.get("https_status") == "https_failed":
        report["recommendation"] = (
            "DNS/TCP/TLS are reachable; HTTPS root probe failed, likely due to proxy or endpoint root behavior. "
            "Proceed to minimal SDK lease repro before changing payload logic."
        )
    else:
        report["recommendation"] = "Endpoint transport is reachable; investigate SDK request, workspace, category, or permission next."
    return report


def _fail(report: dict[str, Any], failed_status: str, exc: Exception, recommendation: str) -> dict[str, Any]:
    if failed_status.startswith("dns"):
        report["dns_status"] = failed_status
    elif failed_status.startswith("tcp"):
        report["tcp_status"] = failed_status
    elif failed_status.startswith("tls"):
        report["tls_status"] = failed_status
    elif failed_status.startswith("https"):
        report["https_status"] = failed_status
    report.update(
        {
            "status": "fail",
            "exception_class": type(exc).__name__,
            "exception_message_redacted": redact_transport_message(str(exc)),
            "recommendation": recommendation,
        }
    )
    return report


def _name_tuple_to_text(value: Any) -> str | None:
    if not value:
        return None
    parts: list[str] = []
    for group in value:
        for key, item in group:
            parts.append(f"{key}={item}")
    return ", ".join(parts)


def redact_transport_message(text: str) -> str:
    # Transport diagnostics should never include credentials or proxy values.
    for name in PROXY_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "[REDACTED_PROXY]")
    return text[:500]


def write_outputs(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    cert = report.get("certificate") or {}
    lines = [
        "# Bailian Endpoint Diagnostics",
        "",
        f"- status: `{report.get('status')}`",
        f"- endpoint: `{report.get('endpoint')}`",
        f"- port: `{report.get('port')}`",
        f"- dns_status: `{report.get('dns_status')}`",
        f"- tcp_status: `{report.get('tcp_status')}`",
        f"- tls_status: `{report.get('tls_status')}`",
        f"- https_status_code: `{report.get('https_status_code')}`",
        f"- exception_class: `{report.get('exception_class')}`",
        f"- exception_message_redacted: {report.get('exception_message_redacted')}",
        f"- proxy_env_set_names: `{report.get('proxy_env_set_names')}`",
        f"- conda_env: `{report.get('conda_env')}`",
        f"- certificate_subject: `{cert.get('subject')}`",
        f"- certificate_issuer: `{cert.get('issuer')}`",
        f"- certificate_notAfter: `{cert.get('notAfter')}`",
        f"- recommendation: {report.get('recommendation')}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
