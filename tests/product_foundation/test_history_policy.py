from __future__ import annotations

import pytest

from review_writer.product_foundation import (
    ConfirmationRequiredError,
    ReadOnlyVersionError,
    StaleRevisionError,
    UndoUnavailableError,
    VersionContext,
)
from review_writer.product_foundation.project_root import version_context_root


def _state(document: str) -> dict[str, object]:
    return {
        "document": document,
        "evidence": [{"id": "e1", "state": "AI_PROVISIONAL", "source_role": "MAIN"}],
        "gaps": [{"id": "gap-1", "status": "GAP"}],
        "comparison": {"status": "NON_COMPARABLE"},
        "lineage": {"source_role": "MAIN", "divergent": True},
    }


def test_read_actions_preserve_current_instance_and_evidence_bound_snapshot() -> None:
    context = VersionContext.create(_state("v1"), version_id="v1")
    context.publish_active_head(_state("v2"), expected_head_id="v1", version_id="v2")
    before = context.state()

    context.select_version("v1")
    view = context.view_version("v1")
    comparison = context.compare_versions("v1", "v2")
    artifact = context.download_version("v1")

    assert context.state().current_version_id == before.current_version_id == "v2"
    assert context.state().active_head_id == before.active_head_id == "v2"
    assert view.snapshot["evidence"][0]["state"] == "AI_PROVISIONAL"
    assert view.snapshot["gaps"][0]["status"] == "GAP"
    assert comparison.left_version_id == "v1"
    assert artifact.version_id == "v1"


def test_non_head_write_is_rejected_without_mutating_history() -> None:
    context = VersionContext.create(_state("v1"), version_id="v1")
    context.publish_active_head(_state("v2"), expected_head_id="v1", version_id="v2")
    context.publish_active_head(_state("v3"), expected_head_id="v2", version_id="v3")
    before = context.state()

    with pytest.raises(ReadOnlyVersionError) as error:
        context.publish_active_head(_state("illegal"), expected_head_id="v2", version_id="v4")

    assert error.value.code == "HISTORICAL_VERSION_READ_ONLY"
    assert context.state() == before
    assert context.view_version("v2").snapshot["document"] == "v2"


def test_undo_requires_target_confirmation_and_never_repeats_implicitly() -> None:
    context = VersionContext.create(_state("v1"), version_id="v1")
    context.publish_active_head(_state("v2"), expected_head_id="v1", version_id="v2")
    context.publish_active_head(_state("v3"), expected_head_id="v2", version_id="v3")

    preview = context.preview_undo()
    assert preview.target_version_id == "v2"
    with pytest.raises(ConfirmationRequiredError) as error:
        context.undo(confirm=False)
    assert error.value.preview.target_version_id == "v2"
    assert context.state().current_version_id == "v3"

    undone = context.undo(confirm=True)
    assert undone.revision == 3
    assert context.state().current_version_id == "v2"
    assert context.preview_undo().target_version_id == "v1"
    with pytest.raises(ConfirmationRequiredError):
        context.undo(confirm=False)
    assert context.state().current_version_id == "v2"


def test_initial_version_has_no_blind_undo_target() -> None:
    context = VersionContext.create(_state("v1"), version_id="v1")

    with pytest.raises(UndoUnavailableError):
        context.preview_undo()


def test_stale_write_preserves_persisted_current_pointer(tmp_path) -> None:
    state_path = version_context_root(tmp_path) / "current.json"
    context = VersionContext.create(
        _state("v1"),
        version_id="v1",
        project_root=tmp_path,
        state_path=state_path,
    )
    stale_revision = context.state().revision
    context.publish_active_head(_state("v2"), expected_head_id="v1", version_id="v2")
    persisted_after_new_head = state_path.read_bytes()

    with pytest.raises(StaleRevisionError) as error:
        context.publish_active_head(
            _state("stale"),
            expected_head_id="v1",
            expected_revision=stale_revision,
            version_id="v-stale",
        )

    assert error.value.code == "STALE_REVISION"
    assert state_path.read_bytes() == persisted_after_new_head
