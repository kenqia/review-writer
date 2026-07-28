from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from review_writer.project.vertical_review import (
    apply_risk_decisions,
    build_risk_packet,
    build_writer_packet,
    initialize_review,
    register_study,
)


APPROVED_CLAIM_ID = "claim-approved-01"
APPROVED_CLAIM_TEXT = "The measured response increased under defined conditions"
HUMAN_CLAIM_ID = "claim-human-01"
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_release_ready_project(tmp_path: Path) -> Path:
    project = initialize_review(
        tmp_path,
        "synthetic-release",
        {"topic": "Synthetic release", "review_status": "AI_REVIEWED_BENCHMARK"},
    )
    candidate = {
        "study_id": "study-approved-01",
        "job_id": "job-approved-01",
        "claims": [
            {
                "claim_id": APPROVED_CLAIM_ID,
                "claim_text": APPROVED_CLAIM_TEXT,
                "evidence_refs": [
                    {
                        "source_id": "source-approved-01",
                        "page": 1,
                        "section_or_item": "Synthetic results",
                        "exact_quote": "A synthetic measured response increased.",
                    }
                ],
                "risk_level": "R1",
                "risk_categories": [],
            }
        ],
    }
    register_study(
        project,
        candidate,
        {"status": "R0_PASS", "job_id": candidate["job_id"], "candidate_job_id": candidate["job_id"]},
        {"verdict": "SUPPORT", "job_id": candidate["job_id"], "study_id": candidate["study_id"]},
    )
    human_candidate = {
        "study_id": "study-human-01",
        "job_id": "job-human-01",
        "claims": [
            {
                "claim_id": HUMAN_CLAIM_ID,
                "claim_text": "A synthetic causal interpretation requires human review",
                "evidence_refs": [
                    {
                        "source_id": "source-human-01",
                        "page": 2,
                        "section_or_item": "Synthetic discussion",
                        "exact_quote": "A synthetic interpretation was discussed.",
                    }
                ],
                "risk_level": "R3",
                "risk_categories": ["MECHANISM_CAUSALITY"],
            }
        ],
    }
    register_study(
        project,
        human_candidate,
        {"status": "R0_PASS", "job_id": human_candidate["job_id"], "candidate_job_id": human_candidate["job_id"]},
        {"verdict": "SUPPORT", "job_id": human_candidate["job_id"], "study_id": human_candidate["study_id"]},
    )
    risk_packet = build_risk_packet(project)
    apply_risk_decisions(
        project,
        {
            "packet_digest": risk_packet["packet_digest"],
            "decisions": [
                {
                    "action": "EXCLUDE" if target["claim_id"] == HUMAN_CLAIM_ID else "APPROVE",
                    "claim_id": target["claim_id"],
                    "review_target_digest": target["review_target_digest"],
                }
                for target in risk_packet["targets"]
            ],
        },
    )
    packet = build_writer_packet(project)
    manuscript = (
        "# Synthetic Review\n\n"
        "## Results\n\n"
        f"{APPROVED_CLAIM_TEXT} [1]. <!-- claim_id:{APPROVED_CLAIM_ID} -->\n\n"
        "![Synthetic one-pixel figure](../assets/tiny.png)\n\n"
        "Figure 1. Synthetic local image.\n\n"
        "## References\n\n"
        "[1] Synthetic reference entry.\n"
    )
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript_path.parent.mkdir(parents=True, exist_ok=True)
    manuscript_path.write_text(manuscript, encoding="utf-8")
    image_path = project / "assets" / "tiny.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(TINY_PNG)
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "schema_version": "review-writer-figure-manifest.v1",
            "figures": [
                {
                    "figure_id": "synthetic-one-pixel",
                    "figure_type": "ORIGINAL_GENERATED",
                    "markdown_path": "../assets/tiny.png",
                    "source_claim_ids": [APPROVED_CLAIM_ID],
                }
            ],
        },
    )
    _write_json(
        project / "04_first_draft" / "manuscript_lineage.json",
        {
            "schema_version": "manuscript-lineage.v1",
            "manuscript_sha256": hashlib.sha256(manuscript.encode("utf-8")).hexdigest(),
            "projection_sha256": packet["projection_sha256"],
            "claims": [
                {
                    "claim_id": APPROVED_CLAIM_ID,
                    "section_id": "results",
                    "text_span": APPROVED_CLAIM_TEXT,
                }
            ],
        },
    )
    return project


def test_section_round_trip_preserves_authoritative_manuscript() -> None:
    from review_writer.delivery.project_release import (
        render_manuscript_sections,
        split_manuscript_sections,
    )

    original = (
        "# Title\n\nIntro text.\n\n"
        "## Results\n\nEvidence-backed text [1].\n\n"
        "## References\n\n[1] Example."
    )
    sections = split_manuscript_sections(original)
    sections[1]["body"] = "Revised evidence-backed text [1]."

    rebuilt = render_manuscript_sections(sections)

    assert "## Results\n\nRevised evidence-backed text [1]." in rebuilt
    assert rebuilt.count("## References") == 1


def test_release_snapshots_exact_authoritative_bytes(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import build_project_release

    project = make_release_ready_project(tmp_path)
    source = project / "04_first_draft" / "first_draft.md"

    result = build_project_release(project)

    assert (project / "05_final_audit" / "final_draft.md").read_bytes() == source.read_bytes()
    assert result["manuscript_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (project / "05_final_audit" / "final_draft.docx").is_file()
    report = json.loads((project / "05_final_audit" / "quality_report.json").read_text(encoding="utf-8"))
    assert report["manuscript_sha256"] == result["manuscript_sha256"]
    assert report["docx_sha256"] == result["docx_sha256"]
    assert report["release_status"] == result["release_status"]
    assert report["figure_validation"]["status"] == "VERIFIED"
    assert report["figure_validation"]["manuscript_sha256"] == result["manuscript_sha256"]
    assert report["figure_validation"]["figures"][0]["figure_type"] == "ORIGINAL_GENERATED"
    assert report["figure_validation"]["figures"][0]["source_claim_ids"] == [APPROVED_CLAIM_ID]


def test_source_truth_project_export_rejects_incomplete_parse_without_touching_release(
    tmp_path: Path,
) -> None:
    from review_writer.delivery.project_release import (
        ProjectReleaseError,
        build_project_release,
    )
    from review_writer.project.parse_quality import write_parse_quality_gate
    from review_writer.project.source_truth import write_source_truth_bundle
    from test_source_truth import _source_truth_project

    project = make_release_ready_project(tmp_path)
    source_project = _source_truth_project(tmp_path / "source-input")
    for relative in (
        "00_sources",
        "01_evidence/mineru",
        "01_evidence/parses",
        "01_evidence/text_layers",
    ):
        shutil.copytree(source_project / relative, project / relative, dirs_exist_ok=True)
    write_source_truth_bundle(project, "scholarly-a")
    write_parse_quality_gate(project, "scholarly-a")
    stage = project / "05_final_audit"
    stage.mkdir(parents=True, exist_ok=True)
    release_paths = tuple(stage / name for name in ("final_draft.md", "final_draft.docx", "quality_report.json"))
    for index, path in enumerate(release_paths):
        path.write_bytes(f"sentinel-{index}".encode("ascii"))
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in release_paths}

    with pytest.raises(ProjectReleaseError, match="PARSE_QUALITY_NOT_READY"):
        build_project_release(project)

    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in release_paths} == before


def test_source_truth_project_export_rejects_incomplete_review_without_touching_release(
    tmp_path: Path,
) -> None:
    from review_writer.delivery.project_release import (
        ProjectReleaseError,
        build_project_release,
    )
    from review_writer.project.parse_quality import write_parse_quality_gate
    from review_writer.project.source_truth import write_source_truth_bundle
    from test_parse_quality import _decide_all
    from test_source_truth import _source_truth_project

    project = make_release_ready_project(tmp_path)
    source_project = _source_truth_project(tmp_path / "source-input")
    for relative in (
        "00_sources",
        "01_evidence/mineru",
        "01_evidence/parses",
        "01_evidence/text_layers",
    ):
        shutil.copytree(source_project / relative, project / relative, dirs_exist_ok=True)
    write_source_truth_bundle(project, "scholarly-a")
    write_parse_quality_gate(project, "scholarly-a")
    assert _decide_all(project)["workflow_can_continue"] is True
    stage = project / "05_final_audit"
    stage.mkdir(parents=True, exist_ok=True)
    release_paths = tuple(
        stage / name
        for name in ("final_draft.md", "final_draft.docx", "quality_report.json")
    )
    for index, path in enumerate(release_paths):
        path.write_bytes(f"sentinel-{index}".encode("ascii"))
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in release_paths}

    with pytest.raises(ProjectReleaseError, match="REVIEW_WORKFLOW_NOT_READY"):
        build_project_release(project)

    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in release_paths} == before


def test_release_accepts_licensed_source_with_explicit_license_and_attribution(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import build_project_release

    project = make_release_ready_project(tmp_path)
    attribution = "Adapted from Example et al., 2024, CC BY 4.0."
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "Figure 1. Synthetic local image.",
        f"Figure 1. Synthetic local image. {attribution}",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "schema_version": "review-writer-figure-manifest.v1",
            "figures": [
                {
                    "figure_id": "licensed-source-figure",
                    "figure_type": "LICENSED_SOURCE",
                    "markdown_path": "../assets/tiny.png",
                    "license": "CC BY 4.0",
                    "attribution": attribution,
                }
            ],
        },
    )

    result = build_project_release(project)

    report = json.loads(Path(result["quality_report"]).read_text(encoding="utf-8"))
    figure = report["figure_validation"]["figures"][0]
    assert figure["figure_type"] == "LICENSED_SOURCE"
    assert figure["license"] == "CC BY 4.0"
    assert figure["attribution"].startswith("Adapted from")
    with zipfile.ZipFile(result["docx"]) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "Adapted from Example et al., 2024, CC BY 4.0." in document_xml


@pytest.mark.parametrize(
    ("license_name", "canonical_license"),
    [
        ("CC-BY-4.0", "CC BY 4.0"),
        ("CC BY 4.0 International", "CC BY 4.0 International"),
        ("Public Domain Mark 1.0", "Public Domain Mark 1.0"),
    ],
)
def test_release_canonicalizes_explicit_license_aliases(
    tmp_path: Path,
    license_name: str,
    canonical_license: str,
) -> None:
    from review_writer.delivery.project_release import build_project_release

    project = make_release_ready_project(tmp_path)
    attribution = "Source status verified for the synthetic figure."
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "Figure 1. Synthetic local image.",
        f"Figure 1. Synthetic local image. {attribution}",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "schema_version": "review-writer-figure-manifest.v1",
            "figures": [
                {
                    "figure_id": "licensed-source-figure",
                    "figure_type": "LICENSED_SOURCE",
                    "markdown_path": "../assets/tiny.png",
                    "license": license_name,
                    "attribution": attribution,
                }
            ],
        },
    )

    result = build_project_release(project)

    report = json.loads(Path(result["quality_report"]).read_text(encoding="utf-8"))
    assert report["figure_validation"]["figures"][0]["license"] == canonical_license


@pytest.mark.parametrize(
    "license_name",
    [
        "All Rights Reserved",
        "permission requested",
        "custom terms may apply",
        "unknown",
        "Creative Commons Attribution status unknown / All Rights Reserved",
        "Creative Commons Attribution 4.0 / All Rights Reserved",
    ],
)
def test_release_rejects_non_permissive_or_ambiguous_source_license(
    tmp_path: Path,
    license_name: str,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "schema_version": "review-writer-figure-manifest.v1",
            "figures": [
                {
                    "figure_id": "source-figure",
                    "figure_type": "LICENSED_SOURCE",
                    "markdown_path": "../assets/tiny.png",
                    "license": license_name,
                    "attribution": "Source: Example et al., 2024.",
                }
            ],
        },
    )

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "FIGURE_POLICY_INVALID"


def test_release_accepts_explicit_written_authorization_with_attribution(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import build_project_release

    project = make_release_ready_project(tmp_path)
    attribution = "Reproduced with written authorization from Example Research Group."
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "Figure 1. Synthetic local image.",
        f"Figure 1. Synthetic local image. {attribution}",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "schema_version": "review-writer-figure-manifest.v1",
            "figures": [
                {
                    "figure_id": "authorized-source-figure",
                    "figure_type": "LICENSED_SOURCE",
                    "markdown_path": "../assets/tiny.png",
                    "license": "Explicit written authorization",
                    "attribution": attribution,
                    "permission_grantor": "Example Research Group",
                    "permission_scope": "Reproduction in this review manuscript and its DOCX release",
                    "permission_evidence_reference": "permission-record-synthetic",
                    "researcher_confirmed": True,
                }
            ],
        },
    )

    result = build_project_release(project)

    with zipfile.ZipFile(result["docx"]) as archive:
        assert attribution in archive.read("word/document.xml").decode("utf-8")


@pytest.mark.parametrize(
    "invalid_field",
    [
        "permission_grantor",
        "permission_scope",
        "permission_evidence_reference",
        "researcher_confirmed",
    ],
)
def test_release_rejects_incomplete_written_permission_record(
    tmp_path: Path,
    invalid_field: str,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    attribution = "Reproduced with written permission from Example Research Group."
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "Figure 1. Synthetic local image.",
        f"Figure 1. Synthetic local image. {attribution}",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())
    figure = {
        "figure_id": "authorized-source-figure",
        "figure_type": "LICENSED_SOURCE",
        "markdown_path": "../assets/tiny.png",
        "license": "Written permission",
        "attribution": attribution,
        "permission_grantor": "Example Research Group",
        "permission_scope": "Reproduction in this review manuscript and its DOCX release",
        "permission_evidence_reference": "permission-record-2026-07-28",
        "researcher_confirmed": True,
    }
    if invalid_field == "researcher_confirmed":
        figure[invalid_field] = False
    else:
        figure.pop(invalid_field)
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {"schema_version": "review-writer-figure-manifest.v1", "figures": [figure]},
    )

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "FIGURE_POLICY_INVALID"


def test_release_rejects_licensed_attribution_absent_from_authoritative_manuscript(
    tmp_path: Path,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "schema_version": "review-writer-figure-manifest.v1",
            "figures": [
                {
                    "figure_id": "licensed-source-figure",
                    "figure_type": "LICENSED_SOURCE",
                    "markdown_path": "../assets/tiny.png",
                    "license": "CC BY 4.0",
                    "attribution": "Adapted from Example et al., 2024, CC BY 4.0.",
                }
            ],
        },
    )

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "FIGURE_ATTRIBUTION_MISSING"


def test_release_rejects_converter_output_missing_required_attribution(
    tmp_path: Path,
) -> None:
    from review_writer.delivery import project_release
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release
    from view.serve_review_dashboard import project_release_docx_is_current

    project = make_release_ready_project(tmp_path)
    old_release = build_project_release(project)
    old_docx = Path(old_release["docx"]).read_bytes()
    attribution = "Adapted from Example et al., 2024, CC BY 4.0."
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "Figure 1. Synthetic local image.",
        f"Figure 1. Synthetic local image. {attribution}",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "schema_version": "review-writer-figure-manifest.v1",
            "figures": [
                {
                    "figure_id": "licensed-source-figure",
                    "figure_type": "LICENSED_SOURCE",
                    "markdown_path": "../assets/tiny.png",
                    "license": "CC BY 4.0",
                    "attribution": attribution,
                }
            ],
        },
    )

    def converter_without_attribution(command, **kwargs):
        output_path = Path(command[command.index("--output") + 1])
        with zipfile.ZipFile(output_path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document><p>Synthetic Review</p></document>")
        return project_release.subprocess.CompletedProcess(command, 0, "", "")

    with patch.object(project_release.subprocess, "run", side_effect=converter_without_attribution):
        with pytest.raises(ProjectReleaseError) as error:
            build_project_release(project)

    assert error.value.code == "DOCX_ATTRIBUTION_MISSING"
    release_docx = project / "05_final_audit" / "final_draft.docx"
    assert release_docx.read_bytes() == old_docx
    assert project_release_docx_is_current(release_docx) is False


@pytest.mark.parametrize(
    "invalid_docx",
    ["ordinary_zip", "missing_content_types", "malformed_document_xml"],
)
def test_release_rejects_non_docx_converter_archives(
    tmp_path: Path,
    invalid_docx: str,
) -> None:
    from review_writer.delivery import project_release
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)

    def invalid_converter(command, **kwargs):
        output_path = Path(command[command.index("--output") + 1])
        with zipfile.ZipFile(output_path, "w") as archive:
            if invalid_docx == "ordinary_zip":
                archive.writestr("notes.txt", "not an OPC document")
            else:
                if invalid_docx == "malformed_document_xml":
                    archive.writestr("[Content_Types].xml", "<Types/>")
                    archive.writestr("word/document.xml", "<document>")
                else:
                    archive.writestr("word/document.xml", "<document/>")
        return project_release.subprocess.CompletedProcess(command, 0, "", "")

    with patch.object(project_release.subprocess, "run", side_effect=invalid_converter):
        with pytest.raises(ProjectReleaseError) as error:
            build_project_release(project)

    assert error.value.code == "DOCX_EXPORT_FAILED"
    assert not (project / "05_final_audit" / "final_draft.docx").exists()


def test_release_rejects_original_figure_claim_outside_writer_whitelist(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    manifest_path = project / "03_figure_redraw" / "figure_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["figures"][0]["source_claim_ids"] = ["claim-fabricated-for-figure"]
    _write_json(manifest_path, manifest)

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "FIGURE_CLAIM_NOT_APPROVED"
    assert not (project / "05_final_audit" / "final_draft.docx").exists()


@pytest.mark.parametrize(
    "figure_changes",
    [
        {"license": "UNKNOWN"},
        {"license": "CC BY 4.0", "attribution": ""},
    ],
    ids=["unknown-license", "missing-attribution"],
)
def test_release_rejects_unlicensed_or_unattributed_source_figure(
    tmp_path: Path,
    figure_changes: dict[str, str],
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    figure = {
        "figure_id": "licensed-source-figure",
        "figure_type": "LICENSED_SOURCE",
        "markdown_path": "../assets/tiny.png",
        "license": "CC BY 4.0",
        "attribution": "Adapted from Example et al., 2024, CC BY 4.0.",
        **figure_changes,
    }
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {"schema_version": "review-writer-figure-manifest.v1", "figures": [figure]},
    )

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "FIGURE_POLICY_INVALID"
    assert not (project / "05_final_audit" / "final_draft.docx").exists()


def test_release_rejects_figure_brief_placeholder(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "schema_version": "review-writer-figure-manifest.v1",
            "figures": [
                {
                    "figure_id": "future-mechanism-figure",
                    "figure_type": "FIGURE_BRIEF_PLACEHOLDER",
                    "brief": "Show the evidence-supported catalytic cycle and unresolved branch.",
                }
            ],
        },
    )

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "FIGURE_PLACEHOLDER_PENDING"
    assert not (project / "05_final_audit" / "final_draft.docx").exists()


@pytest.mark.parametrize(
    "case",
    ["empty-manifest", "manuscript-without-figure", "unreferenced-manifest-figure"],
)
def test_release_requires_a_nonempty_exactly_referenced_figure_manifest(
    tmp_path: Path,
    case: str,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    manifest_path = project / "03_figure_redraw" / "figure_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8")
    if case == "empty-manifest":
        manifest["figures"] = []
    elif case == "manuscript-without-figure":
        manuscript = manuscript.replace("![Synthetic one-pixel figure](../assets/tiny.png)\n\n", "")
    else:
        manifest["figures"].append(
            {
                "figure_id": "unreferenced-copy",
                "figure_type": "ORIGINAL_GENERATED",
                "markdown_path": "../assets/unreferenced.png",
                "source_claim_ids": [APPROVED_CLAIM_ID],
            }
        )
        (project / "assets" / "unreferenced.png").write_bytes(TINY_PNG)
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())
    _write_json(manifest_path, manifest)

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "FIGURE_POLICY_INVALID"
    assert not (project / "05_final_audit" / "final_draft.docx").exists()


@pytest.mark.parametrize("image_failure", ["undecodable", "extension-mismatch"])
def test_release_rejects_invalid_or_mislabelled_image_content(
    tmp_path: Path,
    image_failure: str,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    image_path = project / "assets" / "tiny.png"
    if image_failure == "undecodable":
        image_path.write_bytes(b"not an image")
    else:
        jpg_path = image_path.with_suffix(".jpg")
        jpg_path.write_bytes(image_path.read_bytes())
        manuscript_path = project / "04_first_draft" / "first_draft.md"
        manuscript = manuscript_path.read_text(encoding="utf-8").replace(
            "../assets/tiny.png", "../assets/tiny.jpg"
        )
        manuscript_path.write_text(manuscript, encoding="utf-8")
        _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())
        manifest_path = project / "03_figure_redraw" / "figure_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["figures"][0]["markdown_path"] = "../assets/tiny.jpg"
        _write_json(manifest_path, manifest)

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "FIGURE_IMAGE_INVALID"


def test_release_binds_decoded_image_properties_and_content_digest(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import build_project_release

    project = make_release_ready_project(tmp_path)

    result = build_project_release(project)

    report = json.loads(Path(result["quality_report"]).read_text(encoding="utf-8"))
    figure = report["figure_validation"]["figures"][0]
    assert figure["content_sha256"] == hashlib.sha256(TINY_PNG).hexdigest()
    assert figure["image_format"] == "PNG"
    assert figure["width"] == 1
    assert figure["height"] == 1


@pytest.mark.parametrize("bounded_resource", ["input_bytes", "decoded_pixels"])
def test_release_rejects_figures_above_bounded_decode_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bounded_resource: str,
) -> None:
    from review_writer.delivery import figure_policy, project_release
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    if bounded_resource == "input_bytes":
        monkeypatch.setattr(figure_policy, "_MAX_IMAGE_BYTES", len(TINY_PNG) - 1, raising=False)
    else:
        monkeypatch.setattr(figure_policy, "_MAX_IMAGE_PIXELS", 0, raising=False)

    with patch.object(project_release.subprocess, "run", wraps=project_release.subprocess.run) as converter:
        with pytest.raises(ProjectReleaseError) as error:
            build_project_release(project)

    assert error.value.code == "FIGURE_IMAGE_INVALID"
    converter.assert_not_called()


@pytest.mark.parametrize("mutation", ["image", "manifest"])
def test_dashboard_invalidates_old_docx_when_figure_inputs_change(
    tmp_path: Path,
    mutation: str,
) -> None:
    from review_writer.delivery.project_release import build_project_release
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    result = build_project_release(project)
    assert dashboard.project_release_docx_is_current(Path(result["docx"])) is True
    if mutation == "image":
        (project / "assets" / "tiny.png").write_bytes(TINY_PNG + b"replacement")
    else:
        manifest_path = project / "03_figure_redraw" / "figure_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["figures"][0]["title"] = "Updated comparative evidence figure"
        _write_json(manifest_path, manifest)

    payload = dashboard.project_final_payload(tmp_path, "synthetic-release")

    assert dashboard.project_release_docx_is_current(Path(result["docx"])) is False
    assert payload["final_draft_docx_exists"] is False
    assert payload["final_draft_docx_path"] == ""
    assert payload["release_status"] == "RELEASE_OUTDATED"


def test_figure_freshness_streams_digest_without_reading_or_decoding_whole_image(
    tmp_path: Path,
) -> None:
    from review_writer.delivery import figure_policy
    from review_writer.delivery.figure_policy import figure_validation_is_current
    from review_writer.delivery.project_release import build_project_release

    project = make_release_ready_project(tmp_path)
    result = build_project_release(project)
    report = json.loads(Path(result["quality_report"]).read_text(encoding="utf-8"))
    manifest = json.loads(
        (project / "03_figure_redraw" / "figure_manifest.json").read_text(encoding="utf-8")
    )
    image_path = project / "assets" / "tiny.png"
    image_files = {"../assets/tiny.png": image_path}

    with (
        patch.object(Path, "read_bytes", side_effect=AssertionError("whole-image read is forbidden")),
        patch.object(figure_policy.Image, "open", side_effect=AssertionError("Pillow decode is forbidden")),
    ):
        assert figure_validation_is_current(
            report["figure_validation"],
            manuscript_sha256=report["manuscript_sha256"],
            manifest=manifest,
            image_files_by_markdown_path=image_files,
        ) is True

    image_path.write_bytes(TINY_PNG + b"replacement")
    with (
        patch.object(Path, "read_bytes", side_effect=AssertionError("whole-image read is forbidden")),
        patch.object(figure_policy.Image, "open", side_effect=AssertionError("Pillow decode is forbidden")),
    ):
        assert figure_validation_is_current(
            report["figure_validation"],
            manuscript_sha256=report["manuscript_sha256"],
            manifest=manifest,
            image_files_by_markdown_path=image_files,
        ) is False


def test_manuscript_revision_invalidates_figure_validation_and_docx_snapshot(tmp_path: Path) -> None:
    from review_writer.delivery.figure_policy import figure_validation_is_current
    from review_writer.delivery.project_release import build_project_release

    project = make_release_ready_project(tmp_path)
    result = build_project_release(project)
    report = json.loads(Path(result["quality_report"]).read_text(encoding="utf-8"))
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    revised = manuscript_path.read_text(encoding="utf-8").replace(
        "# Synthetic Review\n\n",
        "# Synthetic Review\n\nEditorial revision.\n\n",
        1,
    )
    manuscript_path.write_text(revised, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(revised.encode("utf-8")).hexdigest())
    current_sha256 = hashlib.sha256(manuscript_path.read_bytes()).hexdigest()

    assert figure_validation_is_current(
        report["figure_validation"],
        manuscript_sha256=current_sha256,
        manifest=json.loads(
            (project / "03_figure_redraw" / "figure_manifest.json").read_text(encoding="utf-8")
        ),
    ) is False
    assert report["manuscript_sha256"] != current_sha256
    assert report["docx_sha256"] == hashlib.sha256(
        (project / "05_final_audit" / "final_draft.docx").read_bytes()
    ).hexdigest()


def test_provider_draft_binding_preserves_exact_bytes_and_advances_to_drafting(
    tmp_path: Path,
) -> None:
    from review_writer.delivery.project_release import bind_authoritative_draft

    project = make_release_ready_project(tmp_path)
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    provider_manuscript = tmp_path / "provider-first-draft.md"
    provider_lineage = tmp_path / "provider-lineage.json"
    provider_manuscript.write_bytes(manuscript_path.read_bytes())
    provider_lineage.write_bytes(lineage_path.read_bytes())
    expected_manuscript = provider_manuscript.read_bytes()
    expected_lineage = provider_lineage.read_bytes()
    manuscript_path.unlink()
    lineage_path.unlink()

    result = bind_authoritative_draft(project, provider_manuscript, provider_lineage)

    assert result["project_id"] == "synthetic-release"
    assert manuscript_path.read_bytes() == expected_manuscript
    assert lineage_path.read_bytes() == expected_lineage
    state = json.loads((project / "00_brief/review_state.json").read_text(encoding="utf-8"))
    assert (state["current_stage"], state["status"]) == ("drafting", "in_progress")


def _update_lineage(project: Path, **changes: object) -> None:
    path = project / "04_first_draft" / "manuscript_lineage.json"
    lineage = json.loads(path.read_text(encoding="utf-8"))
    lineage.update(changes)
    _write_json(path, lineage)


def _section_edit_payload(review_root: Path, section_id: str, body: str) -> dict[str, str]:
    from view import serve_review_dashboard as dashboard

    payload = dashboard.project_draft_payload(review_root, "synthetic-release")
    return {
        "section_id": section_id,
        "body": body,
        "manuscript_version": payload["manuscript_version"],
    }


def _set_title_body(project: Path, body: str) -> None:
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "# Synthetic Review\n\n",
        f"# Synthetic Review\n\n{body}\n\n",
        1,
    )
    if "[2]" in body and "[2] Synthetic second reference entry." not in manuscript:
        manuscript = manuscript.replace(
            "[1] Synthetic reference entry.\n",
            "[1] Synthetic reference entry.\n\n[2] Synthetic second reference entry.\n",
        )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(
        project,
        manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest(),
    )


def test_single_section_edit_preserves_non_target_raw_bytes(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "# Synthetic Review\n\n",
        "# Synthetic Review\n\nOriginal editorial context.  \n\n",
        1,
    )
    manuscript_path.write_bytes(manuscript.replace("\n", "\r\n").encode("utf-8"))
    _update_lineage(
        project,
        manuscript_sha256=hashlib.sha256(manuscript_path.read_bytes()).hexdigest(),
    )
    before = manuscript_path.read_bytes()
    non_target = before[before.index(b"## Results") :]
    payload = _section_edit_payload(tmp_path, "synthetic-review", "Revised editorial context.\nSecond line.")

    dashboard.write_project_draft_sections(tmp_path, "synthetic-release", payload)

    after = manuscript_path.read_bytes()
    assert after[after.index(b"## Results") :] == non_target
    assert b"Revised editorial context.\r\nSecond line." in after


def test_safe_editorial_edit_refreshes_lineage_and_releases(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import build_project_release
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    before_lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    payload = _section_edit_payload(tmp_path, "synthetic-review", "Scientist-reviewed editorial context.")

    result = dashboard.write_project_draft_sections(tmp_path, "synthetic-release", payload)

    after_lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert after_lineage["manuscript_sha256"] == hashlib.sha256(manuscript_path.read_bytes()).hexdigest()
    assert {key: value for key, value in after_lineage.items() if key != "manuscript_sha256"} == {
        key: value for key, value in before_lineage.items() if key != "manuscript_sha256"
    }
    assert result["edit_classification"] == "editorial"
    assert result["needs_evidence_review"] is False
    assert after_lineage.get("pending_scientific_edits", []) == []
    release = build_project_release(project)
    assert Path(release["docx"]).is_file()


def test_stale_single_section_edit_is_rejected_without_changes(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    stale_payload = _section_edit_payload(tmp_path, "synthetic-review", "Stale scientist edit.")
    concurrent = manuscript_path.read_text(encoding="utf-8").replace(
        "# Synthetic Review\n\n",
        "# Synthetic Review\n\nConcurrent editorial change.\n\n",
        1,
    )
    manuscript_path.write_text(concurrent, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(concurrent.encode("utf-8")).hexdigest())
    before = (manuscript_path.read_bytes(), lineage_path.read_bytes())

    with pytest.raises(ValueError, match="stale"):
        dashboard.write_project_draft_sections(tmp_path, "synthetic-release", stale_payload)

    assert (manuscript_path.read_bytes(), lineage_path.read_bytes()) == before


def test_claim_span_edit_is_saved_pending_and_blocks_release(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    results = next(section for section in draft["sections"] if section["id"] == "results")
    payload = {
        "section_id": "results",
        "body": results["body"].replace(APPROVED_CLAIM_TEXT, "The measured response changed under defined conditions"),
        "manuscript_version": draft["manuscript_version"],
    }
    verified_body = results["body"]

    result = dashboard.write_project_draft_sections(tmp_path, "synthetic-release", payload)

    assert b"The measured response changed under defined conditions" in manuscript_path.read_bytes()
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert lineage["manuscript_sha256"] == hashlib.sha256(manuscript_path.read_bytes()).hexdigest()
    pending = lineage["pending_scientific_edits"][0]
    assert pending["section_id"] == "results"
    assert pending["reasons"] == ["修改了证据绑定主张"]
    assert pending["verified_body"].replace(f"<!-- claim_id:{APPROVED_CLAIM_ID} -->", "") == verified_body
    assert result["edit_classification"] == "scientific"
    assert result["needs_evidence_review"] is True
    assert result["reasons"] == ["修改了证据绑定主张"]
    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)
    assert error.value.code == "MANUSCRIPT_NEEDS_EVIDENCE_REVIEW"
    assert not (project / "05_final_audit" / "final_draft.docx").exists()


def test_restoring_verified_body_clears_pending_and_releases(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import build_project_release
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    results = next(section for section in draft["sections"] if section["id"] == "results")
    scientific = {
        "section_id": "results",
        "body": results["body"].replace(APPROVED_CLAIM_TEXT, "The measured response changed under defined conditions"),
        "manuscript_version": draft["manuscript_version"],
    }
    dashboard.write_project_draft_sections(tmp_path, "synthetic-release", scientific)
    pending_draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    pending = pending_draft["revision_status"]["pending_scientific_edits"]

    restored = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "results",
            "body": pending[0]["verified_body"],
            "manuscript_version": pending_draft["manuscript_version"],
        },
    )

    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert lineage["pending_scientific_edits"] == []
    assert restored["edit_classification"] == "restored"
    assert restored["needs_evidence_review"] is False
    release = build_project_release(project)
    assert Path(release["docx"]).is_file()


def test_citation_edit_outside_claim_span_is_saved_pending(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": "Editorial context cites the reported result [1].",
            "manuscript_version": draft["manuscript_version"],
        },
    )

    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert result["edit_classification"] == "scientific"
    assert result["reasons"] == ["改变了文献引用或 DOI"]
    assert lineage["pending_scientific_edits"][0]["verified_body"] == ""


@pytest.mark.parametrize(
    ("verified_body", "candidate_body"),
    [
        (
            "The primary condition was supported [1]. The comparison condition was supported [2].",
            "The primary condition was supported [2]. The comparison condition was supported [1].",
        ),
        (
            "The primary condition follows DOI 10.1000/alpha. The comparison follows DOI 10.1000/beta.",
            "The primary condition follows DOI 10.1000/beta. The comparison follows DOI 10.1000/alpha.",
        ),
    ],
    ids=["citation-sentence-swap", "doi-sentence-swap"],
)
def test_citation_or_doi_swap_between_sentences_is_saved_pending(
    tmp_path: Path,
    verified_body: str,
    candidate_body: str,
) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    _set_title_body(project, verified_body)
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": candidate_body,
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "scientific"
    assert "改变了文献引用或 DOI" in result["reasons"]
    assert result["needs_evidence_review"] is True


def test_scientific_numbers_swapped_between_conditions_are_saved_pending(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    _set_title_body(project, "Condition A gave a 20% response. Condition B gave an 80% response.")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": "Condition A gave an 80% response. Condition B gave a 20% response.",
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "scientific"
    assert "改变了数字或百分比" in result["reasons"]


def test_new_scientific_conclusion_is_saved_pending(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    make_release_ready_project(tmp_path / "review-projects")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": "The intervention improved the measured response.",
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "scientific"
    assert "新增了未经验证的科研结论" in result["reasons"]


@pytest.mark.parametrize(
    "body",
    [
        "The product formed cleanly under irradiation.",
        "-20 → +20 °C",
        "20 → 80 compounds",
        "The material remained stable in air.",
        "产物在光照下保持稳定。",
    ],
    ids=[
        "domain-result",
        "signed-temperature",
        "scientific-count",
        "unknown-english-statement",
        "unknown-chinese-statement",
    ],
)
def test_general_scientific_statements_are_saved_pending(tmp_path: Path, body: str) -> None:
    from view import serve_review_dashboard as dashboard

    make_release_ready_project(tmp_path / "review-projects")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": body,
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "scientific"
    assert result["needs_evidence_review"] is True


def test_document_meta_prose_with_domain_topic_stays_editorial(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    make_release_ready_project(tmp_path / "review-projects")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": "The catalyst section improved readability/navigation.",
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "editorial"
    assert result["needs_evidence_review"] is False
    assert result["reasons"] == []


def test_bare_editorial_version_number_does_not_create_pending(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    make_release_ready_project(tmp_path / "review-projects")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": "Editorial overview version 2.",
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "editorial"
    assert result["needs_evidence_review"] is False
    assert result["reasons"] == []


@pytest.mark.parametrize(
    "body",
    [
        "本节文字与措辞已经修订，以提升可读性。",
        "文档标题和章节概述采用新的编辑格式与样式。",
        "调整章节结构与行文措辞。",
        "调整文章结构。",
    ],
    ids=["wording-readability", "document-format", "section-structure", "article-structure"],
)
def test_chinese_document_meta_prose_stays_editorial(tmp_path: Path, body: str) -> None:
    from view import serve_review_dashboard as dashboard

    make_release_ready_project(tmp_path / "review-projects")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": body,
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "editorial"
    assert result["needs_evidence_review"] is False
    assert result["reasons"] == []


@pytest.mark.parametrize(
    "body",
    [
        "本节文字引用了该结论 [1]。",
        "本节文字将温度修订为 20 °C。",
        "本节文字修订了分子结构与反应机制。",
        "本节文字修订了化学结构。",
        "本节文字修订了立体结构。",
        "本节文字修订了结构式。",
    ],
    ids=[
        "citation",
        "scientific-number",
        "molecular-structure",
        "chemical-structure",
        "stereostructure",
        "structural-formula",
    ],
)
def test_chinese_meta_context_does_not_hide_scientific_changes(tmp_path: Path, body: str) -> None:
    from view import serve_review_dashboard as dashboard

    make_release_ready_project(tmp_path / "review-projects")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": body,
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "scientific"
    assert result["needs_evidence_review"] is True


@pytest.mark.parametrize(
    "body",
    [
        "This section shows that the catalyst improved yield.",
        "This paragraph demonstrates that the treatment improved survival.",
    ],
    ids=["section-scientific-assertion", "paragraph-scientific-assertion"],
)
def test_mixed_document_meta_and_scientific_assertions_stay_scientific(
    tmp_path: Path,
    body: str,
) -> None:
    from view import serve_review_dashboard as dashboard

    make_release_ready_project(tmp_path / "review-projects")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "synthetic-review",
            "body": body,
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "scientific"
    assert result["needs_evidence_review"] is True


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "malformed",
        "non-object",
        "manuscript-hash",
        "projection-hash",
        "writer-binding",
        "claim-whitelist",
    ],
)
def test_draft_payload_fails_closed_on_invalid_authoritative_lineage(
    tmp_path: Path,
    failure: str,
) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    if failure == "missing":
        lineage_path.unlink()
    elif failure == "malformed":
        lineage_path.write_text("{", encoding="utf-8")
    elif failure == "non-object":
        _write_json(lineage_path, [])
    elif failure in {"manuscript-hash", "projection-hash", "claim-whitelist"}:
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        if failure == "manuscript-hash":
            lineage["manuscript_sha256"] = "stale-manuscript-binding"
        elif failure == "projection-hash":
            lineage["projection_sha256"] = "stale-projection-binding"
        else:
            lineage["claims"][0]["claim_id"] = "claim-outside-writer-whitelist"
        _write_json(lineage_path, lineage)
    else:
        packet_path = project / "02_claims" / "writer_packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["projection_sha256"] = "stale-writer-binding"
        _write_json(packet_path, packet)

    with pytest.raises(ValueError):
        dashboard.project_draft_payload(tmp_path, "synthetic-release")


def test_draft_payload_accepts_valid_pending_lineage_with_text_span_drift(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    make_release_ready_project(tmp_path / "review-projects")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    results = next(section for section in draft["sections"] if section["id"] == "results")
    dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "results",
            "body": results["body"].replace(
                APPROVED_CLAIM_TEXT,
                "The measured response changed under defined conditions",
            ),
            "manuscript_version": draft["manuscript_version"],
        },
    )

    pending = dashboard.project_draft_payload(tmp_path, "synthetic-release")

    assert pending["available"] is True
    assert pending["revision_status"]["needs_evidence_review"] is True
    assert pending["revision_status"]["pending_scientific_edits"][0]["section_id"] == "results"


def test_chinese_edit_of_lineage_bound_claim_stays_scientific(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    make_release_ready_project(tmp_path / "review-projects")
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    results = next(section for section in draft["sections"] if section["id"] == "results")

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "results",
            "body": results["body"].replace(APPROVED_CLAIM_TEXT, "本句文字已完成编辑修订"),
            "manuscript_version": draft["manuscript_version"],
        },
    )

    assert result["edit_classification"] == "scientific"
    assert "修改了证据绑定主张" in result["reasons"]
    assert result["needs_evidence_review"] is True


def test_consecutive_scientific_edits_keep_one_pending_verified_baseline(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    first_draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    original = next(row for row in first_draft["sections"] if row["id"] == "results")["body"]
    first = original.replace(APPROVED_CLAIM_TEXT, "The measured response changed under defined conditions")
    dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {"section_id": "results", "body": first, "manuscript_version": first_draft["manuscript_version"]},
    )
    second_draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    second = next(row for row in second_draft["sections"] if row["id"] == "results")["body"].replace(
        "changed",
        "decreased",
    )

    result = dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {"section_id": "results", "body": second, "manuscript_version": second_draft["manuscript_version"]},
    )

    lineage = json.loads(
        (project / "04_first_draft" / "manuscript_lineage.json").read_text(encoding="utf-8")
    )
    assert result["edit_classification"] == "scientific"
    assert result["needs_evidence_review"] is True
    assert len(lineage["pending_scientific_edits"]) == 1
    assert lineage["pending_scientific_edits"][0]["verified_body"].replace(
        f"<!-- claim_id:{APPROVED_CLAIM_ID} -->",
        "",
    ) == original
    assert "decreased" in (project / "04_first_draft" / "first_draft.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("section_bound", [True, False], ids=["declared-section", "whole-manuscript"])
def test_release_rejects_ambiguous_duplicate_lineage_span(
    tmp_path: Path,
    section_bound: bool,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        f"{APPROVED_CLAIM_TEXT} [1].",
        f"{APPROVED_CLAIM_TEXT} [1].\n\n{APPROVED_CLAIM_TEXT} [1].",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    lineage["manuscript_sha256"] = hashlib.sha256(manuscript.encode("utf-8")).hexdigest()
    if not section_bound:
        lineage["claims"][0].pop("section_id")
    _write_json(lineage_path, lineage)

    with pytest.raises(ProjectReleaseError, match="MANUSCRIPT_LINEAGE_DRIFT"):
        build_project_release(project)

    assert not (project / "05_final_audit" / "final_draft.docx").exists()


@pytest.mark.parametrize("marker_failure", ["missing", "duplicate"])
def test_release_requires_each_lineage_claim_marker_exactly_once(
    tmp_path: Path,
    marker_failure: str,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8")
    marker = f"<!-- claim_id:{APPROVED_CLAIM_ID} -->"
    manuscript = (
        manuscript.replace(marker, "")
        if marker_failure == "missing"
        else manuscript.replace(marker, f"{marker} {marker}")
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "MANUSCRIPT_LINEAGE_DRIFT"


def test_dashboard_exposes_researcher_safe_figure_states_without_manifest_internals(
    tmp_path: Path,
) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    (project / "assets" / "licensed.png").write_bytes(TINY_PNG)
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "schema_version": "review-writer-figure-manifest.v1",
            "manifest_sha256": "must-never-be-visible",
            "figures": [
                {
                    "figure_id": "internal-original-id",
                    "figure_type": "ORIGINAL_GENERATED",
                    "markdown_path": "../assets/tiny.png",
                    "source_claim_ids": [APPROVED_CLAIM_ID],
                    "title": "跨研究比较证据图",
                    "caption": "比较纳入研究中的实验响应。",
                },
                {
                    "figure_id": "internal-licensed-id",
                    "figure_type": "LICENSED_SOURCE",
                    "markdown_path": "../assets/licensed.png",
                    "license": "CC BY 4.0",
                    "attribution": "改编自 Example 等，2024，CC BY 4.0。",
                    "caption": "许可来源图。",
                },
                {
                    "figure_id": "internal-placeholder-id",
                    "figure_type": "FIGURE_BRIEF_PLACEHOLDER",
                    "brief": "汇总证据支持的催化循环及尚未解决的分支。",
                },
            ],
        },
    )

    payload = dashboard.project_figures_payload(tmp_path, "synthetic-release")

    assert [row["state"] for row in payload["figures"]] == [
        "原创生成图",
        "许可来源图",
        "图片说明占位符",
    ]
    assert payload["figures"][0]["image_url"] == "/api/project/synthetic-release/figure?index=0"
    assert payload["figures"][1]["image_url"] == "/api/project/synthetic-release/figure?index=1"
    assert "image_url" not in payload["figures"][2]
    assert payload["figures"][2]["description"] == "汇总证据支持的催化循环及尚未解决的分支。"
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in (
        "figure_manifest",
        "manifest_sha256",
        "source_claim_ids",
        "claim-approved-01",
        "internal-original-id",
        "../assets/",
        "/home/",
    ):
        assert forbidden not in serialized


def test_dashboard_figure_payload_does_not_decode_images_during_polling(
    tmp_path: Path,
) -> None:
    from review_writer.delivery import figure_policy
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")

    with patch.object(
        figure_policy.Image,
        "open",
        side_effect=AssertionError("dashboard polling must not decode figures"),
    ):
        payload = dashboard.project_figures_payload(tmp_path, "synthetic-release")

    assert payload["figures"][0]["image_url"].endswith("figure?index=0")


def test_dashboard_merges_existing_original_figure_manifests_without_duplicates(
    tmp_path: Path,
) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    (project / "03_figure_redraw" / "comparative_evidence_map.png").write_bytes(TINY_PNG)
    (project / "assets" / "shared.png").write_bytes(TINY_PNG)
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "figures": [
                {
                    "figure_id": "comparative-evidence-map",
                    "license": "ORIGINAL_GENERATED",
                    "markdown_path": "../03_figure_redraw/comparative_evidence_map.png",
                    "source_claim_ids": [APPROVED_CLAIM_ID],
                    "title": "跨研究比较证据图",
                    "caption": "比较纳入研究中的证据分布。",
                },
                {
                    "figure_id": "shared-original",
                    "license": "ORIGINAL_GENERATED",
                    "markdown_path": "../assets/shared.png",
                    "source_claim_ids": [APPROVED_CLAIM_ID],
                    "title": "重复图件的旧记录",
                },
            ]
        },
    )
    _write_json(
        project / "03_figure_redraw" / "redrawn_figure_manifest.json",
        {
            "figures": [
                {
                    "figure_id": "shared-original",
                    "figure_type": "ORIGINAL_GENERATED",
                    "markdown_path": "../assets/shared.png",
                    "source_claim_ids": [APPROVED_CLAIM_ID],
                    "title": "重复图件的现行记录",
                }
            ]
        },
    )

    payload = dashboard.project_figures_payload(tmp_path, "synthetic-release")

    assert [row["title"] for row in payload["figures"]] == [
        "重复图件的现行记录",
        "跨研究比较证据图",
    ]
    assert [row["state"] for row in payload["figures"]] == ["原创生成图", "原创生成图"]
    assert [row["image_url"] for row in payload["figures"]] == [
        "/api/project/synthetic-release/figure?index=0",
        "/api/project/synthetic-release/figure?index=1",
    ]
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in (
        "figure_id",
        "markdown_path",
        "source_claim_ids",
        APPROVED_CLAIM_ID,
        "../assets/",
        "../03_figure_redraw/",
    ):
        assert forbidden not in serialized


def test_dashboard_orders_reading_figures_by_manuscript_references(
    tmp_path: Path,
) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    (project / "assets" / "second.png").write_bytes(TINY_PNG)
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "![Synthetic one-pixel figure](../assets/tiny.png)",
        "![Second figure](../assets/second.png)\n\n"
        "![Synthetic one-pixel figure](../assets/tiny.png)",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _write_json(
        project / "03_figure_redraw" / "figure_manifest.json",
        {
            "figures": [
                {
                    "figure_id": "first-in-manifest",
                    "figure_type": "ORIGINAL_GENERATED",
                    "markdown_path": "../assets/tiny.png",
                    "source_claim_ids": [APPROVED_CLAIM_ID],
                    "title": "First in manifest",
                },
                {
                    "figure_id": "second-in-manifest",
                    "figure_type": "ORIGINAL_GENERATED",
                    "markdown_path": "../assets/second.png",
                    "source_claim_ids": [APPROVED_CLAIM_ID],
                    "title": "Second in manifest",
                },
            ]
        },
    )

    payload = dashboard.project_figures_payload(tmp_path, "synthetic-release")

    assert [row["title"] for row in payload["figures"]] == [
        "First in manifest",
        "Second in manifest",
    ]
    assert [row["title"] for row in payload["reading_figures"]] == [
        "Second in manifest",
        "First in manifest",
    ]
    assert [row["image_url"] for row in payload["reading_figures"]] == [
        "/api/project/synthetic-release/figure?index=1",
        "/api/project/synthetic-release/figure?index=0",
    ]
    serialized = json.dumps(payload["reading_figures"], ensure_ascii=False)
    assert "markdown_path" not in serialized
    assert "../assets/" not in serialized


def test_draft_editor_hides_claim_marker_and_preserves_it_through_pending_restore(
    tmp_path: Path,
) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    marker = f"<!-- claim_id:{APPROVED_CLAIM_ID} -->"
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    results = next(section for section in draft["sections"] if section["id"] == "results")
    assert marker not in results["body"]

    dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "results",
            "body": results["body"].replace(
                APPROVED_CLAIM_TEXT,
                "The measured response changed under defined conditions",
            ),
            "manuscript_version": draft["manuscript_version"],
        },
    )
    pending = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    verified = pending["revision_status"]["pending_scientific_edits"][0]["verified_body"]
    assert marker not in verified
    dashboard.write_project_draft_sections(
        tmp_path,
        "synthetic-release",
        {
            "section_id": "results",
            "body": verified,
            "manuscript_version": pending["manuscript_version"],
        },
    )

    restored = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    assert restored["revision_status"]["pending_scientific_edits"] == []
    assert (project / "04_first_draft" / "first_draft.md").read_text(encoding="utf-8").count(marker) == 1


def test_review_workbench_connects_figure_states_and_current_docx_without_internal_terms() -> None:
    review_html = (
        Path(__file__).resolve().parents[1] / "view" / "assets" / "dashboard" / "review.html"
    ).read_text(encoding="utf-8")
    review_css = (
        Path(__file__).resolve().parents[1]
        / "view"
        / "assets"
        / "dashboard"
        / "review-ui.css"
    ).read_text(encoding="utf-8")

    assert 'id="figure-summary"' in review_html
    assert 'id="figure-list"' in review_html
    assert "/figures`" in review_html
    assert "/final`" in review_html
    for label in ("原创生成图", "许可来源图", "图片说明占位符", "图件与许可状态"):
        assert label in review_html
    assert "final_draft_docx_exists" in review_html
    assert "claim.text || claim.claim_id" not in review_html
    assert "证据绑定主张待核对" in review_html
    assert "overflow-wrap: anywhere" in review_css
    assert "min-width: 0" in review_css


def test_concurrent_draft_edits_with_one_version_allow_exactly_one_commit(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    first_payload = _section_edit_payload(tmp_path, "synthetic-review", "First concurrent editorial change.")
    second_payload = {**first_payload, "body": "Second concurrent editorial change."}
    real_commit = dashboard._commit_draft_and_lineage
    first_at_commit = threading.Event()
    second_at_commit = threading.Event()
    release_first = threading.Event()
    call_guard = threading.Lock()
    call_count = 0

    def hold_first_commit(*args, **kwargs) -> None:
        nonlocal call_count
        with call_guard:
            call_count += 1
            ordinal = call_count
        if ordinal == 1:
            first_at_commit.set()
            if not release_first.wait(timeout=5):
                raise TimeoutError("concurrent edit test did not release first commit")
        else:
            second_at_commit.set()
        real_commit(*args, **kwargs)

    outcomes: list[object] = []
    with patch.object(dashboard, "_commit_draft_and_lineage", side_effect=hold_first_commit):
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                dashboard.write_project_draft_sections,
                tmp_path,
                "synthetic-release",
                first_payload,
            )
            assert first_at_commit.wait(timeout=5)
            second = executor.submit(
                dashboard.write_project_draft_sections,
                tmp_path,
                "synthetic-release",
                second_payload,
            )
            second_at_commit.wait(timeout=1)
            release_first.set()
            for future in (first, second):
                try:
                    outcomes.append(future.result(timeout=5))
                except Exception as exc:  # noqa: BLE001 - outcomes are asserted below
                    outcomes.append(exc)

    successes = [outcome for outcome in outcomes if isinstance(outcome, dict)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ValueError)
    assert "stale" in str(failures[0])
    manuscript_bytes = manuscript_path.read_bytes()
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert b"First concurrent editorial change." in manuscript_bytes
    assert b"Second concurrent editorial change." not in manuscript_bytes
    assert lineage["manuscript_sha256"] == hashlib.sha256(manuscript_bytes).hexdigest()


def test_draft_two_file_write_failure_rolls_back_both_files(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    payload = _section_edit_payload(tmp_path, "synthetic-review", "Rollback-safe editorial change.")
    before = (manuscript_path.read_bytes(), lineage_path.read_bytes())
    real_atomic_write = dashboard._atomic_write_bytes
    failed = False

    def fail_lineage_once(path: Path, content: bytes) -> None:
        nonlocal failed
        if Path(path) == lineage_path and not failed:
            failed = True
            raise OSError("synthetic lineage commit failure")
        real_atomic_write(path, content)

    with patch.object(dashboard, "_atomic_write_bytes", side_effect=fail_lineage_once):
        with pytest.raises(OSError, match="synthetic lineage commit failure"):
            dashboard.write_project_draft_sections(tmp_path, "synthetic-release", payload)

    assert (manuscript_path.read_bytes(), lineage_path.read_bytes()) == before


def test_draft_and_release_use_the_same_reentrant_lock() -> None:
    from review_writer.delivery import project_release
    from view import serve_review_dashboard as dashboard

    assert dashboard.PROJECT_RELEASE_LOCK is project_release.PROJECT_RELEASE_LOCK
    assert isinstance(project_release.PROJECT_RELEASE_LOCK, type(threading.RLock()))


def test_failed_concurrent_release_rollback_cannot_overwrite_success(tmp_path: Path) -> None:
    from review_writer.delivery import project_release
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    source_path = project / "04_first_draft" / "first_draft.md"
    release_paths = (
        project / "05_final_audit" / "final_draft.md",
        project / "05_final_audit" / "final_draft.docx",
        project / "05_final_audit" / "quality_report.json",
    )
    restore_entered = threading.Event()
    release_restore = threading.Event()
    successful_release_finished = threading.Event()
    real_restore = project_release._restore_release

    def blocking_restore(*args, **kwargs) -> None:
        restore_entered.set()
        if not release_restore.wait(timeout=5):
            raise TimeoutError("concurrent release test did not release rollback")
        real_restore(*args, **kwargs)

    def fake_converter(command, **kwargs):
        if command[0].endswith("missing-python"):
            return project_release.subprocess.CompletedProcess(command, 1, "", "synthetic failure")
        output_path = Path(command[command.index("--output") + 1])
        with zipfile.ZipFile(output_path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
        return project_release.subprocess.CompletedProcess(command, 0, "", "")

    def successful_release() -> dict[str, object]:
        try:
            return build_project_release(project)
        finally:
            successful_release_finished.set()

    with (
        patch.object(project_release, "_restore_release", side_effect=blocking_restore),
        patch.object(project_release.subprocess, "run", side_effect=fake_converter),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        failed = executor.submit(
            build_project_release,
            project,
            project / "missing-python",
        )
        assert restore_entered.wait(timeout=5)
        successful = executor.submit(successful_release)
        successful_release_finished.wait(timeout=1)
        release_restore.set()
        with pytest.raises(ProjectReleaseError, match="DOCX_EXPORT_FAILED"):
            failed.result(timeout=5)
        successful.result(timeout=5)

    assert release_paths[0].read_bytes() == source_path.read_bytes()
    assert zipfile.is_zipfile(release_paths[1])
    report = json.loads(release_paths[2].read_text(encoding="utf-8"))
    assert report["manuscript_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert report["docx_sha256"] == hashlib.sha256(release_paths[1].read_bytes()).hexdigest()


def test_final_dashboard_marks_edited_snapshot_stale_until_release_is_rebuilt(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import build_project_release
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    build_project_release(project)

    ready = dashboard.project_final_payload(tmp_path, "synthetic-release")
    assert ready["release_snapshot"]["matches_authoritative"] is True
    assert ready["release_snapshot"]["docx_exists"] is True
    assert ready["release_status"] == "AI_REVIEWED_BENCHMARK"
    assert ready["manuscript_source"] == "release_snapshot"

    manuscript_path = project / "04_first_draft" / "first_draft.md"
    revised = manuscript_path.read_text(encoding="utf-8").replace(
        "# Synthetic Review\n\n",
        "# Synthetic Review\n\nEditorial context revised by the scientist.\n\n",
        1,
    )
    manuscript_path.write_text(revised, encoding="utf-8")

    stale = dashboard.project_final_payload(tmp_path, "synthetic-release")
    assert stale["release_snapshot"]["matches_authoritative"] is False
    assert stale["release_snapshot"]["docx_exists"] is False
    assert stale["final_draft_docx_exists"] is False
    assert stale["final_draft_docx_path"] == ""
    assert stale["release_status"] == "RELEASE_OUTDATED"
    assert stale["manuscript_source"] == "authoritative_manuscript"
    assert stale["final_draft_md"] == revised

    _update_lineage(
        project,
        manuscript_sha256=hashlib.sha256(revised.encode("utf-8")).hexdigest(),
    )
    build_project_release(project)
    rebuilt = dashboard.project_final_payload(tmp_path, "synthetic-release")
    assert rebuilt["release_snapshot"]["matches_authoritative"] is True
    assert rebuilt["release_snapshot"]["docx_exists"] is True
    assert rebuilt["release_status"] == "AI_REVIEWED_BENCHMARK"
    assert rebuilt["manuscript_source"] == "release_snapshot"

    final_html = (
        Path(__file__).resolve().parents[1] / "view" / "assets" / "dashboard" / "final.html"
    ).read_text(encoding="utf-8")
    assert "payload?.release_snapshot?.matches_authoritative === true" in final_html
    assert "Release outdated" in final_html
    assert "Regenerate DOCX" in final_html
    assert "Current release ready" in final_html
    conditional_download = re.search(
        r'\$\{currentReleaseReady\?`(<a id="docxDownload"[\s\S]*?</a>)`:\'\'\}',
        final_html,
    )
    assert conditional_download, "Download must be absent from the stale DOM, not rendered as a disabled link"
    assert 'href="${fileUrl(payload.final_draft_docx_path)}"' in conditional_download.group(1)
    assert "currentReleaseReady?fileUrl(payload.final_draft_docx_path):'#'" not in final_html
    assert "manuscript_sha256" not in final_html
    assert "docx_sha256" not in final_html


@pytest.mark.parametrize(
    "integrity_failure",
    [
        "missing_report",
        "malformed_report",
        "missing_manuscript_hash",
        "missing_docx_hash",
        "manuscript_hash_mismatch",
        "docx_hash_mismatch",
        "docx_tampered",
    ],
)
def test_final_payload_requires_snapshot_and_reported_artifact_hash_integrity(
    tmp_path: Path,
    integrity_failure: str,
) -> None:
    from review_writer.delivery.project_release import build_project_release
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    build_project_release(project)
    quality_path = project / "05_final_audit" / "quality_report.json"
    docx_path = project / "05_final_audit" / "final_draft.docx"
    if integrity_failure == "missing_report":
        quality_path.unlink()
    elif integrity_failure == "malformed_report":
        quality_path.write_text("[]\n", encoding="utf-8")
    elif integrity_failure == "docx_tampered":
        docx_path.write_bytes(b"replacement-docx-bytes")
    else:
        report = json.loads(quality_path.read_text(encoding="utf-8"))
        if integrity_failure == "missing_manuscript_hash":
            report.pop("manuscript_sha256")
        elif integrity_failure == "missing_docx_hash":
            report.pop("docx_sha256")
        elif integrity_failure == "manuscript_hash_mismatch":
            report["manuscript_sha256"] = "0" * 64
        elif integrity_failure == "docx_hash_mismatch":
            report["docx_sha256"] = "0" * 64
        _write_json(quality_path, report)

    payload = dashboard.project_final_payload(tmp_path, "synthetic-release")

    assert payload["release_snapshot"]["matches_authoritative"] is True
    assert payload["release_snapshot"]["integrity_valid"] is False
    assert payload["release_snapshot"]["docx_exists"] is False
    assert payload["final_draft_docx_exists"] is False
    assert payload["final_draft_docx_path"] == ""
    assert payload["release_status"] == "RELEASE_OUTDATED"


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if not path.is_symlink() and path.is_file()
    }


@pytest.mark.parametrize("stage_name", ["04_first_draft", "05_final_audit"])
def test_final_payload_rejects_symlinked_release_stage_without_reading_outside(
    tmp_path: Path,
    stage_name: str,
) -> None:
    from review_writer.delivery.project_release import build_project_release
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    build_project_release(project)
    stage = project / stage_name
    outside = tmp_path / f"outside-{stage_name}"
    stage.rename(outside)
    stage.symlink_to(outside, target_is_directory=True)
    before = _tree_bytes(outside)

    with pytest.raises(ValueError, match="PROJECT_PATH_INVALID"):
        dashboard.project_final_payload(tmp_path, "synthetic-release")

    assert _tree_bytes(outside) == before


@pytest.mark.parametrize(
    "boundary",
    [
        "project_root",
        "draft_directory",
        "manuscript",
        "lineage",
        "release_directory",
        "snapshot",
        "docx",
        "quality_report",
    ],
)
def test_release_authoritative_symlink_boundaries_fail_closed_and_leave_target_unchanged(
    tmp_path: Path,
    boundary: str,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    outside = tmp_path / f"outside-{boundary}"
    outside.mkdir()
    release_project = project
    protected_root = outside

    if boundary == "project_root":
        release_project = tmp_path / "project-link"
        release_project.symlink_to(project, target_is_directory=True)
        protected_root = project
    elif boundary == "draft_directory":
        target = outside / "04_first_draft"
        (project / "04_first_draft").rename(target)
        (project / "04_first_draft").symlink_to(target, target_is_directory=True)
    elif boundary in {"manuscript", "lineage"}:
        name = "first_draft.md" if boundary == "manuscript" else "manuscript_lineage.json"
        source = project / "04_first_draft" / name
        target = outside / name
        source.rename(target)
        source.symlink_to(target)
    elif boundary == "release_directory":
        target = outside / "05_final_audit"
        target.mkdir()
        (target / "sentinel.txt").write_bytes(b"outside-release-must-not-change")
        (project / "05_final_audit").symlink_to(target, target_is_directory=True)
    else:
        name = {
            "snapshot": "final_draft.md",
            "docx": "final_draft.docx",
            "quality_report": "quality_report.json",
        }[boundary]
        stage = project / "05_final_audit"
        stage.mkdir()
        target = outside / name
        target.write_bytes(f"outside-{boundary}-must-not-change".encode())
        (stage / name).symlink_to(target)

    before = _tree_bytes(protected_root)

    with pytest.raises(ProjectReleaseError):
        build_project_release(release_project)

    assert _tree_bytes(protected_root) == before


@pytest.mark.parametrize("claim_id", [HUMAN_CLAIM_ID, "claim-outside-whitelist"])
def test_release_rejects_nonapproved_claim_references_without_new_release(
    tmp_path: Path,
    claim_id: str,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    _update_lineage(
        project,
        claims=[{"claim_id": claim_id, "section_id": "results"}],
    )

    with pytest.raises(ProjectReleaseError):
        build_project_release(project)

    assert not (project / "05_final_audit" / "final_draft.md").exists()
    assert not (project / "05_final_audit" / "final_draft.docx").exists()
    assert not (project / "05_final_audit" / "quality_report.json").exists()


@pytest.mark.parametrize("failure", ["lineage_drift", "missing_references", "broken_image", "stale_writer_packet"])
def test_release_validation_failures_leave_no_new_release(tmp_path: Path, failure: str) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    if failure == "stale_writer_packet":
        packet_path = project / "02_claims" / "writer_packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["projection_sha256"] = "0" * 64
        _write_json(packet_path, packet)
    else:
        manuscript = manuscript_path.read_text(encoding="utf-8")
        if failure == "lineage_drift":
            manuscript = manuscript.replace("increased", "changed")
        elif failure == "missing_references":
            manuscript = manuscript.split("## References", 1)[0].rstrip() + "\n"
        elif failure == "broken_image":
            manuscript = manuscript.replace("../assets/tiny.png", "../assets/missing.png")
        manuscript_path.write_text(manuscript, encoding="utf-8")
        if failure != "lineage_drift":
            _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())

    with pytest.raises(ProjectReleaseError):
        build_project_release(project)

    assert not (project / "05_final_audit" / "final_draft.md").exists()
    assert not (project / "05_final_audit" / "final_draft.docx").exists()
    assert not (project / "05_final_audit" / "quality_report.json").exists()


@pytest.mark.parametrize("suffix", ["?download=1", "#figure-1"])
def test_release_rejects_image_query_or_fragment_before_docx_export(tmp_path: Path, suffix: str) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "../assets/tiny.png",
        f"../assets/tiny.png{suffix}",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())

    with pytest.raises(ProjectReleaseError, match="IMAGE_INVALID"):
        build_project_release(project)

    assert not (project / "05_final_audit" / "final_draft.docx").exists()


def test_release_uses_literal_percent_encoded_image_path(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    build_project_release(project)
    assert (project / "05_final_audit" / "final_draft.docx").is_file()

    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "../assets/tiny.png",
        "../assets/tiny%2Epng",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())

    with pytest.raises(ProjectReleaseError, match="IMAGE_INVALID"):
        build_project_release(project)


def test_release_rejects_unsafe_image_inside_tilde_fence_before_export(tmp_path: Path) -> None:
    from review_writer.delivery import project_release
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "![Synthetic one-pixel figure](../assets/tiny.png)",
        "~~~\n![Unsafe tilde image](../../outside.png)\n~~~",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())

    with patch.object(project_release.subprocess, "run") as converter:
        with pytest.raises(ProjectReleaseError, match="IMAGE_INVALID"):
            build_project_release(project)

    converter.assert_not_called()


def test_release_ignores_image_text_inside_backtick_fence_and_blocks_no_figure(
    tmp_path: Path,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "![Synthetic one-pixel figure](../assets/tiny.png)",
        "```text\n![Inert code image](../../outside.png)\n```",
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())

    with pytest.raises(ProjectReleaseError) as error:
        build_project_release(project)

    assert error.value.code == "FIGURE_POLICY_INVALID"
    assert not (project / "05_final_audit" / "final_draft.docx").exists()


@pytest.mark.parametrize(
    "unsupported_image",
    [
        "![Synthetic one-pixel figure](<../assets/tiny.png>)",
        '![Synthetic one-pixel figure](../assets/tiny.png "figure title")',
        "![Synthetic one-pixel figure][tiny-figure]",
    ],
    ids=["angle-bracket-url", "optional-title", "reference-form"],
)
def test_release_rejects_every_unsupported_markdown_image_token(
    tmp_path: Path,
    unsupported_image: str,
) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript = manuscript_path.read_text(encoding="utf-8").replace(
        "![Synthetic one-pixel figure](../assets/tiny.png)",
        unsupported_image,
    )
    manuscript_path.write_text(manuscript, encoding="utf-8")
    _update_lineage(project, manuscript_sha256=hashlib.sha256(manuscript.encode("utf-8")).hexdigest())

    with pytest.raises(ProjectReleaseError, match="IMAGE_INVALID"):
        build_project_release(project)

    assert not (project / "05_final_audit" / "final_draft.docx").exists()


def test_failed_export_restores_existing_valid_release(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import ProjectReleaseError, build_project_release

    project = make_release_ready_project(tmp_path)
    build_project_release(project)
    release_paths = (
        project / "05_final_audit" / "final_draft.md",
        project / "05_final_audit" / "final_draft.docx",
        project / "05_final_audit" / "quality_report.json",
    )
    before = {path: path.read_bytes() for path in release_paths}

    with pytest.raises(ProjectReleaseError):
        build_project_release(project, python_executable=project / "missing-python")

    assert {path: path.read_bytes() for path in release_paths} == before
    assert not list((project / "05_final_audit").glob(".*.tmp"))
