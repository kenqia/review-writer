from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from zipfile import ZipFile

import pytest
from jsonschema import Draft202012Validator

from review_writer.evaluation.review_benchmark import (
    BenchmarkError,
    RUBRIC_DIMENSIONS,
    evaluate_review,
    validate_report,
)
from review_writer.evaluation import review_benchmark
from review_writer.evaluation.standard_corpus import (
    GUIDE_SLUGS,
    REVIEW_SLUGS,
    StandardCorpusError,
    load_standard_corpus,
)
from review_writer.project.source_truth import canonical_digest
from scripts.validators import validate_review_benchmark as benchmark_validator


ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = ROOT / "schemas/quality/review_benchmark_report.v1.schema.json"
VALIDATOR = ROOT / "scripts/validators/validate_review_benchmark.py"


def _scores(values: tuple[int, ...]) -> list[dict[str, object]]:
    assert len(values) == len(RUBRIC_DIMENSIONS)
    return [
        {
            "dimension_id": dimension_id,
            "score": score,
            "rationale": f"Independent evidence-based rationale for {dimension_id}.",
        }
        for (dimension_id, _maximum), score in zip(RUBRIC_DIMENSIONS, values, strict=True)
    ]


def _placeholder(*, status: str = "awaiting_human_figure") -> dict[str, object]:
    return {
        "placeholder_id": "synthesis-figure-01",
        "scientific_question": "How do the studies differ?",
        "reader_takeaway": "The comparison remains bounded to the reported studies.",
        "panels": [
            {
                "panel": "A",
                "task": "Compare the approved operating windows.",
                "synthesis_claim_ids": ["synthesis-one"],
                "source_figure_ids": ["source-figure-one"],
            }
        ],
        "comparison_axis": "reported operating window",
        "required_labels_units": ["temperature (C)"],
        "counter_evidence": ["No shared productivity metric"],
        "forbidden_overclaims": ["Do not rank manufacturing readiness"],
        "unresolved_uncertainties": ["Photon flux was not normalized"],
        "caption_draft": "Reported operating windows; NR denotes not reported.",
        "target_size": "full width",
        "status": status,
    }


def _chemical_lineage(*, with_dependency: bool) -> dict[str, object]:
    return {
        "chemical_paper_import_digests": [
            {
                "study_id": "study-a",
                "import_digest": "a" * 64,
                "state_digest": "b" * 64,
            }
        ],
        "chemical_paper_safe_summary": {
            "schema_version": "chemical-paper-safe-summary.v1",
            "route": "chemical-paper-zip-only",
            "study_count": 1,
            "molecule_count": 125,
            "unresolved_field_count": 32,
            "element_review_counts": {
                "not_reviewed": 125,
                "confirmed": 0,
                "corrected": 0,
                "not_applicable": 0,
            },
            "reaction_data_status": "unavailable_not_provided",
        },
        "chemical_paper_claim_dependencies": (
            [
                {
                    "claim_id": "claim-a",
                    "study_id": "study-a",
                    "molecule_index": 0,
                    "required_fields": ["smiles_expanded"],
                    "requires_element_review": False,
                    "requires_reaction_data": False,
                }
            ]
            if with_dependency
            else []
        ),
    }


def _chemical_currentness(*, blocked: bool) -> dict[str, object]:
    if not blocked:
        return {
            "schema_version": "chemical-paper-dependency-currentness.v1",
            "lineage_binding_status": "current",
            "claims": [],
            "can_release": True,
            "blocking_reasons": [],
        }
    reasons = ["CHEMICAL_REQUIRED_FIELD_UNRESOLVED"]
    return {
        "schema_version": "chemical-paper-dependency-currentness.v1",
        "lineage_binding_status": "current",
        "claims": [
            {
                "claim_id": "claim-a",
                "status": "needs_review",
                "dependencies": [
                    {
                        "study_id": "study-a",
                        "molecule_index": 0,
                        "status": "needs_review",
                        "required_field_statuses": {"smiles_expanded": "unresolved"},
                        "element_review_state": "not_reviewed",
                        "reaction_data_status": "unavailable_not_provided",
                        "blocking_reasons": reasons,
                    }
                ],
                "blocking_reasons": reasons,
            }
        ],
        "can_release": False,
        "blocking_reasons": reasons,
    }


def _project_release(
    root: Path,
    monkeypatch: pytest.MonkeyPatch | None,
    *,
    level: str = "SELF_REVIEWED_DRAFT",
    placeholders: list[dict[str, object]] | None = None,
    authoritative: bool = True,
    snapshot_manuscript_sha256: str | None = None,
    embed_verified_figures: bool = True,
    chemical_paper: dict[str, object] | None = None,
    chemical_blocked: bool = False,
) -> Path:
    placeholders = list(placeholders or [])
    manuscript = "# Synthetic review\n"
    if any(row.get("status") != "verified" for row in placeholders):
        manuscript += "\nSYNTHESIS_FIGURE_PLACEHOLDER: synthesis-figure-01\n"
    manuscript_path = root / "04_manuscript/manuscript.md"
    lineage_path = root / "04_manuscript/manuscript_lineage.v2.json"
    placeholder_path = root / "03_figures/synthesis_figure_placeholders.json"
    docx_path = root / (
        "05_release/self_reviewed_draft.docx"
        if level == "SELF_REVIEWED_DRAFT"
        else "05_release/expert_reviewed_release.docx"
    )
    if authoritative:
        manuscript_path.parent.mkdir(parents=True, exist_ok=True)
        manuscript_path.write_text(manuscript, encoding="utf-8")
        placeholder_path.parent.mkdir(parents=True, exist_ok=True)
        placeholder_path.write_text(
            json.dumps({"placeholders": placeholders}) + "\n",
            encoding="utf-8",
        )
        lineage = {
            "manuscript_sha256": _sha256(manuscript_path),
            "lineage_digest": "c" * 64,
            "synthesis_figure_placeholder_digest": canonical_digest(placeholders),
        }
        if chemical_paper is not None:
            lineage.update(chemical_paper)
        lineage_path.write_text(json.dumps(lineage) + "\n", encoding="utf-8")
        if any(row.get("status") == "verified" for row in placeholders):
            asset_path = root / "03_figures/synthesis-figure-01.png"
            asset_path.write_bytes(b"human-verified-synthesis-figure")
            if embed_verified_figures:
                manuscript_path.write_text(
                    manuscript
                    + "\nHUMAN_SYNTHESIS_FIGURE: 03_figures/synthesis-figure-01.png\n",
                    encoding="utf-8",
                )
                lineage["manuscript_sha256"] = _sha256(manuscript_path)
                lineage_path.write_text(json.dumps(lineage) + "\n", encoding="utf-8")
            verification = {
                "placeholder_id": "synthesis-figure-01",
                "asset_path": asset_path.relative_to(root).as_posix(),
                "asset_sha256": _sha256(asset_path),
                "placeholder_digest": canonical_digest(placeholders),
                "lineage_digest": lineage["lineage_digest"],
                "verification": {
                    "schema_version": "verification-decision.v1",
                    "actor_type": "human_researcher",
                    "actor_label": "test-human",
                    "action": "verify",
                    "reason": "Human verified the uploaded synthesis figure against the brief.",
                    "decided_at": "2026-07-29T00:00:00Z",
                    "bound_object_digest": canonical_digest(
                        {
                            "placeholder_digest": canonical_digest(placeholders),
                            "placeholder_id": "synthesis-figure-01",
                            "asset_path": asset_path.relative_to(root).as_posix(),
                            "asset_sha256": _sha256(asset_path),
                            "lineage_digest": lineage["lineage_digest"],
                        }
                    ),
                    "bound_gate_digest": lineage["lineage_digest"],
                },
            }
            (root / "03_figures/synthesis_figure_verification.json").write_text(
                json.dumps({"verifications": [verification]}) + "\n",
                encoding="utf-8",
            )
        if monkeypatch is not None:
            monkeypatch.setattr(
                review_benchmark,
                "manuscript_state",
                lambda _: {
                    "workflow_can_continue": True,
                    "reason_code": "MANUSCRIPT_APPROVED",
                    "manuscript_sha256": lineage["manuscript_sha256"],
                    "lineage_digest": lineage["lineage_digest"],
                },
            )
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    if any(row.get("status") == "verified" for row in placeholders) and embed_verified_figures:
        with ZipFile(docx_path, "w") as package:
            package.writestr("word/document.xml", manuscript_path.read_text(encoding="utf-8"))
            package.writestr("word/media/synthesis-figure-01.png", b"human-verified-synthesis-figure")
    else:
        docx_path.write_bytes(b"synthetic-docx")
    snapshot = {
        "project_id": root.name,
        "release_level": level,
        "manuscript_sha256": snapshot_manuscript_sha256 or (
            _sha256(manuscript_path) if manuscript_path.is_file() else "a" * 64
        ),
        "lineage_digest": "c" * 64,
        "docx_path": docx_path.relative_to(root).as_posix(),
        "docx_sha256": _sha256(docx_path),
    }
    if chemical_paper is not None:
        from review_writer.delivery.chemical_paper_release import (
            analyze_chemical_paper_release,
            safe_chemical_paper_projection,
        )

        chemical_state = analyze_chemical_paper_release(lineage)
        currentness = _chemical_currentness(blocked=chemical_blocked)
        snapshot["chemical_paper_binding_digest"] = chemical_state["binding_digest"]
        snapshot["chemical_paper_safe_summary"] = safe_chemical_paper_projection(
            chemical_state
        )
        snapshot["chemical_paper_dependency_can_release"] = not chemical_blocked
        if monkeypatch is not None:
            monkeypatch.setattr(
                review_benchmark,
                "dependency_currentness_for_project",
                lambda *_args, **_kwargs: currentness,
            )
    (root / "05_release/release_snapshot.json").write_text(
        json.dumps(snapshot) + "\n",
        encoding="utf-8",
    )
    return root


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _standard_corpus(root: Path) -> Path:
    jobs: list[dict[str, str]] = []
    for slug in (*REVIEW_SLUGS, *GUIDE_SLUGS):
        markdown = root / f"mineru-outputs/markdown/{slug}.md"
        origin = root / f"mineru-outputs/extracted/{slug}/{slug}_origin.pdf"
        _write(markdown, f"# {slug}\n".encode())
        _write(origin, f"%PDF synthetic {slug}\n".encode())
        jobs.append({"slug": slug, "pdf_name": f"{slug}.pdf", "state": "done"})
    mineru_manifest = root / "mineru-outputs/manifest.json"
    _write(
        mineru_manifest,
        (json.dumps({"batches": [{"jobs": jobs}]}, sort_keys=True) + "\n").encode(),
    )
    existing_count = sum(path.is_file() for path in (root / "mineru-outputs").rglob("*"))
    for index in range(1071 - existing_count):
        _write(
            root / f"mineru-outputs/sidecars/filler-{index:04d}.json",
            b"{}\n",
        )
    source_zip = root / "source/standard.zip"
    source_zip.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(source_zip, "w") as archive:
        archive.writestr("nr-chemdraw-stylesheet.cds", b"synthetic stylesheet")
    files = []
    for path in sorted((root / "mineru-outputs").rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    manifest = {
        "schema_version": "standard-corpus-manifest.v1",
        "created_at": "2026-07-28T00:00:00Z",
        "source_zip": {
            "path": "source/standard.zip",
            "sha256": _sha256(source_zip),
            "size_bytes": source_zip.stat().st_size,
        },
        "source_zip_sha256": _sha256(source_zip),
        "pdf_count": 14,
        "mineru_success_count": 14,
        "mineru_failure_count": 0,
        "file_count": len(files),
        "files": files,
    }
    _write(
        root / "standard_corpus_manifest.json",
        (json.dumps(manifest, sort_keys=True) + "\n").encode(),
    )
    return root


def test_hard_fail_overrides_numeric_score(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = evaluate_review(
        _project_release(tmp_path / "project", monkeypatch),
        _scores((10, 15, 20, 19, 14, 9, 9)),
        hard_fails=["WRONG_SOURCE_BINDING"],
    )

    assert report["status"] == "fail"
    assert report["score"] == 96
    assert report["hard_fails"] == ["WRONG_SOURCE_BINDING"]


def test_internal_placeholder_is_reported_but_not_internal_hard_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = evaluate_review(
        _project_release(
            tmp_path / "project",
            monkeypatch,
            placeholders=[_placeholder()],
        ),
        _scores((9, 13, 17, 17, 12, 8, 8)),
    )

    assert report["status"] == "pass_internal"
    assert report["score"] == 84
    assert report["hard_fails"] == []
    assert report["issues"] == ["SYNTHESIS_FIGURE_PENDING"]
    assert report["expert_release_ready"] is False


def test_internal_chemical_gaps_are_issues_and_blocked_dependency_is_not_internal_hard_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = evaluate_review(
        _project_release(
            tmp_path / "project",
            monkeypatch,
            chemical_paper=_chemical_lineage(with_dependency=True),
            chemical_blocked=True,
        ),
        _scores((10, 15, 20, 20, 15, 10, 10)),
    )

    assert report["status"] == "pass_internal"
    assert report["hard_fails"] == []
    assert "CHEMICAL_DEPENDENCY_UNRESOLVED" in report["issues"]
    assert report["chemical_paper_safe_summary"]["reaction_data_status"] == (
        "unavailable_not_provided"
    )
    assert report["expert_release_ready"] is False


def test_expert_evaluation_hard_fails_only_when_claim_dependency_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = evaluate_review(
        _project_release(
            tmp_path / "blocked",
            monkeypatch,
            level="EXPERT_REVIEWED_RELEASE",
            chemical_paper=_chemical_lineage(with_dependency=True),
            chemical_blocked=True,
        ),
        _scores((10, 15, 20, 20, 15, 10, 10)),
    )
    unused_gaps = evaluate_review(
        _project_release(
            tmp_path / "unused",
            monkeypatch,
            level="EXPERT_REVIEWED_RELEASE",
            chemical_paper=_chemical_lineage(with_dependency=False),
        ),
        _scores((10, 15, 20, 20, 15, 10, 10)),
    )

    assert blocked["hard_fails"] == ["CHEMICAL_DEPENDENCY_UNRESOLVED"]
    assert blocked["expert_release_ready"] is False
    assert unused_gaps["hard_fails"] == []
    assert unused_gaps["status"] == "pass_expert"
    assert unused_gaps["expert_release_ready"] is True


def test_benchmark_validator_rejects_tampered_chemical_dependency_consistency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = evaluate_review(
        _project_release(
            tmp_path / "project",
            monkeypatch,
            chemical_paper=_chemical_lineage(with_dependency=True),
            chemical_blocked=True,
        ),
        _scores((10, 15, 20, 20, 15, 10, 10)),
    )
    report["issues"].remove("CHEMICAL_DEPENDENCY_UNRESOLVED")
    report["expert_release_ready"] = True

    with pytest.raises(BenchmarkError, match="BENCHMARK_REPORT_INCONSISTENT"):
        review_benchmark.validate_report(report)


def test_benchmark_validator_rejects_safe_summary_gap_omitted_from_issues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = evaluate_review(
        _project_release(
            tmp_path / "project",
            monkeypatch,
            chemical_paper=_chemical_lineage(with_dependency=False),
        ),
        _scores((10, 15, 20, 20, 15, 10, 10)),
    )
    report["issues"].remove("CHEMICAL_FIELDS_UNRESOLVED")

    with pytest.raises(BenchmarkError, match="BENCHMARK_REPORT_INCONSISTENT"):
        review_benchmark.validate_report(report)


def test_expert_release_hard_fails_while_required_synthesis_figure_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = evaluate_review(
        _project_release(
            tmp_path / "project",
            monkeypatch,
            level="EXPERT_REVIEWED_RELEASE",
            placeholders=[_placeholder()],
        ),
        _scores((10, 15, 20, 20, 15, 10, 10)),
    )

    assert report["status"] == "fail"
    assert report["hard_fails"] == ["SYNTHESIS_FIGURE_PENDING"]


def test_release_level_cannot_override_authoritative_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_release(tmp_path / "project", monkeypatch)

    with pytest.raises(BenchmarkError, match="BENCHMARK_RELEASE_LEVEL_MISMATCH"):
        evaluate_review(
            project,
            _scores((10, 15, 20, 20, 15, 10, 10)),
            release_level="EXPERT_REVIEWED_RELEASE",
        )


def test_standard_corpus_loader_binds_hashes_and_expected_layers(tmp_path: Path) -> None:
    corpus_root = _standard_corpus(tmp_path / "standards")

    corpus = load_standard_corpus(corpus_root)

    assert corpus["review_count"] == 8
    assert corpus["guide_count"] == 6
    assert corpus["stylesheet_count"] == 1
    assert corpus["pdf_count"] == 14
    assert corpus["mineru_success_count"] == 14
    assert corpus["mineru_failure_count"] == 0
    assert corpus["manifest_sha256"] == _sha256(corpus_root / "standard_corpus_manifest.json")


def test_standard_corpus_loader_rejects_file_hash_drift(tmp_path: Path) -> None:
    corpus_root = _standard_corpus(tmp_path / "standards")
    target = corpus_root / f"mineru-outputs/markdown/{REVIEW_SLUGS[0]}.md"
    target.write_text("changed\n", encoding="utf-8")

    with pytest.raises(StandardCorpusError, match="STANDARD_CORPUS_HASH_MISMATCH"):
        load_standard_corpus(corpus_root)


def test_standard_corpus_loader_rejects_manifest_with_1070_files(tmp_path: Path) -> None:
    corpus_root = _standard_corpus(tmp_path / "standards")
    manifest_path = corpus_root / "standard_corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    filler = next(row for row in manifest["files"] if "/sidecars/filler-" in row["path"])
    (corpus_root / filler["path"]).unlink()
    manifest["files"].remove(filler)
    manifest["file_count"] = len(manifest["files"])
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(StandardCorpusError, match="STANDARD_CORPUS_MANIFEST_INVALID"):
        load_standard_corpus(corpus_root)


def test_standard_corpus_loader_rejects_manifest_with_1072_files(tmp_path: Path) -> None:
    corpus_root = _standard_corpus(tmp_path / "standards")
    extra = corpus_root / "mineru-outputs/sidecars/extra.json"
    _write(extra, b"{}\n")
    manifest_path = corpus_root / "standard_corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {
            "path": extra.relative_to(corpus_root).as_posix(),
            "sha256": _sha256(extra),
            "size_bytes": extra.stat().st_size,
        }
    )
    manifest["file_count"] = len(manifest["files"])
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(StandardCorpusError, match="STANDARD_CORPUS_MANIFEST_INVALID"):
        load_standard_corpus(corpus_root)


def test_standard_corpus_loader_recounts_actual_pdf_files(tmp_path: Path) -> None:
    corpus_root = _standard_corpus(tmp_path / "standards")
    filler = next((corpus_root / "mineru-outputs/sidecars").glob("filler-*.json"))
    renamed = filler.with_suffix(".pdf")
    filler.rename(renamed)
    manifest_path = corpus_root / "standard_corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = next(item for item in manifest["files"] if item["path"] == filler.relative_to(corpus_root).as_posix())
    row["path"] = renamed.relative_to(corpus_root).as_posix()
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(StandardCorpusError, match="STANDARD_CORPUS_MINERU_INCOMPLETE"):
        load_standard_corpus(corpus_root)


def test_missing_authoritative_manuscript_is_stable_hard_fail(tmp_path: Path) -> None:
    project = _project_release(
        tmp_path / "project",
        None,
        authoritative=False,
    )

    with pytest.raises(BenchmarkError, match="BENCHMARK_MANUSCRIPT_NOT_APPROVED"):
        evaluate_review(
            project,
            _scores((10, 15, 20, 20, 15, 10, 10)),
        )


def test_snapshot_manuscript_digest_drift_is_hard_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_release(
        tmp_path / "project",
        monkeypatch,
        snapshot_manuscript_sha256="d" * 64,
    )

    report = evaluate_review(project, _scores((10, 15, 20, 20, 15, 10, 10)))

    assert report["status"] == "fail"
    assert "STATE_SURFACE_DIVERGENCE" in report["hard_fails"]


def test_internal_release_rejects_incomplete_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_release(
        tmp_path / "project",
        monkeypatch,
        placeholders=[{}],
    )

    report = evaluate_review(project, _scores((10, 15, 20, 20, 15, 10, 10)))

    assert report["status"] == "fail"
    assert "STATE_SURFACE_DIVERGENCE" in report["hard_fails"]


def test_pending_placeholder_requires_visible_placeholder_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_release(
        tmp_path / "project",
        monkeypatch,
        placeholders=[_placeholder()],
    )
    manuscript_path = project / "04_manuscript/manuscript.md"
    lineage_path = project / "04_manuscript/manuscript_lineage.v2.json"
    snapshot_path = project / "05_release/release_snapshot.json"
    manuscript_path.write_text("# Synthetic review\n\nsynthesis-figure-01\n", encoding="utf-8")
    manuscript_sha256 = _sha256(manuscript_path)
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    lineage["manuscript_sha256"] = manuscript_sha256
    lineage_path.write_text(json.dumps(lineage) + "\n", encoding="utf-8")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["manuscript_sha256"] = manuscript_sha256
    snapshot_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        review_benchmark,
        "manuscript_state",
        lambda _: {
            "workflow_can_continue": True,
            "reason_code": "MANUSCRIPT_APPROVED",
            "manuscript_sha256": manuscript_sha256,
            "lineage_digest": lineage["lineage_digest"],
        },
    )

    report = evaluate_review(project, _scores((10, 15, 20, 20, 15, 10, 10)))

    assert report["status"] == "fail"
    assert "STATE_SURFACE_DIVERGENCE" in report["hard_fails"]


def test_expert_release_accepts_complete_verified_placeholder_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_release(
        tmp_path / "project",
        monkeypatch,
        level="EXPERT_REVIEWED_RELEASE",
        placeholders=[_placeholder(status="verified")],
    )

    report = evaluate_review(project, _scores((10, 15, 20, 20, 15, 10, 10)))

    assert report["status"] == "pass_expert"
    assert report["expert_release_ready"] is True


def test_expert_release_rejects_verified_placeholder_without_human_asset_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_release(
        tmp_path / "project",
        monkeypatch,
        level="EXPERT_REVIEWED_RELEASE",
        placeholders=[_placeholder(status="verified")],
        embed_verified_figures=False,
    )
    (project / "03_figures/synthesis_figure_verification.json").unlink()

    report = evaluate_review(project, _scores((10, 15, 20, 20, 15, 10, 10)))

    assert report["status"] == "fail"
    assert "SYNTHESIS_FIGURE_PENDING" in report["hard_fails"]
    assert report["expert_release_ready"] is False


def test_expert_release_rejects_verified_figure_detached_from_manuscript_and_docx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_release(
        tmp_path / "project",
        monkeypatch,
        level="EXPERT_REVIEWED_RELEASE",
        placeholders=[_placeholder(status="verified")],
        embed_verified_figures=False,
    )

    report = evaluate_review(project, _scores((10, 15, 20, 20, 15, 10, 10)))

    assert report["status"] == "fail"
    assert "SYNTHESIS_FIGURE_PENDING" in report["hard_fails"]


def test_expert_release_rejects_asset_replaced_after_human_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_release(
        tmp_path / "project",
        monkeypatch,
        level="EXPERT_REVIEWED_RELEASE",
        placeholders=[_placeholder(status="verified")],
    )
    asset = project / "03_figures/synthesis-figure-01.png"
    replacement = b"replacement-not-human-verified"
    asset.write_bytes(replacement)
    verification_path = project / "03_figures/synthesis_figure_verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification["verifications"][0]["asset_sha256"] = _sha256(asset)
    verification_path.write_text(json.dumps(verification) + "\n", encoding="utf-8")
    docx = project / "05_release/expert_reviewed_release.docx"
    with ZipFile(docx, "w") as package:
        package.writestr("word/document.xml", (project / "04_manuscript/manuscript.md").read_text())
        package.writestr("word/media/synthesis-figure-01.png", replacement)
    snapshot_path = project / "05_release/release_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["docx_sha256"] = _sha256(docx)
    snapshot_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")

    report = evaluate_review(project, _scores((10, 15, 20, 20, 15, 10, 10)))

    assert report["status"] == "fail"
    assert "SYNTHESIS_FIGURE_PENDING" in report["hard_fails"]


def test_validator_rejects_report_only_forgery_without_project_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = evaluate_review(
        _project_release(tmp_path / "project", monkeypatch),
        _scores((9, 13, 17, 17, 12, 8, 8)),
    )
    report_path = tmp_path / "forged-report.json"
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--report", str(report_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert str(report_path) not in result.stdout
    assert str(report_path) not in result.stderr
    assert json.loads(result.stderr)["error_code"] == "BENCHMARK_ARGUMENTS_INVALID"


def test_validator_rejects_report_that_removed_authoritative_hard_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    standards = tmp_path / "standards"
    standards.mkdir()
    score_input = {
        "rubric": _scores((9, 13, 17, 17, 12, 8, 8)),
        "hard_fails": ["WRONG_SOURCE_BINDING"],
    }
    score_path = project / "06_evaluation/review_benchmark_scores.json"
    score_path.parent.mkdir(parents=True, exist_ok=True)
    score_path.write_text(json.dumps(score_input) + "\n", encoding="utf-8")
    report = {
        "rubric": score_input["rubric"],
        "hard_fails": [],
        "release_level": "SELF_REVIEWED_DRAFT",
        "status": "pass_internal",
    }
    report_path = tmp_path / "forged-report.json"
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(benchmark_validator, "validate_report", lambda value: value)
    monkeypatch.setattr(benchmark_validator, "load_standard_corpus", lambda _path: {})

    def fake_evaluate(
        _project: Path,
        rubric: object,
        *,
        hard_fails: object,
        release_level: str,
        standard_corpus: object,
    ) -> dict[str, object]:
        captured.update(rubric=rubric, hard_fails=hard_fails)
        return {**report, "hard_fails": list(hard_fails)}

    monkeypatch.setattr(benchmark_validator, "evaluate_review", fake_evaluate)
    args = Namespace(
        report=report_path,
        project=project,
        standards=standards,
        release_level=None,
        scores=None,
        output=None,
    )

    with pytest.raises(BenchmarkError, match="BENCHMARK_REPORT_MISMATCH"):
        benchmark_validator._run(args)

    assert captured["hard_fails"] == ["WRONG_SOURCE_BINDING"]


def test_report_schema_and_validator_reject_inconsistent_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = evaluate_review(
        _project_release(tmp_path / "project", monkeypatch),
        _scores((9, 13, 17, 17, 12, 8, 8)),
    )
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    report["status"] = "fail"

    with pytest.raises(BenchmarkError, match="BENCHMARK_REPORT_INCONSISTENT"):
        validate_report(report)

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--report", str(report_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stderr)["error_code"] == "BENCHMARK_REPORT_INCONSISTENT"
