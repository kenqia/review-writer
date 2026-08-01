from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from review_writer.project.dual_parse_bootstrap import (
    bind_generic_parse_outputs,
    bootstrap_dual_parse_project,
)
from review_writer.project.input_provenance import (
    InputProvenanceError,
    import_three_paper_inputs,
    input_provenance_state,
    project_input_provenance_state,
    preflight_three_paper_inputs,
)
from review_writer.project.parse_quality import (
    apply_parse_quality_decision,
    parse_quality_state,
)
from review_writer.project.source_truth import canonical_digest
from test_chemical_paper_import import ACTOR, write_chemical_zip
from test_dual_parse_bootstrap import generic_output, source_request


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _three_paper_project(tmp_path: Path) -> Path:
    request = source_request(tmp_path)
    project = bootstrap_dual_parse_project(tmp_path / "review-projects", request)
    bind_generic_parse_outputs(project, generic_output(tmp_path / "generic", request))
    for source in request["sources"]:
        state = parse_quality_state(project, source["study_id"])
        for row in state["objects"]:
            if row["review_state"] == "not_required":
                continue
            state = apply_parse_quality_decision(
                project,
                source["study_id"],
                {
                    "object_id": row["object_id"],
                    "object_digest": row["object_digest"],
                    "gate_digest": state["gate_digest"],
                    "action": "pdf_locator_only",
                    "note": "Fixture gate checked against the bound PDF.",
                    "pdf_resolution": {
                        "pages": [1],
                        "source_scope": "Fixture source is readable on the bound PDF page.",
                        "limitations": "Parsed content remains excluded from scientific use.",
                    },
                },
            )
    return project


def _input_manifest(project: Path, tmp_path: Path) -> dict[str, object]:
    receipt = json.loads(
        (project / "00_sources/acquisition_final_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    studies = []
    for index, row in enumerate(receipt["studies"]):
        si_path = tmp_path / "si" / f"si-{index}.pdf"
        si_path.parent.mkdir(parents=True, exist_ok=True)
        si_path.write_bytes(f"%PDF-1.7\nsi-{index}\n%%EOF\n".encode())
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
        main = row["main_pdf"]
        studies.append(
            {
                "study_id": row["study_id"],
                "source_id": row["source_id"],
                "main_pdf": {
                    "sha256": main["sha256"],
                    "page_count": 1,
                },
                "si": {
                    "input_path": str(si_path),
                    "sha256": _sha256(si_path),
                    "page_count": 1,
                },
                "chemical_zip": {
                    "input_path": str(zip_path),
                    "sha256": _sha256(zip_path),
                    "page_count": 1,
                },
            }
        )
    return {
        "schema_version": "input-provenance-manifest.v1",
        "project_id": project.name,
        "studies": studies,
    }


def _snapshot(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }


def _remove_study(manifest: dict[str, object]) -> None:
    manifest["studies"].pop()


def _duplicate_source_id(manifest: dict[str, object]) -> None:
    manifest["studies"][1]["source_id"] = "source-0"


def _wrong_zip_hash(manifest: dict[str, object]) -> None:
    manifest["studies"][0]["chemical_zip"]["sha256"] = "0" * 64


def _tamper_registry_cross_study(project: Path) -> None:
    path = project / "00_sources/si_resource_registry.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["resources"][0]["source_id"], value["resources"][1]["source_id"] = (
        value["resources"][1]["source_id"],
        value["resources"][0]["source_id"],
    )
    body = {key: item for key, item in value.items() if key != "registry_digest"}
    value["registry_digest"] = canonical_digest(body)
    path.write_text(json.dumps(value), encoding="utf-8")


def _tamper_coverage_cross_study(project: Path) -> None:
    path = project / "00_sources/source_coverage.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["studies"][0], value["studies"][1] = value["studies"][1], value["studies"][0]
    path.write_text(json.dumps(value), encoding="utf-8")


def test_three_paper_preflight_binds_all_four_input_lanes(tmp_path: Path) -> None:
    project = _three_paper_project(tmp_path)
    manifest = _input_manifest(project, tmp_path)

    result = preflight_three_paper_inputs(project, manifest)

    assert result["status"] == "ready_for_import"
    assert result["counts"] == {
        "main_pdf": 3,
        "si": 3,
        "chemical_zip": 3,
        "generic_parse": 3,
    }
    assert len(result["bindings"]) == 3
    assert all(
        row["source_id"] == row["study_id"].replace("study", "source")
        and row["main_pdf"]["page_count"] == 1
        and row["si"]["page_count"] == 1
        and row["chemical_zip"]["page_count"] == 1
        for row in result["bindings"]
    )

    imported = import_three_paper_inputs(project, manifest, ACTOR)
    assert imported["status"] == "imported"
    assert imported["counts"] == result["counts"]
    state = input_provenance_state(project, manifest)
    assert state["status"] == "current"
    assert state["counts"] == result["counts"]
    registry = json.loads(
        (project / "00_sources/si_resource_registry.json").read_text(encoding="utf-8")
    )
    coverage = json.loads(
        (project / "00_sources/source_coverage.json").read_text(encoding="utf-8")
    )
    assert registry["integration_status"] == "CURRENT"
    assert len(registry["resources"]) == 3
    assert all(row["available_roles"] == ["MAIN", "SI"] for row in coverage["studies"])
    assert all(row["study_status"] == "READY" for row in coverage["studies"])
    staging = project / ".dual-parse-staging/chemical-paper"
    assert len(list(staging.glob("*.consumed.json"))) == 3
    assert not list(staging.glob("*.zip"))
    redacted = project_input_provenance_state(project)
    assert redacted["status"] == "current"
    assert redacted["counts"] == result["counts"]
    encoded = json.dumps(redacted)
    assert all(secret not in encoded for secret in ("input_path", "sha256", "digest", "raw"))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
            (_remove_study, "INPUT_MANIFEST_INVALID"),
        (_duplicate_source_id, "INPUT_BINDING_AMBIGUOUS"),
        (_wrong_zip_hash, "CHEMICAL_ZIP_HASH_MISMATCH"),
    ],
)
def test_three_paper_preflight_failures_are_zero_write(
    tmp_path: Path, mutation, code: str
) -> None:
    project = _three_paper_project(tmp_path)
    manifest = _input_manifest(project, tmp_path)
    before = _snapshot(project)
    mutation(manifest)

    with pytest.raises(InputProvenanceError, match=code):
        preflight_three_paper_inputs(project, manifest)

    assert _snapshot(project) == before


def test_stale_si_is_rejected_without_project_write(tmp_path: Path) -> None:
    project = _three_paper_project(tmp_path)
    manifest = _input_manifest(project, tmp_path)
    import_three_paper_inputs(project, manifest, ACTOR)
    before = _snapshot(project)
    si_path = Path(manifest["studies"][0]["si"]["input_path"])
    si_path.write_bytes(si_path.read_bytes() + b"stale")

    with pytest.raises(InputProvenanceError, match="SI_INPUT_STALE"):
        input_provenance_state(project, manifest)

    assert _snapshot(project) == before


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (_tamper_registry_cross_study, "SI_REGISTRY_INVALID"),
        (_tamper_coverage_cross_study, "SOURCE_COVERAGE_INVALID"),
    ],
)
def test_published_cross_study_tamper_is_rejected_by_redacted_state_helper(
    tmp_path: Path,
    mutation,
    code: str,
) -> None:
    project = _three_paper_project(tmp_path)
    manifest = _input_manifest(project, tmp_path)
    import_three_paper_inputs(project, manifest, ACTOR)
    mutation(project)

    with pytest.raises(InputProvenanceError, match=code):
        project_input_provenance_state(project)
