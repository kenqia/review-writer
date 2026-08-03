from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from review_writer.project.dual_parse_bootstrap import (
    DualParseBootstrapError,
    bind_generic_parse_outputs,
    bootstrap_corpus_project,
)
from review_writer.project.input_provenance import (
    InputProvenanceError,
    import_corpus_inputs,
    input_provenance_state,
    preflight_corpus_inputs,
)
from test_chemical_paper_import import ACTOR, write_chemical_zip


def _request(tmp_path: Path, count: int) -> dict[str, object]:
    sources: list[dict[str, object]] = []
    for index in range(count):
        payload = f"%PDF-1.7\nsynthetic-study-{index}\n%%EOF\n".encode()
        path = tmp_path / f"study-{index}.pdf"
        path.write_bytes(payload)
        si_payload = f"%PDF-1.7\nsynthetic-si-{index}\n%%EOF\n".encode()
        si_path = tmp_path / f"study-{index}-si.pdf"
        si_path.write_bytes(si_payload)
        sources.append(
            {
                "study_id": f"study-{index}",
                "source_id": f"source-{index}",
                "doi": f"10.0000/example-{index}",
                "title": f"Synthetic study {index}",
                "tier": "core" if index < max(1, count // 2) else "background",
                "document_role": "MAIN",
                "pdf_input_path": str(path),
                "expected_pdf_sha256": hashlib.sha256(payload).hexdigest(),
                "si_pdf_input_path": str(si_path),
                "expected_si_pdf_sha256": hashlib.sha256(si_payload).hexdigest(),
            }
        )
    return {
        "schema_version": "corpus-manifest.v1",
        "project_id": f"variable-{count}",
        "brief": {"topic": "synthetic boundary test"},
        "sources": sources,
    }


def _generic_output(root: Path, request: dict[str, object]) -> Path:
    completed: list[dict[str, object]] = []
    settings = {
        "language": "en",
        "model_version": "vlm",
        "enable_formula": True,
        "enable_table": True,
        "ocr": False,
    }
    for index, source in enumerate(request["sources"]):
        for role, relative, hash_key in (
            (
                "MAIN",
                f"papers/{source['source_id']}.pdf",
                "expected_pdf_sha256",
            ),
            (
                "SI",
                f"supplements/imported/{source['source_id']}.pdf",
                "expected_si_pdf_sha256",
            ),
        ):
            slug = f"study-{index}-{role.lower()}"
            markdown = f"# Study {index} {role}\n\nBody.\n\n# References\n"
            extracted = root / "extracted" / slug
            (extracted / "images").mkdir(parents=True, exist_ok=True)
            (root / "markdown").mkdir(parents=True, exist_ok=True)
            (root / "markdown" / f"{slug}.md").write_text(markdown, encoding="utf-8")
            (extracted / "full.md").write_text(markdown, encoding="utf-8")
            (extracted / "layout.json").write_text(
                json.dumps({"pages": [{"page_idx": 0}]}), encoding="utf-8"
            )
            (extracted / "parse_content_list.json").write_text(
                json.dumps([{"type": "text", "page_idx": 0, "bbox": [1, 2, 3, 4], "text": "Body."}]),
                encoding="utf-8",
            )
            (extracted / "parse_content_list_v2.json").write_text(
                json.dumps([[{"type": "text", "bbox": [1, 2, 3, 4], "content": {"content": "Body."}}]]),
                encoding="utf-8",
            )
            (root / "raw_zips").mkdir(parents=True, exist_ok=True)
            (root / "raw_zips" / f"{slug}.zip").write_bytes(b"zip")
            completed.append(
                {
                    "pdf_name": Path(relative).name,
                    "relative_pdf_path": relative,
                    "source_pdf_sha256": source[hash_key],
                    "slug": slug,
                    "data_id": f"{index:03d}-{role.lower()}",
                    "study_id": source["study_id"],
                    "source_id": source["source_id"] if role == "MAIN" else f"{source['source_id']}__SI",
                    "document_role": role,
                    "state": "done",
                }
            )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "mineru-parse-manifest.v1",
                "settings": settings,
                "queued": len(completed),
                "completed_count": len(completed),
                "failed_count": 0,
                "completed": completed,
                "failed": [],
            }
        ),
        encoding="utf-8",
    )
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _input_manifest(tmp_path: Path, request: dict[str, object], project: Path) -> dict[str, object]:
    studies: list[dict[str, object]] = []
    for index, source in enumerate(request["sources"]):
        chemical_path = tmp_path / "chemical" / f"chemical-{index}.zip"
        chemical_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path = write_chemical_zip(
            chemical_path,
            pages=1,
            molecules=[
                {
                    "mol_id": f"mol-{index}",
                    "page_idx": 0,
                    "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                    "smiles_expanded": "CO",
                    "smiles_unexpanded": "CO",
                    "mol_idt": f"compound {index}",
                    "mol_block": "fixture\n  review-writer\n\n  1  0  0  0  0  0            999 V2000\n    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\nM  END\n",
                }
            ],
        )
        si_path = Path(source["si_pdf_input_path"])
        main_path = project / "00_sources" / "papers" / f"{source['source_id']}.pdf"
        studies.append(
            {
                "study_id": source["study_id"],
                "source_id": source["source_id"],
                "main_pdf": {
                    "sha256": source["expected_pdf_sha256"],
                    "page_count": 1,
                },
                "si": {
                    "input_path": str(si_path),
                    "sha256": source["expected_si_pdf_sha256"],
                    "page_count": 1,
                },
                "chemical_zip": {
                    "input_path": str(zip_path),
                    "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
                    "page_count": 1,
                },
            }
        )
        assert main_path.is_file()
    return {
        "schema_version": "input-provenance-manifest.v1",
        "project_id": project.name,
        "studies": studies,
    }


@pytest.mark.parametrize("count", [20, 40])
def test_authoritative_variable_n_accepts_only_supported_boundaries(
    tmp_path: Path, count: int
) -> None:
    project = bootstrap_corpus_project(tmp_path / "projects", _request(tmp_path, count))
    receipt = json.loads(
        (project / "00_sources/acquisition_final_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["corpus_kind"] == "authoritative_variable_n"
    assert receipt["variable_n"] is True
    assert receipt["study_count"] == count
    assert len(receipt["studies"]) == count
    assert all("si_pdf" in row for row in receipt["studies"])
    assert all(
        row["si_pdf"]["sha256"]
        == hashlib.sha256(
            (project / "00_sources" / row["si_pdf"]["path"]).read_bytes()
        ).hexdigest()
        for row in receipt["studies"]
    )


@pytest.mark.parametrize("count", [20, 40])
def test_variable_n_generic_binding_requires_and_publishes_main_and_si(
    tmp_path: Path, count: int
) -> None:
    request = _request(tmp_path, count)
    project = bootstrap_corpus_project(tmp_path / "projects", request)

    result = bind_generic_parse_outputs(project, _generic_output(tmp_path / "generic", request))

    assert result == {
        "status": "bound",
        "completed_count": count * 2,
        "failed_count": 0,
        "source_truth_count": count,
        "parse_quality_count": count,
    }
    text_layers = json.loads(
        (project / "01_evidence/text_layers/text_layers.manifest.json").read_text(encoding="utf-8")
    )
    assert len(text_layers["sources"]) == count * 2
    assert len({row["source_id"] for row in text_layers["sources"]}) == count * 2
    for source in request["sources"]:
        bundle = json.loads(
            (project / "01_evidence/source_truth" / source["study_id"] / "bundle.json").read_text(
                encoding="utf-8"
            )
        )
        assert {row["document_role"] for row in bundle["sources"]} == {"MAIN", "SI"}


@pytest.mark.parametrize("mutation,code", [("missing_si", "BOOTSTRAP_REQUEST_INVALID"), ("wrong_hash", "SOURCE_SI_HASH_MISMATCH"), ("reuse_si", "DUPLICATE_SOURCE_PDF")])
def test_variable_n_si_input_failures_publish_nothing(
    tmp_path: Path, mutation: str, code: str
) -> None:
    request = _request(tmp_path, 20)
    if mutation == "missing_si":
        request["sources"][0].pop("si_pdf_input_path")
    elif mutation == "wrong_hash":
        request["sources"][0]["expected_si_pdf_sha256"] = "0" * 64
    else:
        request["sources"][1]["si_pdf_input_path"] = request["sources"][0]["si_pdf_input_path"]
        request["sources"][1]["expected_si_pdf_sha256"] = request["sources"][0]["expected_si_pdf_sha256"]
    review_root = tmp_path / "projects"

    with pytest.raises(DualParseBootstrapError, match=code):
        bootstrap_corpus_project(review_root, request)

    assert not (review_root / request["project_id"]).exists()


def test_variable_n_generic_si_cross_study_reuse_is_zero_write(tmp_path: Path) -> None:
    request = _request(tmp_path, 20)
    project = bootstrap_corpus_project(tmp_path / "projects", request)
    output = _generic_output(tmp_path / "generic", request)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    si_rows = [row for row in manifest["completed"] if row["document_role"] == "SI"]
    si_rows[1]["relative_pdf_path"] = si_rows[0]["relative_pdf_path"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _snapshot(project)

    with pytest.raises(DualParseBootstrapError, match="GENERIC_BINDING_AMBIGUOUS"):
        bind_generic_parse_outputs(project, output)

    assert _snapshot(project) == before


def test_variable_n_input_provenance_binds_si_and_dynamic_counts(tmp_path: Path) -> None:
    request = _request(tmp_path, 20)
    project = bootstrap_corpus_project(tmp_path / "projects", request)
    bind_generic_parse_outputs(project, _generic_output(tmp_path / "generic", request))
    manifest = _input_manifest(tmp_path, request, project)

    preflight = preflight_corpus_inputs(project, manifest)

    assert preflight["status"] == "ready_for_import"
    assert preflight["counts"] == {
        "main_pdf": 20,
        "si": 20,
        "chemical_zip": 20,
        "generic_parse": 20,
        "generic_main": 20,
        "generic_si": 20,
        "chemical_main": 20,
        "chemical_core_si": 10,
    }
    imported = import_corpus_inputs(project, manifest, ACTOR)
    assert imported["status"] == "imported"
    assert imported["counts"] == preflight["counts"]
    assert input_provenance_state(project, manifest)["status"] == "current"


@pytest.mark.parametrize("mutation,code", [("missing", "INPUT_MANIFEST_INVALID"), ("wrong_hash", "SI_HASH_MISMATCH"), ("reuse", "INPUT_BINDING_AMBIGUOUS")])
def test_variable_n_input_provenance_si_failures_are_zero_write(
    tmp_path: Path, mutation: str, code: str
) -> None:
    request = _request(tmp_path, 20)
    project = bootstrap_corpus_project(tmp_path / "projects", request)
    bind_generic_parse_outputs(project, _generic_output(tmp_path / "generic", request))
    manifest = _input_manifest(tmp_path, request, project)
    before = _snapshot(project)
    if mutation == "missing":
        manifest["studies"][0].pop("si")
    elif mutation == "wrong_hash":
        manifest["studies"][0]["si"]["sha256"] = "0" * 64
    else:
        manifest["studies"][1]["si"] = dict(manifest["studies"][0]["si"])

    with pytest.raises(InputProvenanceError, match=code):
        preflight_corpus_inputs(project, manifest)

    assert _snapshot(project) == before


@pytest.mark.parametrize("count", [19, 41])
def test_out_of_range_variable_n_rejects_before_target_publication(
    tmp_path: Path, count: int
) -> None:
    review_root = tmp_path / "projects"
    request = _request(tmp_path, count)
    with pytest.raises(DualParseBootstrapError, match="CORPUS_STUDY_COUNT_INVALID"):
        bootstrap_corpus_project(review_root, request)
    assert not (review_root / request["project_id"]).exists()
