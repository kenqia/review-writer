from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

import review_writer.project.vertical_review as vertical_review
from review_writer.project.review_figures import (
    ReviewFigureError,
    build_source_figure_registry,
    load_source_figure_registry,
    register_synthesis_figure_placeholder,
)
from test_source_truth import _source_truth_project


def _new_route_project(tmp_path: Path) -> Path:
    project = _source_truth_project(tmp_path)
    content_path = (
        project
        / "01_evidence/parses/extracted/10_1000_example/parse_content_list.json"
    )
    content = json.loads(content_path.read_text(encoding="utf-8"))
    image = next(row for row in content if row.get("type") == "image")
    image["image_caption"] = ["Figure 1. Source-grounded example figure."]
    content_path.write_text(json.dumps(content), encoding="utf-8")
    # The source-truth directory is the route discriminator; the bundle itself
    # is written by the production builder so hashes remain authoritative.
    from review_writer.project.source_truth import write_source_truth_bundle

    write_source_truth_bundle(project, "scholarly-a")
    return project


def test_source_figure_binds_asset_caption_page_and_pdf(tmp_path: Path) -> None:
    registry = build_source_figure_registry(_new_route_project(tmp_path))
    figure = registry["figures"][0]

    assert figure["source_pdf_sha256"]
    assert figure["asset_sha256"]
    assert figure["page"] >= 1
    assert figure["caption"]
    assert figure["source_id"] == "stud-a"
    assert figure["asset_path"].startswith("01_evidence/parses/extracted/")
    assert registry["figure_budget"]["status"] == "needs_human_selection"
    assert registry["figure_budget"]["gaps"]


def test_source_figure_registry_excludes_unlabelled_fragments_and_records_gap(
    tmp_path: Path,
) -> None:
    project = _source_truth_project(tmp_path)
    extracted = project / "01_evidence/parses/extracted/10_1000_example"
    (extracted / "images/header.jpg").write_bytes(b"header")
    (extracted / "images/panel-a.jpg").write_bytes(b"panel-a")
    (extracted / "images/panel-b.jpg").write_bytes(b"panel-b")
    (extracted / "images/figure-2.jpg").write_bytes(b"figure-2")
    content_path = extracted / "parse_content_list.json"
    content_path.write_text(
        json.dumps(
            [
                {
                    "type": "image",
                    "img_path": "images/header.jpg",
                    "page_idx": 0,
                    "bbox": [1, 2, 3, 4],
                    "image_caption": [],
                },
                {
                    "type": "image",
                    "img_path": "images/panel-a.jpg",
                    "page_idx": 1,
                    "bbox": [1, 2, 3, 4],
                    "image_caption": ["(a)"],
                },
                {
                    "type": "image",
                    "img_path": "images/panel-b.jpg",
                    "page_idx": 1,
                    "bbox": [5, 6, 7, 8],
                    "image_caption": ["Figure 1. Composite scope figure."],
                },
                {
                    "type": "image",
                    "img_path": "images/figure-2.jpg",
                    "page_idx": 2,
                    "bbox": [1, 2, 3, 4],
                    "image_caption": ["Figure 2. Independently extracted source figure."],
                },
            ]
        ),
        encoding="utf-8",
    )
    from review_writer.project.source_truth import write_source_truth_bundle

    write_source_truth_bundle(project, "scholarly-a")

    registry = build_source_figure_registry(project)

    assert [row["figure_label"] for row in registry["figures"]] == ["Figure 2"]
    assert registry["source_truth_digest"]
    assert registry["locator_gaps"] == [
        {
            "study_id": "scholarly-a",
            "source_id": "stud-a",
            "page": 1,
            "reason": "抽取图片未绑定明确的原论文 Figure/Scheme 图注。",
        },
        {
            "study_id": "scholarly-a",
            "source_id": "stud-a",
            "page": 2,
            "reason": "同页多个图片碎片无法可靠归并为一张完整原论文图。",
        },
    ]


def test_source_figure_registry_fails_closed_after_source_truth_changes(
    tmp_path: Path,
) -> None:
    project = _new_route_project(tmp_path)
    build_source_figure_registry(project)
    markdown = project / "01_evidence/mineru/markdown/10_1000_example.md"
    markdown.write_text("# Canonical\nReparsed content\n", encoding="utf-8")
    from review_writer.project.source_truth import write_source_truth_bundle

    write_source_truth_bundle(project, "scholarly-a")

    with pytest.raises(ReviewFigureError, match="FIGURE_REGISTRY_STALE"):
        load_source_figure_registry(project)


def test_source_figure_rejects_content_list_drift(tmp_path: Path) -> None:
    project = _new_route_project(tmp_path)
    content_path = project / "01_evidence/parses/extracted/10_1000_example/parse_content_list.json"
    content_path.write_text(content_path.read_text(encoding="utf-8").replace("figure.jpg", "full.md"), encoding="utf-8")

    with pytest.raises(ReviewFigureError, match="FIGURE_CONTENT_LIST_DRIFT"):
        build_source_figure_registry(project)


def test_source_figure_rejects_asset_outside_images_directory(tmp_path: Path) -> None:
    project = _new_route_project(tmp_path)
    content_path = project / "01_evidence/parses/extracted/10_1000_example/parse_content_list.json"
    content_path.write_text(content_path.read_text(encoding="utf-8").replace("images/figure.jpg", "full.md"), encoding="utf-8")
    bundle_path = project / "01_evidence/source_truth/scholarly-a/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    source = bundle["sources"][0]
    source["content_list"]["sha256"] = hashlib.sha256(content_path.read_bytes()).hexdigest()
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    from review_writer.project.source_truth import canonical_digest
    bundle["bundle_digest"] = canonical_digest(body)
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(ReviewFigureError, match="FIGURE_ASSET_INVALID"):
        build_source_figure_registry(project)


def test_new_route_never_generates_comparative_bitmap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _new_route_project(tmp_path)

    def forbidden_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("legacy comparative bitmap must not run")

    monkeypatch.setattr(vertical_review, "_build_comparative_evidence_figure", forbidden_call)
    packet = vertical_review.build_writer_packet(project)

    assert packet["figure_policy"] == "source_figures_or_synthesis_placeholders_only"
    assert not (project / "03_figure_redraw/comparative_evidence_map.png").exists()


def test_placeholder_requires_question_panels_claims_and_limits(tmp_path: Path) -> None:
    project = _new_route_project(tmp_path)

    with pytest.raises(ReviewFigureError, match="PLACEHOLDER_INVALID"):
        register_synthesis_figure_placeholder(project, {"title": "Figure 1"})


def test_placeholder_persists_a_human_figure_brief(tmp_path: Path) -> None:
    project = _new_route_project(tmp_path)
    payload = {
        "placeholder_id": "SYNTH-FIG-1",
        "scientific_question": "Which comparison axis separates the studies?",
        "reader_takeaway": "The methods occupy different operating windows.",
        "panels": [
            {
                "panel": "A",
                "task": "Place the three studies on the approved comparison axis.",
                "synthesis_claim_ids": ["SYNTH-1"],
                "source_figure_ids": ["scholarly-a:stud-a:FIG-1"],
            }
        ],
        "comparison_axis": "activation mode",
        "required_labels_units": ["activation mode"],
        "counter_evidence": ["The source studies use non-identical substrates."],
        "forbidden_overclaims": ["Do not claim universal superiority."],
        "unresolved_uncertainties": ["Cross-study normalization is incomplete."],
        "caption_draft": "Human-produced synthesis figure comparing the approved axis.",
        "target_size": "single-column",
        "status": "awaiting_human_figure",
    }
    result = register_synthesis_figure_placeholder(project, payload)

    assert result["placeholder_id"] == "SYNTH-FIG-1"
    assert result["status"] == "awaiting_human_figure"
    stored = json.loads(
        (project / "03_figures/synthesis_figure_placeholders.json").read_text(encoding="utf-8")
    )
    assert stored["placeholders"][0]["placeholder_id"] == "SYNTH-FIG-1"
