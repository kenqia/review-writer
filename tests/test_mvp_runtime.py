from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.run_vertical_review as runtime
from test_variable_n_contract import ACTOR, _generic_output, _input_manifest, _request


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "run_vertical_review.py"


def _run_cli(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *(str(arg) for arg in args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preflight_cli_returns_nonzero_when_result_is_not_ready(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        runtime,
        "preflight_corpus_inputs",
        lambda _project, _manifest: {
            "status": "blocked",
            "reason_code": "INPUT_NOT_READY",
        },
    )
    printed: list[dict[str, object]] = []
    monkeypatch.setattr(
        runtime,
        "_print_summary",
        lambda payload, **_kwargs: printed.append(payload),
    )

    code = runtime.main(
        [
            "preflight-corpus-inputs",
            "--project",
            str(project),
            "--manifest",
            str(manifest),
        ]
    )

    assert code == 3
    assert printed == [{
        "command": "preflight-corpus-inputs",
        "reason_code": "INPUT_NOT_READY",
        "status": "blocked",
    }]


def test_four_corpus_commands_execute_the_documented_mvp_flow(tmp_path: Path) -> None:
    request = _request(tmp_path, 20)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    review_root = tmp_path / "projects"

    bootstrap = _run_cli(
        "bootstrap-corpus",
        "--review-root",
        review_root,
        "--request",
        request_path,
    )
    assert bootstrap.returncode == 0, bootstrap.stderr
    assert json.loads(bootstrap.stdout) == {
        "command": "bootstrap-corpus",
        "project_id": "variable-20",
        "source_count": 20,
        "status": "CREATED",
    }
    project = review_root / "variable-20"

    bind = _run_cli(
        "bind-generic-parse",
        "--project",
        project,
        "--mineru-output",
        _generic_output(tmp_path / "generic", request),
    )
    assert bind.returncode == 0, bind.stderr
    assert json.loads(bind.stdout) == {
        "command": "bind-generic-parse",
        "completed_count": 40,
        "failed_count": 0,
        "parse_quality_count": 20,
        "source_truth_count": 20,
        "status": "bound",
    }

    input_manifest = _input_manifest(tmp_path, request, project)
    input_manifest_path = tmp_path / "input-manifest.json"
    input_manifest_path.write_text(json.dumps(input_manifest), encoding="utf-8")

    preflight = _run_cli(
        "preflight-corpus-inputs",
        "--project",
        project,
        "--manifest",
        input_manifest_path,
    )
    assert preflight.returncode == 0, preflight.stderr
    preflight_payload = json.loads(preflight.stdout)
    assert preflight_payload["command"] == "preflight-corpus-inputs"
    assert preflight_payload["status"] == "ready_for_import"
    assert preflight_payload["manifest_digest"]
    assert len(preflight_payload["bindings"]) == 20
    assert preflight_payload["counts"] == {
        "main_pdf": 20,
        "si": 20,
        "chemical_zip": 20,
        "generic_parse": 20,
        "generic_main": 20,
        "generic_si": 20,
        "chemical_main": 20,
        "chemical_core_si": 10,
    }

    imported = _run_cli(
        "import-corpus-inputs",
        "--project",
        project,
        "--manifest",
        input_manifest_path,
        "--actor-type",
        ACTOR["actor_type"],
        "--actor-label",
        ACTOR["actor_label"],
    )
    assert imported.returncode == 0, imported.stderr
    imported_payload = json.loads(imported.stdout)
    assert imported_payload["command"] == "import-corpus-inputs"
    assert imported_payload["status"] == "imported"
    assert imported_payload["counts"] == preflight_payload["counts"]

    unchanged = _run_cli(
        "import-corpus-inputs",
        "--project",
        project,
        "--manifest",
        input_manifest_path,
        "--actor-type",
        ACTOR["actor_type"],
        "--actor-label",
        ACTOR["actor_label"],
    )
    assert unchanged.returncode == 0, unchanged.stderr
    assert json.loads(unchanged.stdout)["status"] == "unchanged"


def test_bootstrap_corpus_domain_error_uses_json_stderr_and_exit_two(tmp_path: Path) -> None:
    request = _request(tmp_path, 20)
    request["sources"][0]["expected_pdf_sha256"] = "0" * 64
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    result = _run_cli(
        "bootstrap-corpus",
        "--review-root",
        tmp_path / "projects",
        "--request",
        request_path,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "command": "bootstrap-corpus",
        "error_code": "SOURCE_PDF_HASH_MISMATCH",
        "status": "ERROR",
    }
    assert str(tmp_path) not in result.stderr
