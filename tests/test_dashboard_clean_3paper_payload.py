#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = Path("/tmp/review_writer_clean_3paper_e2e")
DEMO_ROOT = ROOT / "demo_projects/clean_3paper_allene_review"
RUNNER = ROOT / "scripts/demo/run_clean_3paper_e2e.py"
SERVER = ROOT / "view/serve_review_dashboard.py"


def main() -> int:
    ensure_output()
    port = free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(SERVER),
            "--review-root",
            str(OUTPUT_ROOT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for_server(port, proc)
        failures = run_checks(port)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("dashboard clean 3-paper payload tests passed")
    return 0


def ensure_output() -> None:
    if (OUTPUT_ROOT / "run_summary.json").exists():
        return
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--demo-root", str(DEMO_ROOT), "--output-root", str(OUTPUT_ROOT), "--strict"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(port: int, proc: subprocess.Popen[str]) -> None:
    deadline = time.time() + 10
    while time.time() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=1)
            raise RuntimeError(f"dashboard exited early\nstdout={stdout}\nstderr={stderr}")
        try:
            request_json(port, "/api/projects")
            return
        except Exception:
            time.sleep(0.15)
    raise RuntimeError("dashboard did not become ready")


def run_checks(port: int) -> list[str]:
    failures: list[str] = []
    projects = request_json(port, "/api/projects")
    project_id = projects[0]["project_id"]
    final = request_json(port, f"/api/project/{urllib.parse.quote(project_id)}/final")
    figures = request_json(port, f"/api/project/{urllib.parse.quote(project_id)}/figures")
    checkpoints = request_json(port, "/api/checkpoints")
    if not final.get("clean_3paper_review_pack"):
        failures.append("final payload missing clean_3paper_review_pack")
    if not final.get("quality_report"):
        failures.append("final payload missing quality_report")
    if not (figures.get("figure_manifest") or {}).get("figures"):
        failures.append("figures payload missing figure_manifest figures")
    if len(checkpoints.get("checkpoints") or []) != 9:
        failures.append("checkpoints payload does not contain 9 checkpoints")
    assert_status(port, "/file?path=/etc/passwd", 403, failures)
    allowed = OUTPUT_ROOT / "05_final_audit/clean_3paper_review_pack.md"
    assert_status(port, f"/file?path={urllib.parse.quote(str(allowed))}", 200, failures)
    return failures


def request_json(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def assert_status(port: int, path: str, expected: int, failures: list[str]) -> None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    except Exception as exc:
        failures.append(f"{path} raised {exc}")
        return
    if status != expected:
        failures.append(f"{path} returned {status}, expected {expected}")


if __name__ == "__main__":
    raise SystemExit(main())
