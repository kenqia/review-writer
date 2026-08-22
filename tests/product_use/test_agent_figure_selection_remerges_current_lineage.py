from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from review_writer.project.manuscript_v2 import (
    approve_section,
    merge_authoritative_manuscript,
    manuscript_state,
    register_section_draft,
)
from review_writer.project.review_figures import build_source_figure_registry
from review_writer.project.source_truth import write_source_truth_bundle
from tests.product_use import test_generator_dashboard_v1_v2_e2e as generator_fixture
from tests.product_use import test_prod006_source_to_release as prod006_fixture
from view import serve_review_dashboard as dashboard


def test_public_figure_selection_refreshes_existing_manuscript_lineage() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-figure-remerge-") as temporary_root:
        review_root = Path(temporary_root)
        project = review_root / prod006_fixture.PROJECT_ID
        project.mkdir(parents=True)

        prod006_fixture._write_source_inputs(project)
        generator_fixture._add_synthetic_source_figure(
            project,
            rebuild_source_truth=False,
        )
        write_source_truth_bundle(project, prod006_fixture.STUDY_ID)
        prod006_fixture._approve_parse_quality(project, prod006_fixture.STUDY_ID)
        prod006_fixture._register_evidence(project)
        prod006_fixture._register_synthesis_and_contract(project)

        figure_id = (
            f"{prod006_fixture.STUDY_ID}:{prod006_fixture.SOURCE_ID}:figure-1"
        )
        body = (
            f"[synthesis:{prod006_fixture.SYNTHESIS_ID}] The source records a bounded outcome.\n\n"
            f"![Synthetic source-bound figure](../01_evidence/parses/extracted/prod006-main/images/synthetic_figure.png)\n\n"
            f"Source Figure Attribution: {figure_id} | {prod006_fixture.SOURCE_ID} | page 1 | Figure 1 "
            f"[evidence:{prod006_fixture.EVIDENCE_ID}]"
        )
        draft_body = body.replace("records a bounded outcome", "reports a bounded outcome")
        draft = register_section_draft(
            project,
            {
                "section_id": prod006_fixture.SECTION_ID,
                "heading": "Reported result",
                "body": draft_body,
                "generation_content_agent_result_digest": "a" * 64,
            },
        )
        approve_section(
            project,
            prod006_fixture.SECTION_ID,
            {"actor_type": "human_researcher", "actor_label": "figure-remerge-test"},
            edited_body=body,
            reason="Human approved the source-bound figure wording.",
            expected_draft_digest=draft["draft_digest"],
        )
        assert merge_authoritative_manuscript(project)["status"] == "approved"

        build_source_figure_registry(project)
        workspace = dashboard.project_review_figures_workspace_payload(
            review_root,
            prod006_fixture.PROJECT_ID,
        )
        figure = workspace["source_figures"][0]
        target = figure["target_options"][0]
        manuscript_bytes = (project / "04_manuscript/manuscript.md").read_bytes()
        binding = {
            "figure_id": figure_id,
            "asset_sha256": figure["asset_sha256"],
            "manuscript_sha256": hashlib.sha256(manuscript_bytes).hexdigest(),
            "section_id": target["section_id"],
            "marker": target["marker"],
            "occurrence": target["occurrence"],
        }

        before = manuscript_state(project)
        assert before["reason_code"] == "MANUSCRIPT_LINEAGE_STALE"
        result = dashboard.write_project_workspace_decision(
            review_root,
            prod006_fixture.PROJECT_ID,
            "review-figures",
            {
                "figure_id": figure_id,
                "selection_status": "selected",
                "version_token": figure["version_token"],
                "target_binding": binding,
            },
        )

        selected = result["source_figures"][0]
        assert selected["target_binding_status"] == "current"
        after = manuscript_state(project)
        assert after["status"] == "approved"
        assert after["workflow_can_continue"] is True
