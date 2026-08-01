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


def _write_v2(project: Path, pages: list[list[dict[str, object]]]) -> Path:
    path = (
        project
        / "01_evidence/parses/extracted/10_1000_example/parse_content_list_v2.json"
    )
    path.write_text(json.dumps(pages), encoding="utf-8")
    return path


def _v2_image(
    path: str,
    bbox: list[int],
    *captions: str,
) -> dict[str, object]:
    return {
        "type": "image",
        "bbox": bbox,
        "content": {
            "content": "",
            "image_source": {"path": path},
            "image_caption": [
                {"type": "text", "content": caption} for caption in captions
            ],
            "image_footnote": [],
        },
    }


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


def test_manuscript_figure_digest_uses_current_registry_binding(tmp_path: Path) -> None:
    project = _new_route_project(tmp_path)
    registry = build_source_figure_registry(project)

    from review_writer.project.manuscript_v2 import _figure_digests

    registry_digest, placeholder_digest = _figure_digests(project)

    assert registry_digest == registry["registry_digest"]
    assert placeholder_digest is None


def test_source_figure_prefers_v2_caption_over_v1(tmp_path: Path) -> None:
    project = _new_route_project(tmp_path)
    v1 = (
        project
        / "01_evidence/parses/extracted/10_1000_example/parse_content_list.json"
    )
    rows = json.loads(v1.read_text(encoding="utf-8"))
    next(row for row in rows if row.get("type") == "image")["image_caption"] = [
        "Figure 99. Legacy caption must not drive Source Figures."
    ]
    v1.write_text(json.dumps(rows), encoding="utf-8")
    from review_writer.project.source_truth import write_source_truth_bundle

    write_source_truth_bundle(project, "scholarly-a")

    registry = build_source_figure_registry(project)

    assert [row["figure_label"] for row in registry["figures"]] == ["Figure 1"]
    assert registry["content_list_v2_digest"]


def test_source_figure_v2_groups_spatially_connected_fragments_with_one_caption(
    tmp_path: Path,
) -> None:
    project = _source_truth_project(tmp_path)
    extracted = project / "01_evidence/parses/extracted/10_1000_example"
    for name, value in (
        ("panel-a.jpg", b"panel-a"),
        ("panel-b.jpg", b"panel-b"),
        ("caption-anchor.jpg", b"caption-anchor"),
    ):
        (extracted / "images" / name).write_bytes(value)
    _write_v2(
        project,
        [
            [
                _v2_image("images/panel-a.jpg", [100, 100, 400, 220], "(a)"),
                _v2_image("images/panel-b.jpg", [105, 245, 405, 360], "(b)"),
                _v2_image(
                    "images/caption-anchor.jpg",
                    [100, 385, 410, 480],
                    "Figure 3. One source-supported composite figure.",
                ),
            ]
        ],
    )
    from review_writer.project.source_truth import write_source_truth_bundle

    write_source_truth_bundle(project, "scholarly-a")

    registry = build_source_figure_registry(project)

    assert [row["figure_label"] for row in registry["figures"]] == ["Figure 3"]
    figure = registry["figures"][0]
    assert [row["asset_path"].rsplit("/", 1)[-1] for row in figure["fragments"]] == [
        "panel-a.jpg",
        "panel-b.jpg",
        "caption-anchor.jpg",
    ]
    assert [row["bbox"] for row in figure["fragments"]] == [
        [100, 100, 400, 220],
        [105, 245, 405, 360],
        [100, 385, 410, 480],
    ]
    assert [row["caption_association"] for row in figure["fragments"]] == [
        "same_page_spatial_group",
        "same_page_spatial_group",
        "explicit_caption_anchor",
    ]
    assert registry["locator_gaps"] == []


def test_source_figure_v2_keeps_adjacent_explicit_caption_anchors_separate(
    tmp_path: Path,
) -> None:
    project = _source_truth_project(tmp_path)
    extracted = project / "01_evidence/parses/extracted/10_1000_example"
    for name in ("scheme-2.jpg", "scheme-3.jpg"):
        (extracted / "images" / name).write_bytes(name.encode())
    _write_v2(
        project,
        [
            [
                _v2_image(
                    "images/scheme-2.jpg",
                    [80, 70, 490, 700],
                    "Scheme 2. Left-column source scheme.",
                ),
                _v2_image(
                    "images/scheme-3.jpg",
                    [502, 70, 915, 700],
                    "Scheme 3. Right-column source scheme.",
                ),
            ]
        ],
    )
    from review_writer.project.source_truth import write_source_truth_bundle

    write_source_truth_bundle(project, "scholarly-a")

    registry = build_source_figure_registry(project)

    assert [row["figure_label"] for row in registry["figures"]] == [
        "Scheme 2",
        "Scheme 3",
    ]
    assert [len(row["fragments"]) for row in registry["figures"]] == [1, 1]
    assert registry["locator_gaps"] == []


def test_source_figure_v2_incomplete_layout_is_a_visible_gap(
    tmp_path: Path,
) -> None:
    project = _source_truth_project(tmp_path)
    _write_v2(
        project,
        [
            [
                _v2_image(
                    "images/figure.jpg",
                    [10, 10, 10, 100],
                    "Figure 8. Invalid zero-width layout block.",
                )
            ]
        ],
    )
    from review_writer.project.source_truth import write_source_truth_bundle

    write_source_truth_bundle(project, "scholarly-a")

    registry = build_source_figure_registry(project)

    assert registry["figures"] == []
    assert registry["locator_gaps"] == [
        {
            "study_id": "scholarly-a",
            "source_id": "stud-a",
            "page": 1,
            "reason": "content_list_v2 图块缺少完整 bbox、图片来源或图注关系，已拒绝定位。",
        }
    ]


def test_source_figure_v2_missing_ambiguous_and_duplicate_labels_are_gaps(
    tmp_path: Path,
) -> None:
    project = _source_truth_project(tmp_path)
    extracted = project / "01_evidence/parses/extracted/10_1000_example"
    for name in (
        "missing.jpg",
        "amb-a.jpg",
        "bridge.jpg",
        "amb-b.jpg",
        "duplicate.jpg",
    ):
        (extracted / "images" / name).write_bytes(name.encode())
    _write_v2(
        project,
        [
            [
                _v2_image("images/missing.jpg", [50, 50, 250, 180]),
                _v2_image("images/amb-a.jpg", [400, 50, 650, 180], "Figure 4. A"),
                _v2_image("images/bridge.jpg", [405, 200, 655, 330]),
                _v2_image("images/amb-b.jpg", [400, 350, 650, 480], "Scheme 5. B"),
                _v2_image(
                    "images/duplicate.jpg",
                    [700, 600, 900, 750],
                    "Figure 4. Duplicate label.",
                )
            ]
        ],
    )
    from review_writer.project.source_truth import write_source_truth_bundle

    write_source_truth_bundle(project, "scholarly-a")

    registry = build_source_figure_registry(project)

    assert registry["figures"] == []
    reasons = [row["reason"] for row in registry["locator_gaps"]]
    assert any("未绑定明确" in reason for reason in reasons)
    assert any("多个图号" in reason for reason in reasons)
    assert any("重复图号" in reason for reason in reasons)


def test_source_figure_registry_fails_closed_when_v2_bytes_drift(
    tmp_path: Path,
) -> None:
    project = _new_route_project(tmp_path)
    build_source_figure_registry(project)
    v2 = (
        project
        / "01_evidence/parses/extracted/10_1000_example/parse_content_list_v2.json"
    )
    v2.write_text(v2.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ReviewFigureError, match="FIGURE_REGISTRY_STALE"):
        load_source_figure_registry(project)


def test_source_figure_registry_groups_v2_fragments_and_records_unlabelled_gap(
    tmp_path: Path,
) -> None:
    project = _source_truth_project(tmp_path)
    extracted = project / "01_evidence/parses/extracted/10_1000_example"
    (extracted / "images/header.jpg").write_bytes(b"header")
    (extracted / "images/panel-a.jpg").write_bytes(b"panel-a")
    (extracted / "images/panel-b.jpg").write_bytes(b"panel-b")
    (extracted / "images/figure-2.jpg").write_bytes(b"figure-2")
    _write_v2(
        project,
        [
            [
                _v2_image("images/header.jpg", [10, 10, 100, 60]),
                _v2_image("images/panel-a.jpg", [200, 100, 400, 200], "(a)"),
                _v2_image(
                    "images/panel-b.jpg",
                    [205, 220, 405, 320],
                    "Figure 1. Composite scope figure.",
                ),
                _v2_image(
                    "images/figure-2.jpg",
                    [600, 500, 900, 700],
                    "Figure 2. Independently extracted source figure.",
                ),
            ]
        ],
    )
    from review_writer.project.source_truth import write_source_truth_bundle

    write_source_truth_bundle(project, "scholarly-a")

    registry = build_source_figure_registry(project)

    assert [row["figure_label"] for row in registry["figures"]] == [
        "Figure 1",
        "Figure 2",
    ]
    assert registry["source_truth_digest"]
    assert registry["locator_gaps"] == [
        {
            "study_id": "scholarly-a",
            "source_id": "stud-a",
            "page": 1,
            "reason": "content_list_v2 图块未绑定明确的原论文 Figure/Scheme/Chart 图注。",
        }
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
    content_path = project / "01_evidence/parses/extracted/10_1000_example/parse_content_list_v2.json"
    content_path.write_text(content_path.read_text(encoding="utf-8").replace("images/figure.jpg", "full.md"), encoding="utf-8")
    bundle_path = project / "01_evidence/source_truth/scholarly-a/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    source = bundle["sources"][0]
    source["content_list_v2"]["sha256"] = hashlib.sha256(content_path.read_bytes()).hexdigest()
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
