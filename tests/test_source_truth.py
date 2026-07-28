from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from review_writer.project.source_truth import (
    SourceTruthError,
    build_all_source_truth,
    build_source_truth_bundle,
    canonical_digest,
    load_source_truth_bundle,
    source_truth_asset,
    write_source_truth_bundle,
)


REAL_CASE = Path(
    "/mnt/c/Users/26960/QW-RW/review-writer-e2e-acceptance-20260728-01/"
    "review-projects/vis-light-olefin-difunctionalization"
)


def _write_bytes(path: Path, value: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _source_truth_project(
    tmp_path: Path,
    *,
    extracted_markdown: bytes = b"# Canonical\nBody\n",
    stale_windows_paths: bool = False,
) -> Path:
    project = tmp_path / "review-projects" / "case"
    pdf_sha = _write_bytes(project / "00_sources/papers/paper-a.pdf", b"%PDF-main-a")
    markdown_sha = _write_bytes(
        project / "01_evidence/mineru/markdown/10_1000_example.md",
        b"# Canonical\nBody\n",
    )
    _write_bytes(
        project / "01_evidence/parses/markdown/10_1000_example.md",
        b"# Canonical\nBody\n",
    )
    extracted = project / "01_evidence/parses/extracted/10_1000_example"
    _write_bytes(extracted / "full.md", extracted_markdown)
    _write_json(
        extracted / "parse_content_list.json",
        [
            {"type": "text", "text": "Canonical", "page_idx": 0, "bbox": [1, 2, 3, 4]},
            {"type": "image", "img_path": "images/figure.jpg", "page_idx": 0, "bbox": [5, 6, 7, 8]},
        ],
    )
    _write_json(extracted / "parse_content_list_v2.json", [])
    _write_json(extracted / "layout.json", {"pages": [{"page_idx": 0}]})
    _write_bytes(extracted / "images/figure.jpg", b"jpeg")
    reading_sha = _write_bytes(
        project / "01_evidence/text_layers/stud-a.reading.txt",
        b"Canonical\f",
    )
    layout_sha = _write_bytes(
        project / "01_evidence/text_layers/stud-a.layout.txt",
        b"Canonical\f",
    )
    _write_json(
        project / "00_sources/acquisition_final_receipt.json",
        {
            "schema_version": "acquisition-final-receipt.v1",
            "studies": [
                {
                    "study_id": "scholarly-a",
                    "doi": "10.1000/example",
                    "document_role": "MAIN",
                    "status": "ACQUIRED",
                    "main_pdf": {
                        "path": "papers/paper-a.pdf",
                        "sha256": pdf_sha,
                        "size_bytes": 11,
                    },
                }
            ],
        },
    )
    _write_json(
        project / "00_sources/source_coverage.json",
        {
            "schema_version": "source-coverage.v1",
            "canonical_artifact": "00_sources/source_coverage.json",
            "studies": [
                {
                    "study_id": "scholarly-a",
                    "available_roles": ["MAIN"],
                    "main_policy": "REQUIRED",
                    "si_policy": "NOT_REQUIRED",
                    "study_status": "READY",
                }
            ],
        },
    )
    _write_json(
        project / "00_sources/source_identity_audit.json",
        {
            "schema_version": "source-identity-audit.v1",
            "results": [
                {
                    "candidate_id": "scholarly-a",
                    "doi": "10.1000/example",
                    "title": "Example",
                    "verdict": "PASS",
                }
            ],
        },
    )
    _write_json(
        project / "01_evidence/mineru/manifest.json",
        {
            "schema_version": "mineru-parse-manifest.v1",
            "completed": [
                {
                    "data_id": "001-10_1000_example",
                    "slug": "10_1000_example",
                    "state": "done",
                    "relative_pdf_path": "papers/paper-a.pdf",
                    "markdown_copy": "markdown/10_1000_example.md",
                }
            ],
        },
    )
    windows_root = r"C:\stale\review-project" if stale_windows_paths else str(project)
    _write_json(
        project / "01_evidence/parses/manifest.json",
        {
            "schema_version": "mineru-batch-parse.v1",
            "completed": [
                {
                    "data_id": "001-10_1000_example",
                    "slug": "10_1000_example",
                    "state": "done",
                    "full_md": windows_root + r"\01_evidence\parses\extracted\10_1000_example\full.md",
                    "extracted_dir": windows_root + r"\01_evidence\parses\extracted\10_1000_example",
                    "markdown_copy": windows_root + r"\01_evidence\parses\markdown\10_1000_example.md",
                }
            ],
        },
    )
    _write_json(
        project / "01_evidence/text_layers/text_layers.manifest.json",
        {
            "schema_version": "pdf-text-layers.v1",
            "sources": [
                {
                    "source_id": "stud-a",
                    "pdf_name": "paper-a.pdf",
                    "pdf_sha256": pdf_sha,
                    "page_count": 1,
                    "reading_order_path": "stud-a.reading.txt",
                    "reading_order_sha256": reading_sha,
                    "layout_path": "stud-a.layout.txt",
                    "layout_sha256": layout_sha,
                }
            ],
        },
    )
    assert markdown_sha == hashlib.sha256(b"# Canonical\nBody\n").hexdigest()
    return project


def test_bundle_closes_study_slug_and_source_id_by_verified_pdf(tmp_path: Path) -> None:
    project = _source_truth_project(tmp_path)

    bundle = build_source_truth_bundle(project, "scholarly-a")

    source = bundle["sources"][0]
    assert bundle["schema_version"] == "source-truth-bundle.v1"
    assert bundle["study_id"] == "scholarly-a"
    assert source["source_id"] == "stud-a"
    assert source["mineru_slug"] == "10_1000_example"
    assert source["pdf"]["path"] == "00_sources/papers/paper-a.pdf"
    assert source["canonical_markdown"]["path"] == (
        "01_evidence/mineru/markdown/10_1000_example.md"
    )
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    assert bundle["bundle_digest"] == canonical_digest(body)


def test_bundle_ignores_absolute_parse_manifest_paths(tmp_path: Path) -> None:
    project = _source_truth_project(tmp_path, stale_windows_paths=True)

    bundle = build_source_truth_bundle(project, "scholarly-a")

    serialized = json.dumps(bundle)
    assert "C:\\\\" not in serialized
    assert "/home/" not in serialized


def test_bundle_rejects_hash_mismatch_and_symlink(tmp_path: Path) -> None:
    project = _source_truth_project(tmp_path / "hash")
    (project / "00_sources/papers/paper-a.pdf").write_bytes(b"changed")
    with pytest.raises(SourceTruthError, match="SOURCE_PDF_HASH_MISMATCH"):
        build_source_truth_bundle(project, "scholarly-a")

    project = _source_truth_project(tmp_path / "link")
    markdown = project / "01_evidence/mineru/markdown/10_1000_example.md"
    markdown.unlink()
    markdown.symlink_to(project / "01_evidence/parses/markdown/10_1000_example.md")
    with pytest.raises(SourceTruthError, match="SOURCE_ASSET_INVALID"):
        build_source_truth_bundle(project, "scholarly-a")


def test_bundle_marks_duplicate_markdown_drift_without_switching_canonical(
    tmp_path: Path,
) -> None:
    project = _source_truth_project(tmp_path, extracted_markdown=b"different")

    bundle = build_source_truth_bundle(project, "scholarly-a")

    assert bundle["warnings"] == ["duplicate_parse_drift"]
    assert bundle["sources"][0]["canonical_markdown"]["path"].startswith(
        "01_evidence/mineru/markdown/"
    )


def test_write_load_and_asset_access_revalidate_current_bytes(tmp_path: Path) -> None:
    project = _source_truth_project(tmp_path)
    written = write_source_truth_bundle(project, "scholarly-a")
    assert load_source_truth_bundle(project, "scholarly-a") == written
    assert source_truth_asset(project, "scholarly-a", "stud-a", "pdf").name == "paper-a.pdf"
    assert source_truth_asset(
        project,
        "scholarly-a",
        "stud-a",
        "parsed-markdown",
    ).name == "10_1000_example.md"

    (project / "00_sources/papers/paper-a.pdf").write_bytes(b"changed")
    with pytest.raises(SourceTruthError, match="SOURCE_ASSET_DRIFT"):
        source_truth_asset(project, "scholarly-a", "stud-a", "pdf")


def test_real_three_paper_case_is_read_only_compatible() -> None:
    if not REAL_CASE.is_dir():
        pytest.skip("local three-paper case is unavailable")
    before = {
        path.relative_to(REAL_CASE).as_posix(): path.stat().st_mtime_ns
        for path in REAL_CASE.rglob("*")
        if path.is_file()
    }

    bundles = build_all_source_truth(REAL_CASE)

    assert len(bundles) == 3
    assert sorted(bundle["sources"][0]["page_count"] for bundle in bundles) == [6, 11, 11]
    assert len({bundle["sources"][0]["source_id"] for bundle in bundles}) == 3
    assert all(bundle["warnings"] == ["duplicate_parse_drift"] for bundle in bundles)
    assert all(
        not Path(descriptor["path"]).is_absolute()
        for bundle in bundles
        for source in bundle["sources"]
        for descriptor in (
            source["pdf"],
            source["canonical_markdown"],
            source["content_list"],
            source["layout"],
            source["reading_layer"],
            source["layout_layer"],
        )
    )
    after = {
        path.relative_to(REAL_CASE).as_posix(): path.stat().st_mtime_ns
        for path in REAL_CASE.rglob("*")
        if path.is_file()
    }
    assert after == before
