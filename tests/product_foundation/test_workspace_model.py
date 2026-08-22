from __future__ import annotations

import re

import pytest

from review_writer.product_foundation import (
    InvalidContextError,
    VersionContext,
    WorkspaceModel,
)


_FORBIDDEN_GOVERNANCE_TOKENS = frozenset(
    {"gate", "receipt", "lease", "generation"}
)


def _normalized_workspace_tokens(model: WorkspaceModel) -> set[str]:
    tokens: set[str] = set()
    for workspace in model.to_dict()["workspaces"]:
        user_strings = (
            workspace["id"],
            workspace["label"],
            workspace["description"],
            *workspace.get("children", ()),
        )
        for value in user_strings:
            tokens.update(token.casefold() for token in re.findall(r"[A-Za-z0-9]+", value))
    return tokens


def _snapshot() -> dict[str, object]:
    return {
        "document": "draft",
        "evidence": [{"state": "AI_PROVISIONAL", "source_role": "MAIN"}],
        "gaps": [{"status": "GAP"}],
        "comparison": {"status": "NON_COMPARABLE"},
        "lineage": {"divergent": True},
    }


def test_default_workspace_model_exposes_the_seven_user_workspaces() -> None:
    model = WorkspaceModel.default()

    assert model.workspace_ids == (
        "Overview",
        "Research",
        "Draft",
        "Figures",
        "Review",
        "History",
        "Release",
    )
    assert "Release" in model.workspace_ids
    assert model.workspace("Release").label == "Release"
    assert model.research_workspace_ids == (
        "Scope",
        "Corpus",
        "Evidence",
        "Matrix",
        "Synthesis",
    )
    assert not _normalized_workspace_tokens(model).intersection(
        _FORBIDDEN_GOVERNANCE_TOKENS
    )


def test_forbidden_governance_workspace_label_is_rejected() -> None:
    model = WorkspaceModel.default()

    assert "Lease" not in model.workspace_ids
    with pytest.raises(InvalidContextError):
        model.workspace("Lease")


def test_history_workspace_context_distinguishes_current_and_inspected_node() -> None:
    context = VersionContext.create(_snapshot(), project_id="project-1", version_id="v1")
    context.publish_active_head({**_snapshot(), "document": "edited"}, expected_head_id="v1", version_id="v2")
    context.select_version("v1")

    bound = WorkspaceModel.default().bind_version_context(
        context,
        workspace_id="History",
    )

    assert bound.workspace_id == "History"
    assert bound.current_version_id == "v2"
    assert bound.inspected_version_id == "v1"
    assert bound.branch_id == "main"
    assert bound.head_version_id == "v2"
    assert bound.read_only is True
    assert bound.can_write is False
    assert bound.to_dict()["workspace"] == "History"


def test_non_history_workspace_keeps_active_head_writable() -> None:
    context = VersionContext.create(_snapshot(), project_id="project-1", version_id="v1")

    bound = WorkspaceModel.default().bind_version_context(
        context,
        workspace_id="Draft",
    )

    assert bound.current_version_id == "v1"
    assert bound.inspected_version_id == "v1"
    assert bound.read_only is False
    assert bound.can_write is True
