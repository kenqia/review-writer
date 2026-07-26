from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from review_writer.project.vertical_review import (
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
    packet = build_writer_packet(project)
    manuscript = (
        "# Synthetic Review\n\n"
        "## Results\n\n"
        f"{APPROVED_CLAIM_TEXT} [1].\n\n"
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

    dashboard.write_project_draft_sections(tmp_path, "synthetic-release", payload)

    after_lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert after_lineage["manuscript_sha256"] == hashlib.sha256(manuscript_path.read_bytes()).hexdigest()
    assert {key: value for key, value in after_lineage.items() if key != "manuscript_sha256"} == {
        key: value for key, value in before_lineage.items() if key != "manuscript_sha256"
    }
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


def test_claim_span_edit_is_rejected_with_manuscript_and_lineage_unchanged(tmp_path: Path) -> None:
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
    before = (manuscript_path.read_bytes(), lineage_path.read_bytes())

    with pytest.raises(ValueError, match="LINEAGE"):
        dashboard.write_project_draft_sections(tmp_path, "synthetic-release", payload)

    assert (manuscript_path.read_bytes(), lineage_path.read_bytes()) == before


def test_duplicate_claim_span_edit_is_rejected_with_both_files_unchanged(tmp_path: Path) -> None:
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    lineage_path = project / "04_first_draft" / "manuscript_lineage.json"
    draft = dashboard.project_draft_payload(tmp_path, "synthetic-release")
    results = next(section for section in draft["sections"] if section["id"] == "results")
    payload = {
        "section_id": "results",
        "body": f"{results['body']}\n\n{APPROVED_CLAIM_TEXT} [1].",
        "manuscript_version": draft["manuscript_version"],
    }
    before = (manuscript_path.read_bytes(), lineage_path.read_bytes())

    with pytest.raises(ValueError, match="LINEAGE"):
        dashboard.write_project_draft_sections(tmp_path, "synthetic-release", payload)

    assert (manuscript_path.read_bytes(), lineage_path.read_bytes()) == before


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


def test_final_dashboard_marks_edited_snapshot_stale_until_release_is_rebuilt(tmp_path: Path) -> None:
    from review_writer.delivery.project_release import build_project_release
    from view import serve_review_dashboard as dashboard

    project = make_release_ready_project(tmp_path / "review-projects")
    build_project_release(project)

    ready = dashboard.project_final_payload(tmp_path, "synthetic-release")
    assert ready["release_snapshot"]["matches_authoritative"] is True
    assert ready["release_snapshot"]["docx_exists"] is True
    assert ready["release_status"] == "AI_REVIEWED_BENCHMARK"

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

    _update_lineage(
        project,
        manuscript_sha256=hashlib.sha256(revised.encode("utf-8")).hexdigest(),
    )
    build_project_release(project)
    rebuilt = dashboard.project_final_payload(tmp_path, "synthetic-release")
    assert rebuilt["release_snapshot"]["matches_authoritative"] is True
    assert rebuilt["release_snapshot"]["docx_exists"] is True
    assert rebuilt["release_status"] == "AI_REVIEWED_BENCHMARK"

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
