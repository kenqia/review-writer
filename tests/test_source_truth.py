from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from review_writer.project.source_truth import (
    SourceTruthError,
    build_all_source_truth,
    build_source_truth_bundle,
    canonical_digest,
    declared_study_ids,
    load_source_truth_bundle,
    source_truth_asset,
    source_truth_asset_snapshot,
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
    _write_json(
        extracted / "parse_content_list_v2.json",
        [
            [
                {
                    "type": "text",
                    "bbox": [1, 2, 3, 4],
                    "content": {"content": "Canonical"},
                },
                {
                    "type": "image",
                    "bbox": [5, 6, 70, 80],
                    "content": {
                        "content": "",
                        "image_source": {"path": "images/figure.jpg"},
                        "image_caption": [
                            {
                                "type": "text",
                                "content": "Figure 1. Source-grounded example figure.",
                            }
                        ],
                        "image_footnote": [],
                    },
                },
            ]
        ],
    )
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
    assert source["content_list_v2"]["path"].endswith(
        "parse_content_list_v2.json"
    )
    assert source["content_list_v2"]["sha256"]
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    assert bundle["bundle_digest"] == canonical_digest(body)


@pytest.mark.parametrize(
    "invalid_row",
    (
        {},
        {"study_id": ""},
        {"study_id": "../escape"},
        {"study_id": "scholarly-a"},
    ),
)
def test_declared_study_ids_rejects_malformed_or_duplicate_receipt_rows(
    tmp_path: Path,
    invalid_row: dict[str, object],
) -> None:
    project = _source_truth_project(tmp_path)
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"].append(invalid_row)
    _write_json(receipt_path, receipt)

    with pytest.raises(SourceTruthError, match="ACQUISITION_FINAL_RECEIPT_INVALID"):
        declared_study_ids(project)


def test_bundle_ignores_absolute_parse_manifest_paths(tmp_path: Path) -> None:
    project = _source_truth_project(tmp_path, stale_windows_paths=True)

    bundle = build_source_truth_bundle(project, "scholarly-a")

    serialized = json.dumps(bundle)
    assert "C:\\\\" not in serialized
    assert "/home/" not in serialized


def test_bundle_requires_one_valid_content_list_v2(tmp_path: Path) -> None:
    missing = _source_truth_project(tmp_path / "missing")
    next(
        (
            missing
            / "01_evidence/parses/extracted/10_1000_example"
        ).glob("*_content_list_v2.json")
    ).unlink()

    with pytest.raises(SourceTruthError, match="CONTENT_LIST_V2_MISSING"):
        build_source_truth_bundle(missing, "scholarly-a")

    malformed = _source_truth_project(tmp_path / "malformed")
    v2 = next(
        (
            malformed
            / "01_evidence/parses/extracted/10_1000_example"
        ).glob("*_content_list_v2.json")
    )
    v2.write_text(json.dumps({"pages": []}), encoding="utf-8")

    with pytest.raises(SourceTruthError, match="CONTENT_LIST_V2_INVALID"):
        build_source_truth_bundle(malformed, "scholarly-a")


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


def test_snapshot_fails_closed_when_secure_open_capabilities_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from review_writer.project import source_truth

    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    source_path = project / "00_sources/papers/paper-a.pdf"
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(source_path.read_bytes())
    real_safe_file = source_truth._safe_file
    swapped = False

    def safe_file_then_swap(root: Path, relative: str, code: str = "SOURCE_ASSET_INVALID") -> Path:
        nonlocal swapped
        path = real_safe_file(root, relative, code)
        if relative == "00_sources/papers/paper-a.pdf" and not swapped:
            swapped = True
            source_path.unlink()
            source_path.symlink_to(outside)
        return path

    real_is_dir = Path.is_dir
    monkeypatch.setattr(source_truth, "_safe_file", safe_file_then_swap)
    monkeypatch.delattr(source_truth.os, "O_NOFOLLOW")
    monkeypatch.setattr(
        Path,
        "is_dir",
        lambda path: False if path == Path("/proc/self/fd") else real_is_dir(path),
    )

    with pytest.raises(SourceTruthError, match="SOURCE_ASSET_SECURITY_UNAVAILABLE"):
        with source_truth_asset_snapshot(
            project,
            "scholarly-a",
            "stud-a",
            "pdf",
        ):
            pass


def test_snapshot_uses_effective_private_permissions_and_cleans_up(tmp_path: Path) -> None:
    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")

    with source_truth_asset_snapshot(
        project,
        "scholarly-a",
        "stud-a",
        "pdf",
    ) as snapshot:
        snapshot_path = snapshot.path
        snapshot_dir = snapshot_path.parent
        assert stat.S_IMODE(snapshot_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(snapshot_path.stat().st_mode) == 0o600
        if hasattr(os, "geteuid"):
            assert snapshot_dir.stat().st_uid == os.geteuid()
            assert snapshot_path.stat().st_uid == os.geteuid()
        assert snapshot_path.read_bytes() == b"%PDF-main-a"
        project_stat = project.resolve().stat()
        assert snapshot.project_instance_root == project.resolve()
        assert snapshot.project_device == project_stat.st_dev
        assert snapshot.project_inode == project_stat.st_ino

    assert not snapshot_dir.exists()


def test_snapshot_rejects_asset_above_server_size_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from review_writer.project import source_truth

    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    monkeypatch.setattr(source_truth, "MAX_SOURCE_ASSET_BYTES", 10, raising=False)

    with pytest.raises(SourceTruthError, match="SOURCE_ASSET_SIZE_INVALID"):
        with source_truth_asset_snapshot(project, "scholarly-a", "stud-a", "pdf"):
            pass


def test_snapshot_semaphore_covers_snapshot_use_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from review_writer.project import source_truth

    class RecordingSemaphore:
        held = False
        released = False

        def acquire(self, *, timeout: float) -> bool:
            assert timeout > 0
            self.held = True
            return True

        def release(self) -> None:
            assert self.held is True
            self.held = False
            self.released = True

    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    semaphore = RecordingSemaphore()
    monkeypatch.setattr(
        source_truth,
        "SOURCE_ASSET_SNAPSHOT_SEMAPHORE",
        semaphore,
        raising=False,
    )

    with source_truth_asset_snapshot(project, "scholarly-a", "stud-a", "pdf") as snapshot:
        snapshot_dir = snapshot.path.parent
        assert semaphore.held is True
        assert snapshot.path.exists()

    assert semaphore.released is True
    assert not snapshot_dir.exists()


def test_snapshot_rejects_busy_server_before_opening_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from review_writer.project import source_truth

    class BusySemaphore:
        def acquire(self, *, timeout: float) -> bool:
            return False

        def release(self) -> None:
            raise AssertionError("unacquired semaphore was released")

    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    monkeypatch.setattr(
        source_truth,
        "SOURCE_ASSET_SNAPSHOT_SEMAPHORE",
        BusySemaphore(),
        raising=False,
    )

    with pytest.raises(SourceTruthError, match="SOURCE_ASSET_BUSY"):
        with source_truth_asset_snapshot(project, "scholarly-a", "stud-a", "pdf"):
            pass


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="fd audit requires procfs")
def test_secure_source_open_closes_fd_when_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from review_writer.project import source_truth

    project = _source_truth_project(tmp_path).resolve()
    before = set(os.listdir("/proc/self/fd"))
    real_fstat = source_truth.os.fstat

    def fail_for_regular_file(file_descriptor: int):
        observed = real_fstat(file_descriptor)
        if stat.S_ISREG(observed.st_mode):
            raise OSError("injected fstat failure")
        return observed

    monkeypatch.setattr(source_truth.os, "fstat", fail_for_regular_file)

    with pytest.raises(SourceTruthError, match="SOURCE_ASSET_INVALID"):
        source_truth._secure_source_fd(
            project,
            "00_sources/papers/paper-a.pdf",
            (project.stat().st_dev, project.stat().st_ino),
        )

    assert set(os.listdir("/proc/self/fd")) == before


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="fd audit requires procfs")
def test_snapshot_closes_created_fd_when_fdopen_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from review_writer.project import source_truth

    project = _source_truth_project(tmp_path)
    write_source_truth_bundle(project, "scholarly-a")
    before = set(os.listdir("/proc/self/fd"))
    real_fdopen = source_truth.os.fdopen

    def fail_snapshot_fdopen(file_descriptor: int, mode: str, *args, **kwargs):
        if mode == "wb":
            raise OSError("injected fdopen failure")
        return real_fdopen(file_descriptor, mode, *args, **kwargs)

    monkeypatch.setattr(source_truth.os, "fdopen", fail_snapshot_fdopen)

    with pytest.raises(OSError, match="injected fdopen failure"):
        with source_truth_asset_snapshot(project, "scholarly-a", "stud-a", "pdf"):
            pass

    assert set(os.listdir("/proc/self/fd")) == before


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
            source["content_list_v2"],
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
