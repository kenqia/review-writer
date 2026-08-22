from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from review_writer.agent.qoderwork_adapter import _parser


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "qoderwork/plugins/review-writer-cn"


def test_qoderwork_plugin_manifest_and_skill_are_current() -> None:
    manifest = json.loads((PLUGIN / ".qoder-plugin/plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "review-writer-cn"
    assert manifest["skills"] == ["skills/review-writer"]
    skill = (PLUGIN / "skills/review-writer/SKILL.md").read_text(encoding="utf-8")
    for required in ("topic", "explicit project root", "authorized PDF folder", "HUMAN_ACTION_REQUIRED", "Dashboard"):
        assert required in skill
    assert "VersionContext" in skill


def test_qoderwork_adapter_exposes_only_start_and_resume_commands() -> None:
    parser = _parser()
    start = parser.parse_args(["start", "--topic", "t", "--project-root", "p", "--authorized-pdf-folder", "pdf"])
    resume = parser.parse_args(["resume", "--project-root", "p"])
    assert start.command == "start"
    assert resume.command == "resume"


def test_qoderwork_plugin_zip_builds_without_secrets(tmp_path: Path) -> None:
    output = tmp_path / "review-writer-cn.qoder-plugin.zip"
    completed = subprocess.run(
        [sys.executable, "scripts/build_qoderwork_plugin_zip.py", "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.is_file()
    assert "review-writer-cn.qoder-plugin.zip" in completed.stdout
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert ".qoder-plugin/plugin.json" in names
        assert "skills/review-writer/SKILL.md" in names
        assert all(".env" not in name and "__pycache__" not in name for name in names)
