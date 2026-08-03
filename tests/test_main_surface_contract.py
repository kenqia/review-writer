from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validators" / "validate_main_surface.py"
CONTRACT = ROOT / "docs" / "product" / "MAIN_SURFACE_CONTRACT.md"


def run_validator(root: Path, mode: str = "candidate") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--mode", mode],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def report(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout, f"validator produced no JSON report: {result.stderr}"
    return json.loads(result.stdout)


def test_current_candidate_has_exact_user_entrypoint_contract() -> None:
    result = run_validator(ROOT)

    assert result.returncode == 0, result.stderr or result.stdout
    payload = report(result)
    assert payload["status"] == "PASS"
    assert payload["mode"] == "candidate"
    assert payload["main_commands"] == [
        "bootstrap-corpus",
        "bind-generic-parse",
        "preflight-corpus-inputs",
        "import-corpus-inputs",
    ]


def test_main_mode_rejects_core_development_paths(tmp_path: Path) -> None:
    result = run_validator(tmp_path, mode="main")

    assert result.returncode == 2
    payload = report(result)
    assert payload["status"] == "FAIL"
    assert any(item["code"] == "MAIN_REQUIRED_PATH_MISSING" for item in payload["findings"])


def test_main_mode_reports_a_present_development_directory(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    result = run_validator(tmp_path, mode="main")
    payload = report(result)

    assert any(item["code"] == "MAIN_REQUIRED_PATH_MISSING" for item in payload["findings"])
    assert any(item["code"] == "CORE_DEVELOPMENT_PATH_PRESENT" for item in payload["findings"])


def test_current_candidate_is_not_yet_a_clean_main_surface() -> None:
    result = run_validator(ROOT, mode="main")
    payload = report(result)

    assert result.returncode == 2
    assert any(item["code"] == "CORE_DEVELOPMENT_PATH_PRESENT" for item in payload["findings"])
    assert any(item["code"] == "MAIN_HELP_EXPOSES_NON_PUBLIC_COMMAND" for item in payload["findings"])


def test_contract_is_machine_readable_and_explains_user_boundary() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    assert "GOLD_DELTA=DIRECT" in text
    assert "TRACE_DELTA=DIRECT" in text
    assert "用户变化" in text
    assert "限制/风险" in text
    assert "core-development" in text
