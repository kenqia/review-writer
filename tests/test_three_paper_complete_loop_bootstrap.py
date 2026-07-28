from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = ROOT / "scripts/review/create_three_paper_complete_loop.py"
ARCHIVE_SCRIPT = ROOT / "scripts/review/archive_standard_corpus.py"
STANDARD_ZIP_SHA256 = "92d2546f71d8751d2d150f125cca0e19c801e7c2fffed6ecca2e61c104d90d3e"


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: bytes = b"fixture") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _legacy_three_paper_fixture(root: Path) -> Path:
    _write_json(
        root / "00_brief/review_state.json",
        {"project_id": "legacy-project", "status": "in_progress"},
    )
    for relative in (
        "00_discovery/candidate_pool.json",
        "00_sources/acquisition_final_receipt.json",
        "01_evidence/mineru/manifest.json",
        "01_evidence/parses/manifest.json",
        "01_evidence/text_layers/text_layers.manifest.json",
    ):
        _write_json(root / relative, {"fixture": relative})
    for index in range(3):
        _write(root / f"00_sources/papers/paper-{index}.pdf", f"pdf-{index}".encode())
        _write(root / f"01_evidence/mineru/markdown/paper-{index}.md", b"# Parsed\n")
        _write(root / f"01_evidence/parses/extracted/paper-{index}/full.md", b"# Parsed\n")
        _write(root / f"01_evidence/text_layers/paper-{index}.reading.txt", b"Parsed\n")
    for relative in (
        "01_evidence/evidence_cards.jsonl",
        "02_claims/claim_projection.jsonl",
        "03_review/risk_packet.json",
        "03_figure_redraw/generated.png",
        "04_first_draft/first_draft.md",
        "05_final_audit/final_draft.docx",
    ):
        _write(root / relative, b"legacy")
    return root


def _standard_parse_fixture(root: Path, *, pdf_count: int = 14) -> Path:
    completed = []
    for index in range(pdf_count):
        slug = f"standard-{index:02d}"
        pdf_name = f"{slug}.pdf"
        _write(root / f"extracted/{slug}/{pdf_name}", f"pdf-{index}".encode())
        _write(root / f"extracted/{slug}/full.md", f"# Standard {index}\n".encode())
        _write(root / f"markdown/{slug}.md", f"# Standard {index}\n".encode())
        _write(root / f"raw_zips/{slug}.zip", f"zip-{index}".encode())
        completed.append(
            {
                "pdf_name": pdf_name,
                "slug": slug,
                "state": "done",
            }
        )
    _write_json(
        root / "manifest.json",
        {
            "tool": "mineru-precise-parse-review-writer",
            "queued": pdf_count,
            "completed": pdf_count,
            "failed": 0,
            "batches": [{"jobs": completed}],
        },
    )
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_bootstrap_copies_only_source_and_parse_inputs(tmp_path: Path) -> None:
    bootstrap = _load_script("complete_loop_bootstrap", BOOTSTRAP_SCRIPT)
    source = _legacy_three_paper_fixture(tmp_path / "source")
    target = tmp_path / "target"

    result = bootstrap.create_complete_loop_project(source, target)

    assert result["pdf_count"] == 3
    assert (target / "00_sources/acquisition_final_receipt.json").is_file()
    assert (target / "01_evidence/mineru/manifest.json").is_file()
    review_state = json.loads((target / "00_brief/review_state.json").read_text(encoding="utf-8"))
    assert review_state["project_id"] == target.name
    assert not (target / "01_evidence/evidence_cards.jsonl").exists()
    assert not (target / "02_claims").exists()
    assert not (target / "03_review").exists()
    assert not (target / "03_figure_redraw").exists()
    assert not (target / "04_first_draft").exists()
    assert not (target / "05_final_audit").exists()


def test_bootstrap_refuses_existing_target_without_writing(tmp_path: Path) -> None:
    bootstrap = _load_script("complete_loop_bootstrap_existing", BOOTSTRAP_SCRIPT)
    source = _legacy_three_paper_fixture(tmp_path / "source")
    target = tmp_path / "target"
    _write(target / "keep.txt", b"keep")
    before = _snapshot(target)

    with pytest.raises(bootstrap.BootstrapError, match="TARGET_EXISTS"):
        bootstrap.create_complete_loop_project(source, target)

    assert _snapshot(target) == before


def test_bootstrap_rejects_symlink_without_creating_target(tmp_path: Path) -> None:
    bootstrap = _load_script("complete_loop_bootstrap_symlink", BOOTSTRAP_SCRIPT)
    source = _legacy_three_paper_fixture(tmp_path / "source")
    outside = tmp_path / "outside.txt"
    _write(outside, b"outside")
    (source / "00_sources/linked.txt").symlink_to(outside)
    target = tmp_path / "target"

    with pytest.raises(bootstrap.BootstrapError, match="SOURCE_REPARSE_POINT"):
        bootstrap.create_complete_loop_project(source, target)

    assert not target.exists()


def test_standard_archive_is_non_overwriting_and_hash_manifested(tmp_path: Path) -> None:
    archive = _load_script("standard_corpus_archive", ARCHIVE_SCRIPT)
    source = _standard_parse_fixture(tmp_path / "source")
    source_zip = tmp_path / "standard.zip"
    _write(source_zip, b"standard-zip")
    target = tmp_path / "standards"

    manifest = archive.archive_standard_corpus(
        source,
        target,
        source_zip=source_zip,
        expected_source_zip_sha256=hashlib.sha256(b"standard-zip").hexdigest(),
    )

    assert manifest["pdf_count"] == 14
    assert manifest["mineru_success_count"] == 14
    assert manifest["mineru_failure_count"] == 0
    assert manifest["source_zip_sha256"] == hashlib.sha256(b"standard-zip").hexdigest()
    assert manifest["file_count"] == len(manifest["files"])
    assert all(row["sha256"] for row in manifest["files"])
    assert (target / "standard_corpus_manifest.json").is_file()
    before = _snapshot(target)

    with pytest.raises(archive.StandardArchiveError, match="TARGET_EXISTS"):
        archive.archive_standard_corpus(
            source,
            target,
            source_zip=source_zip,
            expected_source_zip_sha256=hashlib.sha256(b"standard-zip").hexdigest(),
        )

    assert _snapshot(target) == before


def test_standard_archive_rejects_source_zip_hash_mismatch(tmp_path: Path) -> None:
    archive = _load_script("standard_corpus_archive_hash", ARCHIVE_SCRIPT)
    source = _standard_parse_fixture(tmp_path / "source")
    source_zip = tmp_path / "standard.zip"
    _write(source_zip, b"changed")
    target = tmp_path / "standards"

    with pytest.raises(archive.StandardArchiveError, match="SOURCE_ZIP_HASH_MISMATCH"):
        archive.archive_standard_corpus(
            source,
            target,
            source_zip=source_zip,
            expected_source_zip_sha256=STANDARD_ZIP_SHA256,
        )

    assert not target.exists()
