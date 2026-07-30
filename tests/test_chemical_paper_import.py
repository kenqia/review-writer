from __future__ import annotations

import copy
import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from review_writer.project.source_truth import canonical_digest


PDF_SHA = "a" * 64
ACTOR = {"actor_type": "simulated_researcher_agent", "actor_label": "fixture-researcher"}


def _file(path: str, sha256: str = "b" * 64) -> dict[str, object]:
    return {"path": path, "sha256": sha256, "size_bytes": 1}


def source_truth_project(root: Path, *, study_id: str = "study-1", pages: int = 2) -> Path:
    project = root / "project"
    target = project / "01_evidence/source_truth" / study_id
    target.mkdir(parents=True)
    receipt = project / "00_sources/acquisition_final_receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "acquisition-final-receipt.v1",
                "studies": [{"study_id": study_id}],
            }
        ),
        encoding="utf-8",
    )
    source = {
        "source_id": "source-main",
        "document_role": "MAIN",
        "source_type": "primary_study",
        "mineru_slug": "study-1-main",
        "pdf": _file("00_sources/main.pdf", PDF_SHA),
        "canonical_markdown": _file("01_evidence/mineru/markdown/main.md"),
        "content_list": _file("01_evidence/parses/extracted/main/content_list.json"),
        "content_list_v2": _file("01_evidence/parses/extracted/main/content_list_v2.json"),
        "layout": _file("01_evidence/parses/extracted/main/layout.json"),
        "reading_layer": _file("01_evidence/text_layers/main.reading.json"),
        "layout_layer": _file("01_evidence/text_layers/main.layout.json"),
        "page_count": pages,
        "images": {"count": 0, "digest": "c" * 64},
    }
    body = {
        "schema_version": "source-truth-bundle.v1",
        "project_id": project.name,
        "study_id": study_id,
        "study_identity": {"doi": "10.1000/test", "title": "Fixture study"},
        "sources": [source],
        "warnings": [],
    }
    bundle = {**body, "bundle_digest": canonical_digest(body)}
    (target / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    return project


def v2000(symbols: tuple[str, ...] = ("C", "O")) -> str:
    atoms = "".join(
        f"    0.0000    0.0000    0.0000 {symbol:<3} 0  0  0  0  0  0  0  0  0  0  0  0\n"
        for symbol in symbols
    )
    return (
        "fixture\n  review-writer\n\n"
        f"{len(symbols):>3}  0  0  0  0  0            999 V2000\n"
        f"{atoms}M  END\n"
    )


def v2000_empty() -> str:
    return "fixture\n  review-writer\n\n  0  0  0  0  0  0            999 V2000\nM  END\n"


def write_chemical_zip(
    path: Path,
    *,
    pages: int = 2,
    molecules: list[dict[str, object]] | None = None,
    generic: bool = False,
    extra_entries: list[tuple[zipfile.ZipInfo | str, bytes]] | None = None,
) -> Path:
    if molecules is None:
        molecules = [
            {
                "mol_id": "mol-1",
                "page_idx": 0,
                "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                "smiles_expanded": "CO",
                "smiles_unexpanded": "CO",
                "mol_idt": "methanol-candidate",
                "mol_block": v2000(),
            },
            {
                "mol_id": "mol-2",
                "page_idx": 1,
                "bbox_normalized": [0.2, 0.3, 0.5, 0.6],
                "smiles_expanded": "",
                "smiles_unexpanded": "",
                "mol_idt": "",
                "mol_block": v2000(("N",)),
            },
        ]
    main = {
        "_backend": "pipeline",
        "_version_name": "3.4.4",
        "pdf_info": [
            {
                "page_idx": index,
                "page_size": [612, 792],
                "preproc_blocks": [],
                "discarded_blocks": [],
                "para_blocks": [],
            }
            for index in range(pages)
        ],
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("main.json", json.dumps(main).encode())
        archive.writestr("paper.md", b"# Fixture\n")
        if generic:
            archive.writestr("content.json", b"[]")
        else:
            archive.writestr("molecule-info.json", json.dumps({"molecules": molecules}).encode())
        for name, payload in extra_entries or []:
            archive.writestr(name, payload)
    return path


def snapshot(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }


def test_import_binds_pdf_and_preserves_explicit_unknowns_with_safe_projection(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import (
        chemical_paper_projection,
        import_chemical_paper,
        load_chemical_paper_state,
    )

    project = source_truth_project(tmp_path)
    archive = write_chemical_zip(tmp_path / "chemical.zip")
    result = import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)

    assert result["status"] == "imported"
    state = load_chemical_paper_state(project, "study-1")
    assert state["schema_version"] == "chemical-paper-state.v1"
    assert state["current_import_digest"]
    assert (
        project / "01_evidence/chemical_paper/study-1/state.json"
    ).is_file()
    assert state["source_pdf_sha256"] == PDF_SHA
    assert state["source_truth_bundle_digest"]
    imported_event = state["imports"][state["current_import_digest"]]
    assert imported_event["backend"] == "pipeline"
    assert imported_event["version"] == "3.4.4"
    assert imported_event["reaction_data_status"] == "unavailable_not_provided"
    assert len(imported_event["entry_inventory"]) == 3
    assert state["molecules"][1]["fields"]["mol_idt"]["status"] == "unresolved"
    assert state["molecules"][1]["fields"]["smiles_expanded"]["value"] is None
    assert state["molecules"][1]["element_candidate_counts"] == {"N": 1}
    assert state["molecules"][1]["element_review_state"] == "not_reviewed"

    projection = chemical_paper_projection(project)
    encoded = json.dumps(projection)
    assert projection["schema_version"] == "chemical-paper-projection.v1"
    assert projection["studies"][0]["reaction_data_status"] == "unavailable_not_provided"
    molecule_projection = projection["studies"][0]["molecules"][1]
    assert molecule_projection["molecule_index"] == 1
    assert molecule_projection["pdf_page_url"].endswith("/pdf-page?page=2")
    assert molecule_projection["missing_fields"] == [
        "mol_idt",
        "smiles_expanded",
        "smiles_unexpanded",
    ]
    assert "molecule_id" not in molecule_projection
    assert "mol_block" not in molecule_projection
    assert projection["studies"][0]["file_kinds"] == [
        "layout",
        "markdown",
        "molecule_info",
    ]
    for forbidden in (str(archive), PDF_SHA, imported_event["archive_sha256"], "mol_block", "entry_inventory"):
        assert forbidden not in encoded


def test_safe_projection_routes_three_studies_to_their_quoted_bound_sources(
    tmp_path: Path,
) -> None:
    from review_writer.project.chemical_paper import (
        chemical_paper_projection,
        import_chemical_paper,
    )

    project = source_truth_project(tmp_path, study_id="study-a")
    renamed = project.with_name("project#quoted?")
    project.rename(renamed)
    project = renamed
    base_bundle = json.loads(
        (project / "01_evidence/source_truth/study-a/bundle.json").read_text(
            encoding="utf-8"
        )
    )
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"] = [
        {"study_id": study_id} for study_id in ("study-a", "study-b", "study-c")
    ]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    expected: dict[str, str] = {}
    for index, study_id in enumerate(("study-a", "study-b", "study-c"), start=1):
        body = {
            key: copy.deepcopy(value)
            for key, value in base_bundle.items()
            if key != "bundle_digest"
        }
        body["project_id"] = project.name
        body["study_id"] = study_id
        body["study_identity"] = {
            "doi": f"10.1000/test-{index}",
            "title": f"Fixture study {index}",
        }
        body["sources"][0]["source_id"] = f"source#{index}?main"
        body["sources"][0]["mineru_slug"] = f"study-{index}-main"
        bundle_path = project / f"01_evidence/source_truth/{study_id}/bundle.json"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(
            json.dumps({**body, "bundle_digest": canonical_digest(body)}),
            encoding="utf-8",
        )
        import_chemical_paper(
            project,
            study_id,
            PDF_SHA,
            write_chemical_zip(tmp_path / f"chemical-{index}.zip"),
            ACTOR,
        )
        expected[study_id] = (
            f"/api/project/project%23quoted%3F/source/"
            f"source%23{index}%3Fmain/pdf-page?page=2"
        )

    projection = chemical_paper_projection(project)
    observed = {
        study["study_id"]: study["molecules"][1]["pdf_page_url"]
        for study in projection["studies"]
    }

    assert observed == expected
    encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    assert "/parse-quality/" not in encoded
    for forbidden in (
        "source_pdf_sha256",
        "archive_sha256",
        "entry_inventory",
        "mol_block",
        str(project),
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "binding_failure",
    ("wrong", "missing", "ambiguous", "stale", "page_out_of_range"),
)
def test_safe_projection_fails_closed_for_invalid_current_source_binding(
    tmp_path: Path,
    binding_failure: str,
) -> None:
    from review_writer.project.chemical_paper import (
        ChemicalPaperError,
        chemical_paper_projection,
        import_chemical_paper,
    )

    project = source_truth_project(tmp_path)
    import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )
    state_path = project / "01_evidence/chemical_paper/study-1/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    bundle_path = project / "01_evidence/source_truth/study-1/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

    if binding_failure == "wrong":
        state["source_id"] = "wrong-source"
    elif binding_failure in {"missing", "ambiguous"}:
        body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
        if binding_failure == "missing":
            body["sources"][0]["document_role"] = "SI"
        else:
            body["sources"].append(copy.deepcopy(body["sources"][0]))
        bundle = {**body, "bundle_digest": canonical_digest(body)}
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        state["source_truth_bundle_digest"] = bundle["bundle_digest"]
    elif binding_failure == "stale":
        body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
        body["warnings"] = ["source binding changed"]
        bundle_path.write_text(
            json.dumps({**body, "bundle_digest": canonical_digest(body)}),
            encoding="utf-8",
        )
    else:
        state["molecules"][0]["page_index"] = 2

    state["state_digest"] = canonical_digest(
        {key: value for key, value in state.items() if key != "state_digest"}
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(
        ChemicalPaperError,
        match="CHEMICAL_PAPER_SOURCE_TRUTH_STALE",
    ):
        chemical_paper_projection(project)


def test_import_preserves_exported_molecule_order_for_stable_review_indexes(
    tmp_path: Path,
) -> None:
    from review_writer.project.chemical_paper import (
        chemical_paper_projection,
        correct_chemical_paper_field,
        import_chemical_paper,
        load_chemical_paper_state,
    )

    project = source_truth_project(tmp_path)
    exported = [
        {
            "mol_id": "export-first",
            "page_idx": 1,
            "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
            "smiles_expanded": "C",
            "smiles_unexpanded": "C",
            "mol_idt": "export-first",
            "mol_block": v2000(("C",)),
        },
        {
            "mol_id": "export-second",
            "page_idx": 0,
            "bbox_normalized": [0.2, 0.3, 0.4, 0.5],
            "smiles_expanded": "N",
            "smiles_unexpanded": "N",
            "mol_idt": "export-second",
            "mol_block": v2000(("N",)),
        },
    ]
    archive = write_chemical_zip(tmp_path / "export-order.zip", molecules=exported)
    first = import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        archive,
        ACTOR,
    )

    state = load_chemical_paper_state(project, "study-1")
    assert [row["molecule_id"] for row in state["molecules"]] == [
        "export-first",
        "export-second",
    ]
    projected = chemical_paper_projection(project)["studies"][0]["molecules"]
    assert [(row["molecule_index"], row["page"]) for row in projected] == [
        (0, 2),
        (1, 1),
    ]
    corrected = correct_chemical_paper_field(
        project,
        study_id="study-1",
        molecule_index=0,
        field="smiles_expanded",
        value="CC",
        actor=ACTOR,
        reason="Checked exported index against the original PDF.",
        version_token=first["version_token"],
    )
    state = load_chemical_paper_state(project, "study-1")
    assert state["field_corrections"][-1]["molecule_id"] == "export-first"
    assert chemical_paper_projection(project)["studies"][0]["molecules"][0][
        "smiles_expanded"
    ] == "CC"
    state_path = project / "01_evidence/chemical_paper/study-1/state.json"
    before = state_path.read_bytes()
    second = import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)
    assert state_path.read_bytes() == before
    assert second == {
        "status": "unchanged",
        "study_id": "study-1",
        "version_token": corrected["version_token"],
    }


@pytest.mark.parametrize(
    "unsafe_name,error_code",
    [
        ("../escape.txt", "ZIP_PATH_UNSAFE"),
        ("/absolute.txt", "ZIP_PATH_UNSAFE"),
        ("back\\slash.txt", "ZIP_PATH_UNSAFE"),
        ("nested.zip", "ZIP_NESTED_ARCHIVE"),
    ],
)
def test_import_rejects_unsafe_member_without_project_mutation(
    tmp_path: Path, unsafe_name: str, error_code: str
) -> None:
    from review_writer.project.chemical_paper import ChemicalPaperError, import_chemical_paper

    project = source_truth_project(tmp_path)
    archive = write_chemical_zip(
        tmp_path / "unsafe.zip", extra_entries=[(unsafe_name, b"payload")]
    )
    before = snapshot(project)
    with pytest.raises(ChemicalPaperError, match=error_code):
        import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)
    assert snapshot(project) == before


def test_import_rejects_duplicate_symlink_and_generic_archives(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import ChemicalPaperError, import_chemical_paper

    project = source_truth_project(tmp_path)
    duplicate = write_chemical_zip(tmp_path / "duplicate.zip")
    with zipfile.ZipFile(duplicate, "a") as archive:
        archive.writestr("paper.md", b"duplicate")
    symlink = zipfile.ZipInfo("link.json")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    linked = write_chemical_zip(
        tmp_path / "symlink.zip", extra_entries=[(symlink, b"main.json")]
    )
    generic = write_chemical_zip(tmp_path / "generic.zip", generic=True)

    for archive, code in (
        (duplicate, "ZIP_DUPLICATE_ENTRY"),
        (linked, "ZIP_SYMLINK_UNSAFE"),
        (generic, "CHEMICAL_PAPER_CONTRACT_MISSING"),
    ):
        before = snapshot(project)
        with pytest.raises(ChemicalPaperError, match=code):
            import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)
        assert snapshot(project) == before


def test_import_rejects_source_stale_invalid_bbox_and_invalid_molblock_atomically(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import ChemicalPaperError, import_chemical_paper

    project = source_truth_project(tmp_path)
    cases: list[tuple[str, list[dict[str, object]], str, str]] = []
    bad_bbox = [{
        "mol_id": "m", "page_idx": 0, "bbox_normalized": [0.2, 0.2, 1.2, 0.5],
        "smiles_expanded": "", "smiles_unexpanded": "", "mol_idt": "", "mol_block": v2000(),
    }]
    bad_block = copy.deepcopy(bad_bbox)
    bad_block[0]["bbox_normalized"] = [0.1, 0.2, 0.3, 0.5]
    bad_block[0]["mol_block"] = "not a mol block"
    cases.extend([
        ("bbox.zip", bad_bbox, PDF_SHA, "MOLECULE_BBOX_INVALID"),
        ("molblock.zip", bad_block, PDF_SHA, "MOLBLOCK_INVALID"),
        ("stale.zip", [], "d" * 64, "SOURCE_PDF_STALE"),
    ])
    for name, molecules, sha, code in cases:
        archive = write_chemical_zip(tmp_path / name, molecules=molecules or None)
        before = snapshot(project)
        with pytest.raises(ChemicalPaperError, match=code):
            import_chemical_paper(project, "study-1", sha, archive, ACTOR)
        assert snapshot(project) == before


def test_corrections_are_append_only_bound_and_stale_safe(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import (
        ChemicalPaperError,
        append_chemical_field_correction,
        chemical_paper_projection,
        import_chemical_paper,
        load_chemical_paper_state,
    )

    project = source_truth_project(tmp_path)
    archive = write_chemical_zip(tmp_path / "chemical.zip")
    imported = import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)
    state = load_chemical_paper_state(project, "study-1")
    molecule = next(row for row in state["molecules"] if row["molecule_id"] == "mol-2")

    correction = append_chemical_field_correction(
        project,
        "study-1",
        "mol-2",
        "smiles_expanded",
        "N",
        ACTOR,
        reason="Checked against the original PDF.",
        expected_version_token=imported["version_token"],
        bound_import_digest=state["current_import_digest"],
        bound_molecule_digest=molecule["molecule_digest"],
    )
    after = load_chemical_paper_state(project, "study-1")
    assert after["molecules"][1]["fields"]["smiles_unexpanded"]["status"] == "unresolved"
    assert after["field_corrections"][0]["prior_value"] is None
    assert after["field_corrections"][0]["value"] == "N"
    assert correction["version_token"] != imported["version_token"]
    projection = chemical_paper_projection(project)
    assert projection["studies"][0]["molecules"][1]["smiles_expanded"] == "N"

    before = snapshot(project)
    with pytest.raises(ChemicalPaperError, match="STALE_CHEMICAL_PAPER_STATE"):
        append_chemical_field_correction(
            project, "study-1", "mol-2", "mol_idt", "amine", ACTOR,
            reason="Original PDF review.", expected_version_token=imported["version_token"],
            bound_import_digest=state["current_import_digest"],
            bound_molecule_digest=molecule["molecule_digest"],
        )
    assert snapshot(project) == before


def test_element_reviews_are_optional_historical_and_never_infer_smiles(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import (
        append_element_review,
        import_chemical_paper,
        load_chemical_paper_state,
    )

    project = source_truth_project(tmp_path)
    archive = write_chemical_zip(tmp_path / "chemical.zip")
    imported = import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)
    state = load_chemical_paper_state(project, "study-1")
    molecule = next(row for row in state["molecules"] if row["molecule_id"] == "mol-2")
    result = append_element_review(
        project,
        "study-1",
        "mol-2",
        "corrected",
        ACTOR,
        reason="Corrected after optional MolBlock review.",
        expected_version_token=imported["version_token"],
        bound_import_digest=state["current_import_digest"],
        bound_molecule_digest=molecule["molecule_digest"],
        corrected_counts={"N": 1, "H": 3},
    )
    after = load_chemical_paper_state(project, "study-1")
    assert result["status"] == "corrected"
    assert after["element_reviews"][0]["prior_state"] == "not_reviewed"
    assert after["molecules"][1]["fields"]["smiles_expanded"]["value"] is None


def test_identical_import_is_byte_idempotent(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import import_chemical_paper

    project = source_truth_project(tmp_path)
    archive = write_chemical_zip(tmp_path / "chemical.zip")
    first = import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)
    state_path = project / "01_evidence/chemical_paper/study-1/state.json"
    before = state_path.read_bytes()
    second = import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)
    assert state_path.read_bytes() == before
    assert second["status"] == "unchanged"
    assert second["version_token"] == first["version_token"]


def test_dependency_state_blocks_only_evidence_that_uses_unresolved_fields(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import (
        chemical_dependency_state,
        import_chemical_paper,
        load_chemical_paper_state,
    )

    project = source_truth_project(tmp_path)
    import_chemical_paper(project, "study-1", PDF_SHA, write_chemical_zip(tmp_path / "chemical.zip"), ACTOR)
    state = load_chemical_paper_state(project, "study-1")
    unresolved = next(row for row in state["molecules"] if row["molecule_id"] == "mol-2")

    text_only = chemical_dependency_state(project, "evidence-text", [])
    chemical = chemical_dependency_state(project, "evidence-chemical", [{
        "study_id": "study-1",
        "molecule_id": "mol-2",
        "molecule_digest": unresolved["molecule_digest"],
        "chemical_paper_import_digest": state["current_import_digest"],
        "required_fields": ["smiles_expanded"],
    }])
    assert text_only["dependency_status"] == "ready"
    assert chemical["dependency_status"] == "blocked_unresolved"
    assert chemical["gaps"] == ["study-1/mol-2:smiles_expanded:unresolved"]


def test_zip_bomb_file_count_and_encryption_flags_are_fail_closed(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import ChemicalPaperError, _zip_inventory

    many = tmp_path / "many.zip"
    with zipfile.ZipFile(many, "w") as archive:
        for index in range(17):
            archive.writestr(f"{index}.txt", b"x")
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.txt", b"x" * 1_000_000)

    for archive, code in ((many, "ZIP_ENTRY_COUNT_LIMIT"), (bomb, "ZIP_COMPRESSION_RATIO_LIMIT")):
        with pytest.raises(ChemicalPaperError, match=code):
            _zip_inventory(archive)


def test_duplicate_molecule_id_and_page_mismatch_are_rejected(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import ChemicalPaperError, import_chemical_paper

    project = source_truth_project(tmp_path)
    duplicate = [
        {
            "mol_id": "dup", "page_idx": 0, "bbox_normalized": [0, 0, 1, 1],
            "smiles_expanded": "C", "smiles_unexpanded": "C", "mol_idt": "C", "mol_block": v2000(("C",)),
        },
        {
            "mol_id": "dup", "page_idx": 1, "bbox_normalized": [0, 0, 1, 1],
            "smiles_expanded": "N", "smiles_unexpanded": "N", "mol_idt": "N", "mol_block": v2000(("N",)),
        },
    ]
    archive = write_chemical_zip(tmp_path / "duplicate-molecule.zip", molecules=duplicate)
    with pytest.raises(ChemicalPaperError, match="MOLECULE_ID_DUPLICATE"):
        import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)
    archive = write_chemical_zip(tmp_path / "page-count.zip", pages=1)
    with pytest.raises(ChemicalPaperError, match="CHEMICAL_PAPER_PAGE_COUNT_MISMATCH"):
        import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)


def test_empty_but_framed_molblock_is_an_explicit_fillable_gap(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import chemical_paper_projection, import_chemical_paper

    project = source_truth_project(tmp_path)
    molecule = {
        "mol_id": "empty-structure",
        "page_idx": 0,
        "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
        "smiles_expanded": "",
        "smiles_unexpanded": "",
        "mol_idt": "",
        "mol_block": v2000_empty(),
    }
    import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "empty.zip", molecules=[molecule]),
        ACTOR,
    )
    projected = chemical_paper_projection(project)["studies"][0]["molecules"][0]
    assert projected["molblock_available"] is False
    assert projected["candidate_elements"] == []
    assert projected["missing_fields"] == ["mol_idt", "smiles_expanded", "smiles_unexpanded"]


def test_safe_index_mutations_require_current_opaque_version_and_are_zero_write_on_stale(
    tmp_path: Path,
) -> None:
    from review_writer.project.chemical_paper import (
        ChemicalPaperError,
        chemical_paper_projection,
        correct_chemical_paper_field,
        import_chemical_paper,
        review_chemical_paper_elements,
    )

    project = source_truth_project(tmp_path)
    import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )
    version = chemical_paper_projection(project)["studies"][0]["version_token"]
    corrected = correct_chemical_paper_field(
        project,
        study_id="study-1",
        molecule_index=1,
        field="smiles_expanded",
        value="N",
        actor=ACTOR,
        reason="Checked against the original PDF.",
        version_token=version,
    )
    assert corrected["molecule_index"] == 1
    assert corrected["version_token"] != version

    before = snapshot(project)
    with pytest.raises(ChemicalPaperError, match="STALE_CHEMICAL_PAPER_STATE"):
        review_chemical_paper_elements(
            project,
            study_id="study-1",
            molecule_index=1,
            review_state="confirmed",
            actor=ACTOR,
            reason="Optional element review against the original PDF.",
            version_token=version,
        )
    assert snapshot(project) == before

    reviewed = review_chemical_paper_elements(
        project,
        study_id="study-1",
        molecule_index=1,
        review_state="confirmed",
        actor=ACTOR,
        reason="Optional element review against the original PDF.",
        version_token=corrected["version_token"],
    )
    assert reviewed["status"] == "confirmed"
    molecule = chemical_paper_projection(project)["studies"][0]["molecules"][1]
    assert molecule["element_review_state"] == "confirmed"
    assert molecule["smiles_unexpanded"] is None


def test_source_truth_change_makes_chemical_state_stale(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import (
        ChemicalPaperError,
        import_chemical_paper,
        load_chemical_paper_state,
    )

    project = source_truth_project(tmp_path)
    import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )
    bundle_path = project / "01_evidence/source_truth/study-1/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    body["warnings"] = ["fixture source truth changed"]
    bundle_path.write_text(
        json.dumps({**body, "bundle_digest": canonical_digest(body)}),
        encoding="utf-8",
    )
    with pytest.raises(ChemicalPaperError, match="CHEMICAL_PAPER_SOURCE_TRUTH_STALE"):
        load_chemical_paper_state(project, "study-1")


def test_manuscript_bindings_use_exact_frozen_v1_shapes(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import (
        chemical_paper_manuscript_bindings,
        import_chemical_paper,
    )

    project = source_truth_project(tmp_path)
    import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )
    binding = chemical_paper_manuscript_bindings(project)
    assert set(binding) == {
        "chemical_paper_import_digests",
        "chemical_paper_safe_summary",
    }
    assert set(binding["chemical_paper_import_digests"][0]) == {
        "study_id",
        "import_digest",
        "state_digest",
    }
    summary = binding["chemical_paper_safe_summary"]
    assert summary == {
        "schema_version": "chemical-paper-safe-summary.v1",
        "route": "chemical-paper-zip-only",
        "study_count": 1,
        "molecule_count": 2,
        "unresolved_field_count": 3,
        "element_review_counts": {
            "not_reviewed": 2,
            "confirmed": 0,
            "corrected": 0,
            "not_applicable": 0,
        },
        "reaction_data_status": "unavailable_not_provided",
    }


def test_dependency_currentness_is_the_strict_release_authority(tmp_path: Path) -> None:
    from review_writer.project.chemical_paper import (
        chemical_paper_dependency_currentness,
        chemical_paper_manuscript_bindings,
        import_chemical_paper,
    )

    project = source_truth_project(tmp_path)
    import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )
    binding = chemical_paper_manuscript_bindings(project)
    claims = [
        {
            "claim_id": "claim-1",
            "study_id": "study-1",
            "molecule_index": 1,
            "required_fields": ["smiles_expanded"],
            "requires_element_review": True,
            "requires_reaction_data": False,
        }
    ]
    result = chemical_paper_dependency_currentness(
        project,
        import_digests=binding["chemical_paper_import_digests"],
        claim_dependencies=claims,
    )
    assert result == {
        "schema_version": "chemical-paper-dependency-currentness.v1",
        "lineage_binding_status": "current",
        "claims": [
            {
                "claim_id": "claim-1",
                "status": "needs_review",
                "dependencies": [
                    {
                        "study_id": "study-1",
                        "molecule_index": 1,
                        "status": "needs_review",
                        "required_field_statuses": {
                            "smiles_expanded": "unresolved",
                        },
                        "element_review_state": "not_reviewed",
                        "reaction_data_status": "unavailable_not_provided",
                        "blocking_reasons": [
                            "claim-1:elements:not_reviewed",
                            "claim-1:smiles_expanded:unresolved",
                        ],
                    }
                ],
                "blocking_reasons": [
                    "claim-1:elements:not_reviewed",
                    "claim-1:smiles_expanded:unresolved",
                ],
            }
        ],
        "can_release": False,
        "blocking_reasons": [
            "claim-1:elements:not_reviewed",
            "claim-1:smiles_expanded:unresolved",
        ],
    }

    stale = copy.deepcopy(binding["chemical_paper_import_digests"])
    stale[0]["state_digest"] = "f" * 64
    stale_result = chemical_paper_dependency_currentness(
        project,
        import_digests=stale,
        claim_dependencies=claims,
    )
    assert stale_result["lineage_binding_status"] == "stale"
    assert stale_result["can_release"] is False
