from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from review_writer.product_foundation import VersionContext
from review_writer.product_foundation.project_root import version_context_root
from tests.product_use import test_public_e2e_chemical_import as chemical_flow
from tests.product_use import test_public_e2e_source_truth_parse as source_flow


PROJECT_ID = chemical_flow.PROJECT_ID
REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "run_vertical_review.py"


def _run_generator_start(project: Path, input_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "generator-start",
            "--project",
            str(project),
            "--input",
            str(input_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _error_payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    stream = result.stdout if result.returncode == 0 else result.stderr
    return json.loads(stream)


def test_public_agent_draft_entry_uses_project_version_context_after_chemical_binding() -> None:
    """The public blank-project path must reach the existing Agent seam."""
    with tempfile.TemporaryDirectory(prefix="public-e2e-agent-draft-entry-") as temporary_root:
        review_root = Path(temporary_root)
        server, thread, base_url = source_flow._start_dashboard(review_root)
        try:
            source = chemical_flow._prepare_parse_ready_project(
                review_root,
                base_url,
                PROJECT_ID,
            )
            chemical_flow._confirm_chemical_import(base_url, source)
            project = review_root / PROJECT_ID
            current_path = version_context_root(project) / "current.json"
            assert current_path.is_file(), (
                "public project creation must initialize the canonical VersionContext"
            )
            context = VersionContext.load(project)
            state = context.state()
            current = context.view_version(state.current_version_id)
            assert state.project_id == PROJECT_ID
            assert current.is_current is True
            assert current.is_active_head is True
            assert current.can_write is True
            assert current.snapshot["currentness"] == "current"

            request_path = review_root / "generator-request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "session_id": "generator-public-entry",
                        "section_id": "section-public-entry",
                        "heading": "Bounded synthetic finding",
                        "body": "[evidence:evidence-public-entry]",
                        "v2_addition": "[evidence:evidence-public-entry] Explicit limitation.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            current_before = current_path.read_bytes()
            started = _run_generator_start(project, request_path)
            payload = _error_payload(started)
            assert started.returncode == 2
            assert payload["error_code"] != "VERSION_CONTEXT_INVALID"
            assert payload["error_code"] != "PROJECT_WRITE_LOCK_UNINITIALIZED"
            assert payload["write_mode"] == "NONE"
            assert current_path.read_bytes() == current_before
        finally:
            source_flow._stop_dashboard(server, thread)
