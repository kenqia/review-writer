"""Focused semantic-contract tests for the independent VersionContext owner.

These tests use only synthetic JSON-compatible metadata.  They intentionally do
not establish delivery release pointer-last behavior, Product Use, PUBLIC_E2E,
human acceptance, or scientific validity.
"""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from review_writer.product_foundation.contracts import (
    ConfirmationRequiredError,
    ReadOnlyVersionError,
    StaleRevisionError,
)
from review_writer.product_foundation.service import VersionContext
from review_writer.product_foundation.project_root import version_context_root


def _snapshot() -> dict[str, object]:
    return {
        "title": "Synthetic version-context fixture",
        "authors": ["Synthetic Author"],
        "metadata": {
            "year": 2026,
            "tags": ["alpha", "beta"],
        },
    }


def _updated_snapshot() -> dict[str, object]:
    value = _snapshot()
    value["title"] = "Synthetic version-context fixture v2"
    return value


def _create_context(root: Path, snapshot: dict[str, object] | None = None) -> tuple[VersionContext, Path]:
    state_path = version_context_root(root) / "current.json"
    context = VersionContext.create(
        snapshot or _snapshot(),
        project_id="synthetic-project",
        version_id="v1",
        branch_id="main",
        branch_name="Main",
        project_root=root,
        state_path=state_path,
    )
    return context, state_path


def test_create_load_persist_and_revision_are_stable() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = _snapshot()
        context, state_path = _create_context(root, source)

        initial = context.state()
        assert initial.current_version_id == "v1"
        assert initial.active_head_id == "v1"
        assert initial.writable_version_id == "v1"
        assert initial.inspected_version_id == "v1"
        assert initial.revision == 0
        assert state_path.is_file()

        loaded = VersionContext.load(state_path)
        assert loaded.state() == initial
        assert loaded.view_version("v1").snapshot == source

        context.publish_active_head(
            _updated_snapshot(),
            expected_head_id="v1",
            expected_revision=0,
            version_id="v2",
        )
        published = context.state()
        assert published.current_version_id == "v2"
        assert published.active_head_id == "v2"
        assert published.writable_version_id == "v2"
        assert published.inspected_version_id == "v2"
        assert published.revision == 1

        reloaded = VersionContext.load(state_path)
        assert reloaded.state() == published
        assert reloaded.view_version("v2").snapshot == _updated_snapshot()


def test_version_nodes_keep_immutable_snapshot_copies_and_deterministic_digests() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = _snapshot()
        original_source = copy.deepcopy(source)
        context, _ = _create_context(root, source)

        source["metadata"]["tags"].append("caller-mutation")  # type: ignore[index]
        first_view = context.view_version("v1")
        assert first_view.snapshot == original_source

        first_view.snapshot["metadata"]["year"] = 1900  # type: ignore[index]
        assert context.view_version("v1").snapshot == original_source

        published_snapshot = _updated_snapshot()
        published_node = context.publish_active_head(
            published_snapshot,
            expected_head_id="v1",
            expected_revision=0,
            version_id="v2",
        )
        published_snapshot["metadata"]["tags"].append("caller-mutation")  # type: ignore[index]
        published_node.snapshot["metadata"]["year"] = 1900  # type: ignore[index]
        assert context.view_version("v2").snapshot == _updated_snapshot()
        with pytest.raises(FrozenInstanceError):
            published_node.version_id = "mutated"  # type: ignore[misc]

        reordered = {
            "metadata": {"tags": ["alpha", "beta"], "year": 2026},
            "authors": ["Synthetic Author"],
            "title": "Synthetic version-context fixture",
        }
        equivalent_context = VersionContext.create(
            reordered,
            project_id="synthetic-project",
            version_id="equivalent-v1",
            branch_id="equivalent-main",
            branch_name="Equivalent Main",
        )
        assert (
            context.view_version("v1").snapshot_digest
            == equivalent_context.view_version("equivalent-v1").snapshot_digest
        )


def test_historical_selection_and_read_operations_preserve_current_pointer() -> None:
    with TemporaryDirectory() as temporary:
        context, state_path = _create_context(Path(temporary))
        context.publish_active_head(
            _updated_snapshot(),
            expected_head_id="v1",
            expected_revision=0,
            version_id="v2",
        )

        before_selection = context.state()
        historical = context.select_version("v1")
        after_selection = context.state()
        assert historical.read_only is True
        assert historical.can_write is False
        assert historical.is_current is False
        assert historical.is_active_head is False
        assert after_selection.current_version_id == before_selection.current_version_id == "v2"
        assert after_selection.active_head_id == before_selection.active_head_id == "v2"
        assert after_selection.writable_version_id == before_selection.writable_version_id == "v2"
        assert after_selection.inspected_version_id == "v1"
        assert after_selection.revision == before_selection.revision

        stable_state = context.state()
        stable_bytes = state_path.read_bytes()
        view = context.view_version("v1")
        comparison = context.compare_versions("v1", "v2")
        artifact = context.download_version("v1")

        assert view.read_only is True
        assert view.is_current is False
        assert comparison.left_version_id == "v1"
        assert comparison.right_version_id == "v2"
        assert "title" in comparison.changed_fields
        assert artifact.version_id == "v1"
        assert artifact.metadata["read_only"] is True
        assert json.loads(artifact.content.decode("utf-8"))["version_id"] == "v1"
        assert context.state() == stable_state
        assert state_path.read_bytes() == stable_bytes


def test_explicit_branch_from_here_requires_confirmation_and_creates_writable_leaf() -> None:
    with TemporaryDirectory() as temporary:
        context, _ = _create_context(Path(temporary))
        context.publish_active_head(
            _updated_snapshot(),
            expected_head_id="v1",
            expected_revision=0,
            version_id="v2",
        )
        context.select_version("v1")
        before = context.state()

        branch_args = {
            "source_version_id": "v1",
            "branch_id": "review",
            "branch_name": "Review branch",
            "version_id": "review-v1",
            "activate": True,
        }
        preview = context.preview_branch(**branch_args)
        assert preview.current_version_id == before.current_version_id == "v2"
        assert preview.active_branch_id == before.active_branch_id == "main"
        assert preview.activates_branch is True

        with pytest.raises(ConfirmationRequiredError) as raised:
            context.branch_from(
                **branch_args,
                confirm=False,
                expected_revision=before.revision,
            )
        assert raised.value.preview == preview
        assert context.state() == before

        leaf = context.branch_from(
            **branch_args,
            confirm=True,
            expected_revision=before.revision,
        )
        after = context.state()
        assert leaf.version_id == "review-v1"
        assert leaf.parent_version_id == "v1"
        assert after.current_version_id == "review-v1"
        assert after.active_head_id == "review-v1"
        assert after.writable_version_id == "review-v1"
        assert after.inspected_version_id == "review-v1"
        assert after.branch_heads == {"main": "v2", "review": "review-v1"}
        assert context.view_version("review-v1").can_write is True
        assert context.view_version("review-v1").read_only is False
        assert context.view_version("v2").read_only is True


def test_stale_revision_and_head_publish_leave_state_and_disk_unchanged() -> None:
    with TemporaryDirectory() as temporary:
        context, state_path = _create_context(Path(temporary))
        context.publish_active_head(
            _updated_snapshot(),
            expected_head_id="v1",
            expected_revision=0,
            version_id="v2",
        )
        stable_state = context.state()
        stable_bytes = state_path.read_bytes()

        with pytest.raises(StaleRevisionError):
            context.publish_active_head(
                _snapshot(),
                expected_head_id="v2",
                expected_revision=stable_state.revision - 1,
                version_id="stale-revision",
            )
        assert context.state() == stable_state
        assert state_path.read_bytes() == stable_bytes

        with pytest.raises(StaleRevisionError):
            context.publish_active_head(
                _snapshot(),
                expected_head_id="v1",
                expected_revision=stable_state.revision,
                version_id="stale-head",
            )
        assert context.state() == stable_state
        assert state_path.read_bytes() == stable_bytes
        assert {view.version_id for view in context.history()} == {"v1", "v2"}


def test_undo_rolls_back_pointer_and_retains_discarded_history_read_only() -> None:
    with TemporaryDirectory() as temporary:
        context, _ = _create_context(Path(temporary))
        context.publish_active_head(
            _updated_snapshot(),
            expected_head_id="v1",
            expected_revision=0,
            version_id="v2",
        )
        context.publish_active_head(
            {**_updated_snapshot(), "title": "Synthetic version-context fixture v3"},
            expected_head_id="v2",
            expected_revision=1,
            version_id="v3",
        )
        before = context.state()
        preview = context.preview_undo("v2")
        assert preview.current_version_id == "v3"
        assert preview.target_version_id == "v2"
        assert preview.discarded_version_ids == ("v3",)

        with pytest.raises(ConfirmationRequiredError):
            context.rollback("v2", confirm=False, expected_revision=before.revision)
        assert context.state() == before

        rolled_back = context.rollback(
            "v2",
            confirm=True,
            expected_revision=before.revision,
            branch_id="rollback",
            version_id="rollback-v1",
        )
        assert rolled_back.current_version_id == "rollback-v1"
        assert rolled_back.active_branch_id == "rollback"
        assert rolled_back.active_head_id == "rollback-v1"
        assert rolled_back.writable_version_id == "rollback-v1"
        assert rolled_back.inspected_version_id == "rollback-v1"
        assert rolled_back.revision == before.revision + 1

        discarded = context.view_version("v3")
        assert discarded.read_only is True
        assert discarded.can_write is False
        assert discarded.is_current is False
        assert discarded.is_active_head is False
        assert {view.version_id for view in context.history()} == {
            "v1",
            "v2",
            "v3",
            "rollback-v1",
        }
        assert context.compare_versions("v2", "v3").changed_fields == ("title",)
        assert context.download_version("v3").version_id == "v3"


def test_context_payload_has_no_automatic_promote_or_b2_state() -> None:
    with TemporaryDirectory() as temporary:
        context, state_path = _create_context(Path(temporary))
        context.select_version("v1")
        persisted = state_path.read_text(encoding="utf-8")
        artifact_text = context.download_version("v1").content.decode("utf-8")
        payload = json.loads(persisted)

        assert set(payload) == {
            "schema_version",
            "project_id",
            "version_id",
            "branch_id",
            "head_version_id",
            "revision",
            "inspected_version_id",
        }
        assert "PROMOTE" not in persisted.upper()
        assert "B2" not in persisted.upper()
        assert "PROMOTE" not in artifact_text.upper()
        assert "B2" not in artifact_text.upper()
        assert context.state().current_version_id == "v1"
