from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from review_writer.project.dual_parse_bootstrap import (
    DualParseBootstrapError,
    bind_generic_parse_outputs,
    bootstrap_dual_parse_project,
)


def _pdf(path: Path, index: int) -> dict[str, object]:
    payload = f"%PDF-1.7\nsynthetic-{index}\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "study_id": f"study-{index}",
        "source_id": f"source-{index}",
        "doi": f"10.1000/dual-{index}",
        "title": f"Dual parse study {index}",
        "tier": "core",
        "document_role": "MAIN",
        "pdf_input_path": str(path),
        "expected_pdf_sha256": hashlib.sha256(payload).hexdigest(),
    }


def source_request(tmp_path: Path, *, project_id: str = "dual-fresh", count: int = 3) -> dict[str, object]:
    return {
        "schema_version": "dual-parse-bootstrap-request.v1",
        "project_id": project_id,
        "brief": {"topic": "Synthetic dual parse review"},
        "sources": [_pdf(tmp_path / "inputs" / f"paper-{index}.pdf", index) for index in range(count)],
    }


def snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unsupported: {exc}")


def generic_output(root: Path, request: dict[str, object]) -> Path:
    completed = []
    for index, source in enumerate(request["sources"]):
        slug = f"generic-{index}"
        markdown = f"# {source['title']}\n\nBody {index}.\n"
        (root / "markdown").mkdir(parents=True, exist_ok=True)
        (root / "markdown" / f"{slug}.md").write_text(markdown, encoding="utf-8")
        extracted = root / "extracted" / slug
        (extracted / "images").mkdir(parents=True, exist_ok=True)
        (extracted / "full.md").write_text(markdown, encoding="utf-8")
        (extracted / "images" / "figure.png").write_bytes(b"png")
        (extracted / "parse_content_list.json").write_text(json.dumps([
            {"type": "text", "page_idx": 0, "bbox": [1, 2, 3, 4], "text": f"Body {index}."},
        ]), encoding="utf-8")
        (extracted / "parse_content_list_v2.json").write_text(json.dumps([[
            {"type": "text", "bbox": [1, 2, 3, 4], "content": {"content": f"Body {index}."}},
        ]]), encoding="utf-8")
        (extracted / "layout.json").write_text(json.dumps({"pages": [{"page_idx": 0}]}), encoding="utf-8")
        (root / "raw_zips").mkdir(parents=True, exist_ok=True)
        (root / "raw_zips" / f"{slug}.zip").write_bytes(b"zip")
        completed.append({
            "pdf_name": Path(source["pdf_input_path"]).name,
            "relative_pdf_path": f"{source['source_id']}.pdf",
            "slug": slug,
            "data_id": f"{index:03d}-{slug}",
            "state": "done",
        })
    (root / "manifest.json").write_text(json.dumps({
        "tool": "mineru-precise-parse-review-writer",
        "settings": {
            "language": "en", "model_version": "vlm", "enable_formula": True,
            "enable_table": True, "ocr": False,
        },
        "queued": 3, "completed_count": 3, "failed_count": 0,
        "completed": completed, "failed": [], "batches": [{"jobs": completed}],
    }), encoding="utf-8")
    return root


def test_bootstrap_creates_only_brief_discovery_and_bound_pdfs(tmp_path: Path) -> None:
    request = source_request(tmp_path)

    project = bootstrap_dual_parse_project(tmp_path / "review-projects", request)

    assert len(list((project / "00_sources/papers").glob("*.pdf"))) == 3
    assert (project / "00_brief/review_state.json").is_file()
    assert (project / "00_discovery/candidate_pool.json").is_file()
    assert (project / "00_sources/acquisition_final_receipt.json").is_file()
    assert (project / "00_sources/source_identity_audit.json").is_file()
    assert not (project / "01_evidence").exists()
    assert not (project / "02_synthesis").exists()
    assert not (project / "04_manuscript").exists()
    assert "pdf_input_path" not in "".join(
        path.read_text(encoding="utf-8")
        for path in project.rglob("*.json")
    )


def test_bootstrap_requires_si_for_core_studies(tmp_path: Path) -> None:
    project = bootstrap_dual_parse_project(
        tmp_path / "review-projects", source_request(tmp_path)
    )

    coverage = json.loads(
        (project / "00_sources/source_coverage.json").read_text(encoding="utf-8")
    )

    assert all(row["si_policy"] == "REQUIRED" for row in coverage["studies"])
    assert all(row["study_status"] == "PARTIAL" for row in coverage["studies"])
    assert all(
        row["blocking_reasons"] == ["SI_REQUIRED_FOR_DECLARED_CLAIMS"]
        for row in coverage["studies"]
    )
    assert all(row["blocked_claim_ids"] == [] for row in coverage["studies"])


def test_hash_mismatch_is_zero_write(tmp_path: Path) -> None:
    request = source_request(tmp_path)
    request["sources"][0]["expected_pdf_sha256"] = "0" * 64
    review_root = tmp_path / "review-projects"
    before = snapshot(review_root)

    with pytest.raises(DualParseBootstrapError, match="SOURCE_PDF_HASH_MISMATCH"):
        bootstrap_dual_parse_project(review_root, request)

    assert snapshot(review_root) == before


@pytest.mark.parametrize("count", [2, 4])
def test_bootstrap_requires_exactly_three_sources(tmp_path: Path, count: int) -> None:
    with pytest.raises(DualParseBootstrapError, match="BOOTSTRAP_REQUEST_INVALID"):
        bootstrap_dual_parse_project(tmp_path / "review-projects", source_request(tmp_path, count=count))


@pytest.mark.parametrize("duplicate", ["study_id", "source_id"])
def test_bootstrap_rejects_duplicate_id_without_writing(tmp_path: Path, duplicate: str) -> None:
    request = source_request(tmp_path)
    request["sources"][1][duplicate] = request["sources"][0][duplicate]

    with pytest.raises(DualParseBootstrapError, match="DUPLICATE"):
        bootstrap_dual_parse_project(tmp_path / "review-projects", request)

    assert snapshot(tmp_path / "review-projects") == {}


def test_bootstrap_rejects_unknown_fields_non_main_and_existing_target(tmp_path: Path) -> None:
    request = source_request(tmp_path)
    request["unexpected"] = True
    with pytest.raises(DualParseBootstrapError, match="BOOTSTRAP_REQUEST_INVALID"):
        bootstrap_dual_parse_project(tmp_path / "review-projects", request)

    request = source_request(tmp_path)
    request["sources"][0]["document_role"] = "SI"
    with pytest.raises(DualParseBootstrapError, match="BOOTSTRAP_REQUEST_INVALID"):
        bootstrap_dual_parse_project(tmp_path / "review-projects", request)

    request = source_request(tmp_path)
    target = tmp_path / "review-projects" / "dual-fresh"
    target.mkdir(parents=True)
    (target / "keep.json").write_text(json.dumps({"keep": True}), encoding="utf-8")
    before = snapshot(tmp_path / "review-projects")
    with pytest.raises(DualParseBootstrapError, match="TARGET_EXISTS"):
        bootstrap_dual_parse_project(tmp_path / "review-projects", request)
    assert snapshot(tmp_path / "review-projects") == before


def test_bootstrap_rejects_symlink_non_pdf_and_duplicate_bytes(tmp_path: Path) -> None:
    request = source_request(tmp_path)
    real = Path(request["sources"][0]["pdf_input_path"])
    linked = tmp_path / "inputs" / "linked.pdf"
    symlink_or_skip(linked, real)
    request["sources"][0]["pdf_input_path"] = str(linked)
    review_root = tmp_path / "review-projects"
    with pytest.raises(DualParseBootstrapError, match="SOURCE_PDF_INVALID"):
        bootstrap_dual_parse_project(review_root, request)
    assert snapshot(review_root) == {}
    assert not review_root.exists()

    request = source_request(tmp_path)
    invalid = Path(request["sources"][0]["pdf_input_path"])
    invalid.write_bytes(b"not a PDF")
    request["sources"][0]["expected_pdf_sha256"] = hashlib.sha256(b"not a PDF").hexdigest()
    with pytest.raises(DualParseBootstrapError, match="SOURCE_PDF_INVALID"):
        bootstrap_dual_parse_project(tmp_path / "review-projects", request)

    request = source_request(tmp_path)
    first = Path(request["sources"][0]["pdf_input_path"])
    second = Path(request["sources"][1]["pdf_input_path"])
    second.write_bytes(first.read_bytes())
    request["sources"][1]["expected_pdf_sha256"] = request["sources"][0]["expected_pdf_sha256"]
    with pytest.raises(DualParseBootstrapError, match="DUPLICATE_SOURCE_PDF"):
        bootstrap_dual_parse_project(tmp_path / "review-projects", request)


def test_bootstrap_rejects_symlinked_parent_component_zero_write(tmp_path: Path) -> None:
    request = source_request(tmp_path)
    real = Path(request["sources"][0]["pdf_input_path"])
    linked_parent = tmp_path / "linked-inputs"
    symlink_or_skip(linked_parent, real.parent, target_is_directory=True)
    request["sources"][0]["pdf_input_path"] = str(linked_parent / real.name)
    review_root = tmp_path / "review-projects"

    with pytest.raises(DualParseBootstrapError, match="SOURCE_PDF_INVALID"):
        bootstrap_dual_parse_project(review_root, request)

    assert snapshot(review_root) == {}
    assert not review_root.exists()


def test_generic_binding_builds_all_current_source_truth_and_parse_gates(tmp_path: Path) -> None:
    request = source_request(tmp_path)
    project = bootstrap_dual_parse_project(tmp_path / "review-projects", request)
    output = generic_output(tmp_path / "generic-output", request)

    result = bind_generic_parse_outputs(project, output)

    assert result == {
        "status": "bound",
        "completed_count": 3,
        "failed_count": 0,
        "source_truth_count": 3,
        "parse_quality_count": 3,
    }
    assert len(list((project / "01_evidence/source_truth").glob("*/bundle.json"))) == 3
    assert len(list((project / "01_evidence/source_truth").glob("*/parse_quality.json"))) == 3
    assert (project / "01_evidence/text_layers/text_layers.manifest.json").is_file()


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("completed_count", 2, "GENERIC_PARSE_INCOMPLETE"),
        ("failed_count", 1, "GENERIC_PARSE_INCOMPLETE"),
    ],
)
def test_generic_binding_failure_is_zero_write(
    tmp_path: Path, field: str, value: object, code: str,
) -> None:
    request = source_request(tmp_path)
    project = bootstrap_dual_parse_project(tmp_path / "review-projects", request)
    output = generic_output(tmp_path / "generic-output", request)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = snapshot(project)

    with pytest.raises(DualParseBootstrapError, match=code):
        bind_generic_parse_outputs(project, output)

    assert snapshot(project) == before
