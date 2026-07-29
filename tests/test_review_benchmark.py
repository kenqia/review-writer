from __future__ import annotations

import hashlib
import json
import subprocess
import sys
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


def _project_release(
    root: Path,
    monkeypatch: pytest.MonkeyPatch | None,
    *,
    level: str = "SELF_REVIEWED_DRAFT",
    placeholders: list[dict[str, object]] | None = None,
    authoritative: bool = True,
    snapshot_manuscript_sha256: str | None = None,
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
        lineage_path.write_text(json.dumps(lineage) + "\n", encoding="utf-8")
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


def test_missing_authoritative_manuscript_is_stable_hard_fail(tmp_path: Path) -> None:
    project = _project_release(
        tmp_path / "project",
        None,
        authoritative=False,
    )

    report = evaluate_review(
        project,
        _scores((10, 15, 20, 20, 15, 10, 10)),
    )

    assert report["status"] == "fail"
    assert report["score"] == 100
    assert "STATE_SURFACE_DIVERGENCE" in report["hard_fails"]
    assert report["release_binding"]["manuscript_sha256"] is None


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
