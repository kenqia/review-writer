from __future__ import annotations

from pathlib import Path

from review_writer.project.review_figures import build_source_figure_registry
from test_parse_reconciliation import reconciliation_project


def test_generic_caption_and_image_remain_source_figure_authority_with_chemical_lane(
    tmp_path: Path,
) -> None:
    project = reconciliation_project(tmp_path, conflict=False)

    registry = build_source_figure_registry(project)

    assert [row["figure_label"] for row in registry["figures"]] == ["Figure 1"]
    assert registry["figures"][0]["asset_path"].startswith(
        "01_evidence/parses/extracted/"
    )
    assert registry["chemical_paper_project_binding_digest"]
    assert any(
        "Chemical Paper" in row["reason"] and "独立图片" in row["reason"]
        for row in registry["locator_gaps"]
    )
