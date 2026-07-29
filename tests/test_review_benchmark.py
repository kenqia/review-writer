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
from review_writer.evaluation.standard_corpus import (
    GUIDE_SLUGS,
    REVIEW_SLUGS,
    StandardCorpusError,
    load_standard_corpus,
)


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


def _release(*, level: str = "SELF_REVIEWED_DRAFT", placeholder: bool = False) -> dict[str, object]:
    return {
        "project_id": "synthetic-review",
        "release_level": level,
        "manuscript_sha256": "a" * 64,
        "release_sha256": "b" * 64,
        "synthesis_placeholders": (
            [{"placeholder_id": "synthesis-figure-01", "status": "awaiting_human_figure"}]
            if placeholder
            else []
        ),
    }


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


def test_hard_fail_overrides_numeric_score() -> None:
    report = evaluate_review(
        _release(),
        _scores((10, 15, 20, 19, 14, 9, 9)),
        hard_fails=["WRONG_SOURCE_BINDING"],
    )

    assert report["status"] == "fail"
    assert report["score"] == 96
    assert report["hard_fails"] == ["WRONG_SOURCE_BINDING"]


def test_internal_placeholder_is_reported_but_not_internal_hard_fail() -> None:
    report = evaluate_review(
        _release(placeholder=True),
        _scores((9, 13, 17, 17, 12, 8, 8)),
    )

    assert report["status"] == "pass_internal"
    assert report["score"] == 84
    assert report["hard_fails"] == []
    assert report["issues"] == ["SYNTHESIS_FIGURE_PENDING"]
    assert report["expert_release_ready"] is False


def test_expert_release_hard_fails_while_required_synthesis_figure_is_pending() -> None:
    report = evaluate_review(
        _release(level="EXPERT_REVIEWED_RELEASE", placeholder=True),
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


def test_report_schema_and_validator_reject_inconsistent_status(tmp_path: Path) -> None:
    report = evaluate_review(
        _release(),
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
