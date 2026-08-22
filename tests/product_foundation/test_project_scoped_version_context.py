from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_writer.product_foundation import (
    InvalidContextError,
    PersistenceError,
    StaleRevisionError,
    VersionContext,
)
from review_writer.product_foundation.project_root import version_context_root
from review_writer.product_foundation import service as service_module


def _snapshot(document: str) -> dict[str, object]:
    return {
        "document": document,
        "currentness": "current",
        "artifact_refs": [{"path": "00_brief/review_state.json", "sha256": "0" * 64}],
        "version_token": "synthetic-token",
    }


def test_project_scoped_create_persists_exact_durable_layout_and_cold_load(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    context = VersionContext.create(
        _snapshot("v1"),
        project_root=project,
        project_id="project",
        version_id="v1",
        branch_id="main",
        branch_name="Main",
    )

    durable_root = version_context_root(project)
    assert sorted(path.relative_to(durable_root).as_posix() for path in durable_root.rglob("*")) == [
        "branches",
        "branches/main.json",
        "current.json",
        "versions",
        "versions/v1.json",
    ]
    current = json.loads((durable_root / "current.json").read_text(encoding="utf-8"))
    node = json.loads((durable_root / "versions/v1.json").read_text(encoding="utf-8"))
    branch = json.loads((durable_root / "branches/main.json").read_text(encoding="utf-8"))

    assert current["version_id"] == "v1"
    assert current["branch_id"] == "main"
    assert current["revision"] == 0
    assert "snapshot" not in current
    assert "versions" not in current
    assert node["version_id"] == "v1"
    assert node["snapshot"] == _snapshot("v1")
    assert branch["branch_id"] == "main"
    assert branch["head_version_id"] == "v1"

    resumed = VersionContext.load(project)
    assert resumed.state() == context.state()
    assert resumed.view_version("v1").snapshot == _snapshot("v1")


def test_project_scoped_root_is_explicit_and_stale_write_is_zero_write(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    context = VersionContext.create(
        _snapshot("v1"),
        project_root=project,
        project_id="project",
        version_id="v1",
    )
    stale = VersionContext.load(project)
    context.publish_active_head(_snapshot("v2"), expected_head_id="v1", version_id="v2")

    durable_root = version_context_root(project)
    before = {
        path.relative_to(durable_root).as_posix(): path.read_bytes()
        for path in durable_root.rglob("*.json")
    }

    with pytest.raises(StaleRevisionError):
        stale.publish_active_head(
            _snapshot("stale"),
            expected_head_id="v1",
            expected_revision=0,
            version_id="stale",
        )

    after = {
        path.relative_to(durable_root).as_posix(): path.read_bytes()
        for path in durable_root.rglob("*.json")
    }
    assert after == before
    assert VersionContext.load(project).state().current_version_id == "v2"

    with pytest.raises(InvalidContextError):
        VersionContext.create(_snapshot("invalid"), project_root=Path("relative"))


def test_project_scoped_rollback_creates_new_branch_and_preserves_history(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    context = VersionContext.create(
        _snapshot("v1"),
        project_root=project,
        project_id="project",
        version_id="v1",
    )
    context.publish_active_head(_snapshot("v2"), expected_head_id="v1", version_id="v2")
    context.publish_active_head(_snapshot("v3"), expected_head_id="v2", version_id="v3")
    before = context.state()

    rolled_back = context.rollback(
        "v2",
        confirm=True,
        expected_revision=before.revision,
        branch_id="rollback",
        version_id="rollback-v1",
    )

    assert rolled_back.current_version_id == "rollback-v1"
    assert rolled_back.active_branch_id == "rollback"
    assert rolled_back.branch_heads == {"main": "v3", "rollback": "rollback-v1"}
    assert context.view_version("v3").snapshot == _snapshot("v3")
    assert context.view_version("v3").read_only is True
    assert context.view_version("rollback-v1").snapshot == _snapshot("v2")
    assert (version_context_root(project) / "versions/v3.json").is_file()
    assert (version_context_root(project) / "branches/main.json").is_file()
    assert (version_context_root(project) / "branches/rollback.json").is_file()


def test_current_pointer_is_written_last_and_old_current_survives_pointer_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    context = VersionContext.create(
        _snapshot("v1"),
        project_root=project,
        project_id="project",
        version_id="v1",
    )
    durable_root = version_context_root(project)
    current_path = durable_root / "current.json"
    branch_path = durable_root / "branches/main.json"
    current_before = current_path.read_bytes()
    branch_before = branch_path.read_bytes()
    replace = service_module.os.replace

    def fail_current(source: object, target: object) -> None:
        if Path(target).name == "current.json":
            raise OSError("synthetic current pointer failure")
        replace(source, target)

    monkeypatch.setattr(service_module.os, "replace", fail_current)
    with pytest.raises(PersistenceError):
        context.publish_active_head(
            _snapshot("v2"),
            expected_head_id="v1",
            expected_revision=0,
            version_id="v2",
        )

    assert current_path.read_bytes() == current_before
    assert branch_path.read_bytes() == branch_before
    assert not (durable_root / "versions/v2.json").exists()
    assert VersionContext.load(project).state().current_version_id == "v1"


def test_missing_or_mismatched_durable_artifacts_fail_closed_without_writes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    VersionContext.create(
        _snapshot("v1"),
        project_root=project,
        project_id="project",
        version_id="v1",
    )
    durable_root = version_context_root(project)
    current_path = durable_root / "current.json"
    current_before = current_path.read_bytes()

    current_path.unlink()
    missing_before = {
        path.relative_to(durable_root).as_posix(): path.read_bytes()
        for path in durable_root.rglob("*.json")
    }
    with pytest.raises(PersistenceError):
        VersionContext.load(project)
    missing_after = {
        path.relative_to(durable_root).as_posix(): path.read_bytes()
        for path in durable_root.rglob("*.json")
    }
    assert missing_after == missing_before

    current_path.write_bytes(current_before)
    node_path = durable_root / "versions/v1.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node["snapshot_digest"] = "0" * 64
    node_path.write_text(
        json.dumps(node, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    corrupt_before = {
        path.relative_to(durable_root).as_posix(): path.read_bytes()
        for path in durable_root.rglob("*.json")
    }
    with pytest.raises(InvalidContextError):
        VersionContext.load(project)
    corrupt_after = {
        path.relative_to(durable_root).as_posix(): path.read_bytes()
        for path in durable_root.rglob("*.json")
    }
    assert corrupt_after == corrupt_before
