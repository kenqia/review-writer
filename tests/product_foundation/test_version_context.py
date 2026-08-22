from __future__ import annotations

import json

import pytest

from review_writer.product_foundation import (
    ConfirmationRequiredError,
    ReadOnlyVersionError,
    StaleRevisionError,
    VersionContext,
)
from review_writer.product_foundation.project_root import version_context_root


def _snapshot(document: str, *, gaps: list[str] | None = None) -> dict[str, object]:
    return {
        "document": document,
        "evidence": {"status": "AI_PROVISIONAL", "source_role": "MAIN"},
        "gaps": list(gaps or []),
        "comparison": {"status": "NON_COMPARABLE"},
        "lineage": {"branch": "divergent", "parent": "source-a"},
    }


def test_selecting_history_keeps_current_head_and_exposes_read_only_view() -> None:
    context = VersionContext.create(_snapshot("first"), version_id="v1")
    context.publish_active_head(_snapshot("second"), expected_head_id="v1", version_id="v2")

    before = context.state()
    view = context.select_version("v1")
    after = context.state()

    assert view.version_id == "v1"
    assert view.read_only is True
    assert view.can_write is False
    assert after.current_version_id == before.current_version_id == "v2"
    assert after.active_branch_id == before.active_branch_id == "main"
    assert after.active_head_id == before.active_head_id == "v2"
    assert after.writable_version_id == "v2"
    assert after.inspected_version_id == "v1"


def test_compare_and_download_bind_exactly_to_selected_nodes_without_state_changes() -> None:
    context = VersionContext.create(_snapshot("first"), version_id="v1")
    context.publish_active_head(
        _snapshot("second", gaps=["missing-locator"]),
        expected_head_id="v1",
        version_id="v2",
    )
    before = context.state()

    comparison = context.compare_versions("v1", "v2")
    artifact = context.download_version("v1")

    assert comparison.left_version_id == "v1"
    assert comparison.right_version_id == "v2"
    assert {"document", "gaps"}.issubset(comparison.changed_fields)
    assert artifact.version_id == "v1"
    assert artifact.filename == "review-v1.json"
    assert json.loads(artifact.content.decode("utf-8"))["snapshot"] == _snapshot("first")
    assert context.state() == before


def test_only_active_head_can_publish_and_old_nodes_remain_immutable() -> None:
    context = VersionContext.create(_snapshot("first"), version_id="v1")
    context.publish_active_head(_snapshot("second"), expected_head_id="v1", version_id="v2")

    with pytest.raises(ReadOnlyVersionError):
        context.publish_active_head(
            _snapshot("illegal-history-edit"),
            expected_head_id="v1",
            version_id="v3",
        )

    context.publish_active_head(_snapshot("third"), expected_head_id="v2", version_id="v3")
    assert context.view_version("v1").snapshot == _snapshot("first")
    assert context.view_version("v2").snapshot == _snapshot("second")
    assert context.state().writable_version_id == "v3"


def test_branch_requires_confirmation_and_activation_is_explicit() -> None:
    context = VersionContext.create(_snapshot("first"), version_id="v1")
    context.publish_active_head(_snapshot("second"), expected_head_id="v1", version_id="v2")
    before = context.state()

    preview = context.preview_branch("v1", branch_id="draft", branch_name="Draft")
    assert preview.source_version_id == "v1"
    assert preview.new_branch_id == "draft"
    with pytest.raises(ConfirmationRequiredError):
        context.branch_from(
            "v1",
            branch_id="draft",
            branch_name="Draft",
            version_id="draft-v1",
            confirm=False,
        )
    assert context.state() == before

    created = context.branch_from(
        "v1",
        branch_id="draft",
        branch_name="Draft",
        version_id="draft-v1",
        confirm=True,
        activate=False,
    )
    assert created.version_id == "draft-v1"
    assert context.state().current_version_id == "v2"
    assert context.state().active_branch_id == "main"

    context.activate_branch("draft", expected_head_id="draft-v1", confirm=True)
    assert context.state().current_version_id == "draft-v1"
    assert context.state().active_branch_id == "draft"
    assert context.state().writable_version_id == "draft-v1"
    assert context.view_version("v1").can_write is False


def test_undo_preview_requires_confirmation_and_cancel_has_zero_side_effects() -> None:
    context = VersionContext.create(_snapshot("first"), version_id="v1")
    context.publish_active_head(_snapshot("second"), expected_head_id="v1", version_id="v2")
    context.publish_active_head(_snapshot("third"), expected_head_id="v2", version_id="v3")
    before = context.state()

    preview = context.preview_undo("v2")
    assert preview.target_version_id == "v2"
    assert preview.discarded_version_ids == ("v3",)
    with pytest.raises(ConfirmationRequiredError):
        context.undo("v2", confirm=False)
    assert context.state() == before

    context.undo("v2", confirm=True)
    assert context.state().current_version_id == "v2"
    assert context.state().active_head_id == "v2"
    assert context.view_version("v3").read_only is True


def test_stale_revision_is_rejected_without_overwriting_new_head() -> None:
    context = VersionContext.create(_snapshot("first"), version_id="v1")
    stale_revision = context.state().revision
    context.publish_active_head(_snapshot("second"), expected_head_id="v1", version_id="v2")
    after_new_write = context.state()

    with pytest.raises(StaleRevisionError):
        context.publish_active_head(
            _snapshot("stale-write"),
            expected_head_id="v1",
            expected_revision=stale_revision,
            version_id="v-stale",
        )

    assert context.state() == after_new_write
    assert context.state().current_version_id == "v2"


def test_restart_resume_preserves_history_active_branch_and_inspected_node(tmp_path) -> None:
    state_path = version_context_root(tmp_path) / "current.json"
    context = VersionContext.create(
        _snapshot("first"),
        version_id="v1",
        project_root=tmp_path,
        state_path=state_path,
    )
    context.publish_active_head(_snapshot("second"), expected_head_id="v1", version_id="v2")
    context.select_version("v1")

    resumed = VersionContext.load(state_path)

    assert resumed.state() == context.state()
    assert resumed.view_version("v1").read_only is True
    assert resumed.view_version("v2").can_write is True
