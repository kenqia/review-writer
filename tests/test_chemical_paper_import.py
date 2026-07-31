from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from review_writer.project.source_truth import canonical_digest


PDF_BYTES = b"%PDF-1.4\nchemical-paper-fixture\n%%EOF\n"
PDF_SHA = hashlib.sha256(PDF_BYTES).hexdigest()
ACTOR = {"actor_type": "simulated_researcher_agent", "actor_label": "fixture-researcher"}


def _file(
    path: str,
    sha256: str = "b" * 64,
    size_bytes: int = 1,
) -> dict[str, object]:
    return {"path": path, "sha256": sha256, "size_bytes": size_bytes}


def source_truth_project(root: Path, *, study_id: str = "study-1", pages: int = 2) -> Path:
    project = root / "project"
    target = project / "01_evidence/source_truth" / study_id
    target.mkdir(parents=True)
    pdf_path = project / "00_sources/main.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(PDF_BYTES)
    receipt = project / "00_sources/acquisition_final_receipt.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
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
        "pdf": _file("00_sources/main.pdf", PDF_SHA, len(PDF_BYTES)),
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


def replace_source_pdf_binding(
    project: Path,
    study_id: str,
    payload: bytes,
) -> None:
    bundle_path = project / f"01_evidence/source_truth/{study_id}/bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    body = {
        key: copy.deepcopy(value)
        for key, value in bundle.items()
        if key != "bundle_digest"
    }
    source = next(
        row for row in body["sources"] if row.get("document_role") == "MAIN"
    )
    pdf_path = project / source["pdf"]["path"]
    pdf_path.write_bytes(payload)
    source["pdf"]["sha256"] = hashlib.sha256(payload).hexdigest()
    source["pdf"]["size_bytes"] = len(payload)
    body["warnings"] = ["source binding changed for race fixture"]
    bundle_path.write_text(
        json.dumps({**body, "bundle_digest": canonical_digest(body)}),
        encoding="utf-8",
    )


def release_pdf_snapshot(
    project: Path,
    bundle: dict[str, Any],
    payload: bytes,
    snapshot_path: Path,
    *,
    project_instance_root: Path | None = None,
) -> SimpleNamespace:
    source = bundle["sources"][0]
    instance_root = (project_instance_root or project).resolve()
    instance_metadata = instance_root.stat()
    snapshot_path.write_bytes(payload)
    snapshot_path.chmod(0o600)
    return SimpleNamespace(
        path=snapshot_path,
        filename="main.pdf",
        project_id=project.name,
        project_instance_root=instance_root,
        project_device=instance_metadata.st_dev,
        project_inode=instance_metadata.st_ino,
        study_id=bundle["study_id"],
        source_id=source["source_id"],
        kind="pdf",
        bundle_digest=bundle["bundle_digest"],
        sha256=source["pdf"]["sha256"],
        size_bytes=source["pdf"]["size_bytes"],
        page_count=source["page_count"],
    )


def imported_pdf_descriptor(project: Path, archive_path: Path):
    import review_writer.project.chemical_paper as chemical_paper

    chemical_paper.import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(archive_path),
        ACTOR,
    )
    locator = chemical_paper.chemical_paper_projection(project)["studies"][0][
        "molecules"
    ][0]["pdf_page_url"]
    binding = parse_qs(urlsplit(locator).query)["binding"][0]
    return chemical_paper.resolve_chemical_paper_pdf_locator(
        project,
        "source-main",
        binding,
    )


def expand_source_truth_studies(project: Path, study_count: int) -> list[str]:
    study_ids = [f"study-{index}" for index in range(1, study_count + 1)]
    base_path = project / "01_evidence/source_truth/study-1/bundle.json"
    base = json.loads(base_path.read_text(encoding="utf-8"))
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"] = [{"study_id": study_id} for study_id in study_ids]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    for index, study_id in enumerate(study_ids, start=1):
        body = {
            key: copy.deepcopy(value)
            for key, value in base.items()
            if key != "bundle_digest"
        }
        body["study_id"] = study_id
        body["study_identity"] = {
            "doi": f"10.1000/performance-{index}",
            "title": f"Performance fixture {index}",
        }
        body["sources"][0]["source_id"] = f"source-{index}"
        body["sources"][0]["mineru_slug"] = f"study-{index}-main"
        bundle_path = project / f"01_evidence/source_truth/{study_id}/bundle.json"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(
            json.dumps({**body, "bundle_digest": canonical_digest(body)}),
            encoding="utf-8",
        )
    return study_ids


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
    assert state["schema_version"] == "chemical-paper-state.v2"
    assert state["current_import_digest"]
    assert (
        project / "01_evidence/chemical_paper/study-1/state.json"
    ).is_file()
    assert state["source_pdf_sha256"] == PDF_SHA
    assert state["source_truth_bundle_digest"]
    imported_event = state["imports"][state["current_import_digest"]]
    assert imported_event["archive_sha256"] == hashlib.sha256(
        archive.read_bytes()
    ).hexdigest()
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
    assert projection["schema_version"] == "chemical-paper-projection.v2"
    assert projection["studies"][0]["reaction_data_status"] == "unavailable_not_provided"
    molecule_projection = projection["studies"][0]["molecules"][1]
    assert molecule_projection["molecule_index"] == 1
    assert molecule_projection["pdf_page_url"].startswith(
        "/api/project/project/chemical-paper/source/"
        "source-main/pdf-page?page=2&binding=cpb1."
    )
    assert molecule_projection["missing_fields"] == [
        "mol_idt",
        "resolved_smiles",
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
            f"/api/project/project%23quoted%3F/chemical-paper/source/"
            f"source%23{index}%3Fmain/pdf-page?page=2"
        )

    projection = chemical_paper_projection(project)
    observed = {
        study["study_id"]: study["molecules"][1]["pdf_page_url"]
        for study in projection["studies"]
    }

    assert all(
        observed[study_id].startswith(f"{expected_url}&binding=cpb1.")
        for study_id, expected_url in expected.items()
    )
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


@pytest.mark.parametrize("study_count", (3, 30))
def test_safe_projection_builds_a_fresh_linear_source_index_per_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    study_count: int,
) -> None:
    import review_writer.project.source_truth as source_truth
    from review_writer.project.chemical_paper import (
        ChemicalPaperError,
        chemical_paper_projection,
        import_chemical_paper,
    )

    project = source_truth_project(tmp_path)
    study_ids = expand_source_truth_studies(project, study_count)
    for index, study_id in enumerate(study_ids, start=1):
        import_chemical_paper(
            project,
            study_id,
            PDF_SHA,
            write_chemical_zip(tmp_path / f"chemical-{index}.zip"),
            ACTOR,
        )

    real_load = source_truth.load_source_truth_bundle
    load_count = 0

    def counted_load(root: Path, study_id: str) -> dict[str, object]:
        nonlocal load_count
        load_count += 1
        return real_load(root, study_id)

    monkeypatch.setattr(source_truth, "load_source_truth_bundle", counted_load)
    projected = chemical_paper_projection(project)

    assert len(projected["studies"]) == study_count
    assert load_count <= 2 * study_count + 1
    first_request_loads = load_count

    first_bundle = real_load(project, study_ids[0])
    orphan_body = {
        key: copy.deepcopy(value)
        for key, value in first_bundle.items()
        if key != "bundle_digest"
    }
    orphan_body["study_id"] = "orphan-study"
    orphan_body["study_identity"] = {
        "doi": "10.1000/performance-orphan",
        "title": "Fresh-index orphan collision",
    }
    orphan_path = project / "01_evidence/source_truth/orphan-study/bundle.json"
    orphan_path.parent.mkdir(parents=True)
    orphan_path.write_text(
        json.dumps(
            {**orphan_body, "bundle_digest": canonical_digest(orphan_body)}
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ChemicalPaperError,
        match="CHEMICAL_PAPER_SOURCE_TRUTH_STALE",
    ):
        chemical_paper_projection(project)
    assert first_request_loads < load_count <= first_request_loads + study_count + 2


def test_safe_projection_never_combines_indexed_binding_a_with_asset_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project = source_truth_project(tmp_path)
    chemical_paper.import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )
    real_binding = chemical_paper.project_source_binding
    switched = False

    def switch_after_indexed_binding(root: Path, source_id: str, **kwargs):
        nonlocal switched
        resolved = real_binding(root, source_id, **kwargs)
        if kwargs.get("source_index") is not None and not switched:
            replace_source_pdf_binding(
                project,
                "study-1",
                b"%PDF-1.4\nbinding-b\n%%EOF\n",
            )
            switched = True
        return resolved

    monkeypatch.setattr(
        chemical_paper,
        "project_source_binding",
        switch_after_indexed_binding,
    )

    with pytest.raises(ChemicalPaperError, match="SOURCE_ASSET_DRIFT"):
        chemical_paper.chemical_paper_projection(project)
    assert switched is True


def test_locator_binding_is_stable_per_project_instance_and_unique_across_roots(
    tmp_path: Path,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project_a = source_truth_project(tmp_path / "root-a")
    project_b = source_truth_project(tmp_path / "root-b")
    for root, project in ((tmp_path / "root-a", project_a), (tmp_path / "root-b", project_b)):
        chemical_paper.import_chemical_paper(
            project,
            "study-1",
            PDF_SHA,
            write_chemical_zip(root / "chemical.zip"),
            ACTOR,
        )

    locator_a = chemical_paper.chemical_paper_projection(project_a)["studies"][0][
        "molecules"
    ][0]["pdf_page_url"]
    locator_a_after_restart = chemical_paper.chemical_paper_projection(project_a)[
        "studies"
    ][0]["molecules"][0]["pdf_page_url"]
    locator_b = chemical_paper.chemical_paper_projection(project_b)["studies"][0][
        "molecules"
    ][0]["pdf_page_url"]
    token_a = parse_qs(urlsplit(locator_a).query)["binding"][0]
    token_b = parse_qs(urlsplit(locator_b).query)["binding"][0]

    assert locator_a_after_restart == locator_a
    assert token_a != token_b
    assert str(project_a.resolve()) not in locator_a
    assert str(project_b.resolve()) not in locator_b
    assert PDF_SHA not in locator_a + locator_b
    with pytest.raises(ChemicalPaperError, match="STALE_CHEMICAL_PAPER_LOCATOR"):
        chemical_paper.chemical_paper_pdf_locator(
            project_b,
            "source-main",
            token_a,
        )


def test_public_locator_descriptor_revalidates_with_a_fresh_orphan_aware_index(
    tmp_path: Path,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    resolver = getattr(chemical_paper, "resolve_chemical_paper_pdf_locator", None)
    verifier = getattr(chemical_paper, "verify_chemical_paper_pdf_locator", None)
    assert callable(resolver)
    assert callable(verifier)

    project = source_truth_project(tmp_path)
    chemical_paper.import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )
    locator = chemical_paper.chemical_paper_projection(project)["studies"][0][
        "molecules"
    ][0]["pdf_page_url"]
    binding = parse_qs(urlsplit(locator).query)["binding"][0]
    descriptor = resolver(project, "source-main", binding)
    verifier(descriptor)

    source_path = project / "01_evidence/source_truth/study-1/bundle.json"
    source_bundle = json.loads(source_path.read_text(encoding="utf-8"))
    orphan_body = {
        key: copy.deepcopy(value)
        for key, value in source_bundle.items()
        if key != "bundle_digest"
    }
    orphan_body["study_id"] = "orphan-study"
    orphan_body["study_identity"] = {
        "doi": "10.1000/fresh-index-orphan",
        "title": "Fresh-index orphan collision",
    }
    orphan_path = project / "01_evidence/source_truth/orphan-study/bundle.json"
    orphan_path.parent.mkdir(parents=True)
    orphan_path.write_text(
        json.dumps(
            {**orphan_body, "bundle_digest": canonical_digest(orphan_body)}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ChemicalPaperError, match="STALE_CHEMICAL_PAPER_LOCATOR"):
        verifier(descriptor)


def test_locator_descriptor_binds_immutable_snapshot_bytes_across_aba(
    tmp_path: Path,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project = source_truth_project(tmp_path)
    chemical_paper.import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        write_chemical_zip(tmp_path / "chemical.zip"),
        ACTOR,
    )
    locator = chemical_paper.chemical_paper_projection(project)["studies"][0][
        "molecules"
    ][0]["pdf_page_url"]
    binding = parse_qs(urlsplit(locator).query)["binding"][0]
    descriptor = chemical_paper.resolve_chemical_paper_pdf_locator(
        project,
        "source-main",
        binding,
    )
    bundle_path = project / "01_evidence/source_truth/study-1/bundle.json"
    bundle_a_bytes = bundle_path.read_bytes()
    bundle_a = json.loads(bundle_a_bytes)
    snapshot_a = release_pdf_snapshot(
        project,
        bundle_a,
        PDF_BYTES,
        tmp_path / "snapshot-a.pdf",
    )

    pdf_b = b"%PDF-1.4\nimmutable-snapshot-b\n%%EOF\n"
    replace_source_pdf_binding(project, "study-1", pdf_b)
    bundle_b = json.loads(bundle_path.read_text(encoding="utf-8"))
    snapshot_b = release_pdf_snapshot(
        project,
        bundle_b,
        pdf_b,
        tmp_path / "snapshot-b.pdf",
    )

    (project / "00_sources/main.pdf").write_bytes(PDF_BYTES)
    bundle_path.write_bytes(bundle_a_bytes)
    chemical_paper.verify_chemical_paper_pdf_locator(descriptor)
    assert descriptor.source_truth_bundle_digest == bundle_a["bundle_digest"]
    assert descriptor.pdf_sha256 == PDF_SHA
    assert descriptor.pdf_size_bytes == len(PDF_BYTES)
    chemical_paper.verify_chemical_paper_pdf_snapshot(descriptor, snapshot_a)
    chemical_paper.verify_chemical_paper_pdf_snapshot(
        descriptor,
        sha256=snapshot_a.sha256,
        size_bytes=snapshot_a.size_bytes,
    )
    for field, value in (
        ("project_id", "other-project"),
        ("project_device", snapshot_a.project_device + 1),
        ("project_inode", snapshot_a.project_inode + 1),
        ("study_id", "other-study"),
        ("source_id", "other-source"),
        ("kind", "parsed-markdown"),
        ("bundle_digest", "f" * 64),
    ):
        wrong_identity = SimpleNamespace(
            **{**vars(snapshot_a), field: value},
        )
        with pytest.raises(
            ChemicalPaperError,
            match="STALE_CHEMICAL_PAPER_LOCATOR",
        ):
            chemical_paper.verify_chemical_paper_pdf_snapshot(
                descriptor,
                wrong_identity,
            )
    for wrong_descriptor in (
        replace(
            descriptor,
            binding=(
                descriptor.binding[:-1]
                + ("A" if descriptor.binding[-1] != "A" else "B")
            ),
        ),
        replace(descriptor, pdf_sha256="e" * 64),
        replace(descriptor, pdf_size_bytes=descriptor.pdf_size_bytes + 1),
    ):
        with pytest.raises(
            ChemicalPaperError,
            match="STALE_CHEMICAL_PAPER_LOCATOR",
        ):
            chemical_paper.verify_chemical_paper_pdf_snapshot(
                wrong_descriptor,
                snapshot_a,
            )

    with pytest.raises(ChemicalPaperError, match="STALE_CHEMICAL_PAPER_LOCATOR"):
        chemical_paper.verify_chemical_paper_pdf_snapshot(
            descriptor,
            snapshot_b,
        )
    with pytest.raises(ChemicalPaperError, match="STALE_CHEMICAL_PAPER_LOCATOR"):
        chemical_paper.verify_chemical_paper_pdf_snapshot(
            descriptor,
            sha256=snapshot_b.sha256,
            size_bytes=snapshot_b.size_bytes,
        )


def test_snapshot_verifier_rejects_cross_root_and_missing_instance_identity(
    tmp_path: Path,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project_a = source_truth_project(tmp_path / "root-a")
    project_b = source_truth_project(tmp_path / "root-b")
    descriptor_a = imported_pdf_descriptor(
        project_a,
        tmp_path / "chemical-a.zip",
    )
    bundle_b = json.loads(
        (
            project_b / "01_evidence/source_truth/study-1/bundle.json"
        ).read_text(encoding="utf-8")
    )
    snapshot_b = release_pdf_snapshot(
        project_b,
        bundle_b,
        PDF_BYTES,
        tmp_path / "snapshot-root-b.pdf",
    )

    with pytest.raises(ChemicalPaperError, match="STALE_CHEMICAL_PAPER_LOCATOR"):
        chemical_paper.verify_chemical_paper_pdf_snapshot(
            descriptor_a,
            snapshot_b,
        )
    for field in ("project_instance_root", "project_device", "project_inode"):
        missing_instance = vars(snapshot_b).copy()
        missing_instance.pop(field)
        with pytest.raises(
            ChemicalPaperError,
            match="CHEMICAL_PAPER_PDF_SNAPSHOT_INVALID",
        ):
            chemical_paper.verify_chemical_paper_pdf_snapshot(
                descriptor_a,
                SimpleNamespace(**missing_instance),
            )


def test_snapshot_verifier_rejects_same_path_project_instance_replacement(
    tmp_path: Path,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project = source_truth_project(tmp_path / "live")
    descriptor = imported_pdf_descriptor(project, tmp_path / "chemical.zip")
    bundle = json.loads(
        (
            project / "01_evidence/source_truth/study-1/bundle.json"
        ).read_text(encoding="utf-8")
    )
    snapshot = release_pdf_snapshot(
        project,
        bundle,
        PDF_BYTES,
        tmp_path / "snapshot-before-replacement.pdf",
    )
    retired = tmp_path / "retired-project"
    project.rename(retired)
    shutil.copytree(retired, project)
    assert retired.stat().st_ino != project.stat().st_ino

    with pytest.raises(ChemicalPaperError, match="STALE_CHEMICAL_PAPER_LOCATOR"):
        chemical_paper.verify_chemical_paper_pdf_snapshot(
            descriptor,
            snapshot,
        )


def test_snapshot_verifier_rejects_forged_bytes_page_count_and_symlink(
    tmp_path: Path,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project = source_truth_project(tmp_path)
    descriptor = imported_pdf_descriptor(project, tmp_path / "chemical.zip")
    bundle = json.loads(
        (
            project / "01_evidence/source_truth/study-1/bundle.json"
        ).read_text(encoding="utf-8")
    )
    wrong_bytes = b"X" * len(PDF_BYTES)
    forged_bytes = release_pdf_snapshot(
        project,
        bundle,
        wrong_bytes,
        tmp_path / "forged-bytes.pdf",
    )
    valid_snapshot = release_pdf_snapshot(
        project,
        bundle,
        PDF_BYTES,
        tmp_path / "valid-snapshot.pdf",
    )
    wrong_page_count = SimpleNamespace(
        **{**vars(valid_snapshot), "page_count": 999},
    )
    symlink_target = tmp_path / "symlink-target.pdf"
    symlink_target.write_bytes(PDF_BYTES)
    symlink_target.chmod(0o600)
    symlink_path = tmp_path / "snapshot-link.pdf"
    symlink_path.symlink_to(symlink_target)
    symlink_snapshot = SimpleNamespace(
        **{**vars(valid_snapshot), "path": symlink_path},
    )
    public_path = tmp_path / "public-snapshot.pdf"
    public_path.write_bytes(PDF_BYTES)
    public_path.chmod(0o644)
    public_snapshot = SimpleNamespace(
        **{**vars(valid_snapshot), "path": public_path},
    )

    for snapshot in (forged_bytes, wrong_page_count):
        with pytest.raises(
            ChemicalPaperError,
            match="STALE_CHEMICAL_PAPER_LOCATOR",
        ):
            chemical_paper.verify_chemical_paper_pdf_snapshot(
                descriptor,
                snapshot,
            )
    for snapshot in (symlink_snapshot, public_snapshot):
        with pytest.raises(
            ChemicalPaperError,
            match="CHEMICAL_PAPER_PDF_SNAPSHOT_INVALID",
        ):
            chemical_paper.verify_chemical_paper_pdf_snapshot(
                descriptor,
                snapshot,
            )


def test_snapshot_verifier_rejects_path_swap_between_lstat_and_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project = source_truth_project(tmp_path)
    descriptor = imported_pdf_descriptor(project, tmp_path / "chemical.zip")
    bundle = json.loads(
        (
            project / "01_evidence/source_truth/study-1/bundle.json"
        ).read_text(encoding="utf-8")
    )
    snapshot = release_pdf_snapshot(
        project,
        bundle,
        PDF_BYTES,
        tmp_path / "snapshot.pdf",
    )
    attacker = tmp_path / "attacker.pdf"
    attacker.write_bytes(b"X" * len(PDF_BYTES))
    attacker.chmod(0o600)
    real_open = chemical_paper.os.open
    swapped = False

    def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if Path(path) == snapshot.path and not swapped:
            os.replace(attacker, snapshot.path)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(chemical_paper.os, "open", swap_before_open)

    with pytest.raises(
        ChemicalPaperError,
        match="CHEMICAL_PAPER_PDF_SNAPSHOT_INVALID",
    ):
        chemical_paper.verify_chemical_paper_pdf_snapshot(
            descriptor,
            snapshot,
        )
    assert swapped is True


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


def test_safe_projection_rejects_cross_study_duplicate_source_id(
    tmp_path: Path,
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
    first_path = project / "01_evidence/source_truth/study-1/bundle.json"
    first = json.loads(first_path.read_text(encoding="utf-8"))
    second_body = {
        key: copy.deepcopy(value)
        for key, value in first.items()
        if key != "bundle_digest"
    }
    second_body["study_id"] = "study-2"
    second_body["study_identity"] = {
        "doi": "10.1000/test-2",
        "title": "Fixture study 2",
    }
    second_path = project / "01_evidence/source_truth/study-2/bundle.json"
    second_path.parent.mkdir(parents=True)
    second_path.write_text(
        json.dumps(
            {**second_body, "bundle_digest": canonical_digest(second_body)}
        ),
        encoding="utf-8",
    )
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["studies"].append({"study_id": "study-2"})
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(
        ChemicalPaperError,
        match="CHEMICAL_PAPER_SOURCE_TRUTH_STALE",
    ):
        chemical_paper_projection(project)


def test_safe_projection_rejects_orphan_source_collision_outside_receipt(
    tmp_path: Path,
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
    first_path = project / "01_evidence/source_truth/study-1/bundle.json"
    first = json.loads(first_path.read_text(encoding="utf-8"))
    orphan_body = {
        key: copy.deepcopy(value)
        for key, value in first.items()
        if key != "bundle_digest"
    }
    orphan_body["study_id"] = "orphan-study"
    orphan_body["study_identity"] = {
        "doi": "10.1000/orphan",
        "title": "Undeclared orphan fixture",
    }
    orphan_path = project / "01_evidence/source_truth/orphan-study/bundle.json"
    orphan_path.parent.mkdir(parents=True)
    orphan_path.write_text(
        json.dumps(
            {**orphan_body, "bundle_digest": canonical_digest(orphan_body)}
        ),
        encoding="utf-8",
    )

    receipt = json.loads(
        (project / "00_sources/acquisition_final_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["studies"] == [{"study_id": "study-1"}]
    with pytest.raises(
        ChemicalPaperError,
        match="CHEMICAL_PAPER_SOURCE_TRUTH_STALE",
    ):
        chemical_paper_projection(project)


@pytest.mark.parametrize(
    ("asset_failure", "error_code"),
    (
        ("deleted", "SOURCE_ASSET_INVALID"),
        ("drift", "SOURCE_ASSET_DRIFT"),
        ("symlink", "SOURCE_ASSET_INVALID"),
        ("invalid", "SOURCE_ASSET_INVALID"),
    ),
)
def test_safe_projection_requires_the_current_bound_original_pdf_file(
    tmp_path: Path,
    asset_failure: str,
    error_code: str,
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
    pdf_path = project / "00_sources/main.pdf"
    pdf_path.unlink()
    if asset_failure == "drift":
        pdf_path.write_bytes(b"drifted original PDF")
    elif asset_failure == "symlink":
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(PDF_BYTES)
        pdf_path.symlink_to(outside)
    elif asset_failure == "invalid":
        pdf_path.mkdir()

    with pytest.raises(
        ChemicalPaperError,
        match=error_code,
    ):
        chemical_paper_projection(project)


@pytest.mark.parametrize(
    "identity_failure",
    ("bundle_project", "bundle_study", "state_study"),
)
def test_safe_projection_rejects_digest_valid_wrong_self_identity(
    tmp_path: Path,
    identity_failure: str,
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
    if identity_failure == "state_study":
        state["study_id"] = "wrong-study"
    else:
        bundle_path = project / "01_evidence/source_truth/study-1/bundle.json"
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
        body["project_id" if identity_failure == "bundle_project" else "study_id"] = (
            "wrong-project" if identity_failure == "bundle_project" else "wrong-study"
        )
        bundle_digest = canonical_digest(body)
        bundle_path.write_text(
            json.dumps({**body, "bundle_digest": bundle_digest}),
            encoding="utf-8",
        )
        state["source_truth_bundle_digest"] = bundle_digest
        active = state["imports"][state["current_import_digest"]]
        active["source_truth_bundle_digest"] = bundle_digest
        active["import_event_digest"] = canonical_digest(
            {key: value for key, value in active.items() if key != "import_event_digest"}
        )
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
        field="resolved_smiles",
        value="CC",
        actor=ACTOR,
        reason="Checked exported index against the original PDF.",
        pdf_locator={"page": 2},
        version_token=first["version_token"],
    )
    state = load_chemical_paper_state(project, "study-1")
    assert state["field_corrections"][-1]["molecule_id"] == "export-first"
    assert chemical_paper_projection(project)["studies"][0]["molecules"][0][
        "resolved_smiles"
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


@pytest.mark.parametrize(
    ("asset_failure", "error_code"),
    (("deleted", "SOURCE_ASSET_INVALID"), ("drift", "SOURCE_ASSET_DRIFT")),
)
def test_first_import_rejects_missing_or_drifted_pdf_without_chemical_state(
    tmp_path: Path,
    asset_failure: str,
    error_code: str,
) -> None:
    from review_writer.project.chemical_paper import (
        ChemicalPaperError,
        import_chemical_paper,
    )

    project = source_truth_project(tmp_path)
    archive = write_chemical_zip(tmp_path / "chemical.zip")
    pdf_path = project / "00_sources/main.pdf"
    pdf_path.unlink()
    if asset_failure == "drift":
        pdf_path.write_bytes(b"drifted original PDF")
    before = snapshot(project)

    with pytest.raises(ChemicalPaperError, match=error_code):
        import_chemical_paper(project, "study-1", PDF_SHA, archive, ACTOR)

    assert snapshot(project) == before
    assert not (
        project / "01_evidence/chemical_paper/study-1/state.json"
    ).exists()


@pytest.mark.parametrize(
    ("stale_input", "error_code"),
    (
        ("bundle", "SOURCE_INPUT_STALE"),
        ("receipt", "SOURCE_INPUT_STALE"),
        ("pdf_deleted", "SOURCE_ASSET_INVALID"),
        ("pdf_drift", "SOURCE_ASSET_DRIFT"),
    ),
)
def test_first_import_revalidates_source_inputs_inside_commit_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_input: str,
    error_code: str,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError
    from review_writer.project.paper_evidence_store import (
        project_write_lock as real_project_write_lock,
    )

    project = source_truth_project(tmp_path)
    archive = write_chemical_zip(tmp_path / "chemical.zip")

    @contextmanager
    def drift_input_after_lock(root: Path):
        with real_project_write_lock(root):
            if stale_input == "bundle":
                bundle_path = root / "01_evidence/source_truth/study-1/bundle.json"
                bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                body = {
                    key: value
                    for key, value in bundle.items()
                    if key != "bundle_digest"
                }
                body["warnings"] = ["changed while import waited for commit lock"]
                bundle_path.write_text(
                    json.dumps({**body, "bundle_digest": canonical_digest(body)}),
                    encoding="utf-8",
                )
            elif stale_input == "receipt":
                receipt_path = root / "00_sources/acquisition_final_receipt.json"
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt["lock_race_marker"] = "changed"
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            else:
                pdf_path = root / "00_sources/main.pdf"
                pdf_path.unlink()
                if stale_input == "pdf_drift":
                    pdf_path.write_bytes(b"drifted while import waited for lock")
            yield

    monkeypatch.setattr(
        chemical_paper,
        "project_write_lock",
        drift_input_after_lock,
    )

    with pytest.raises(ChemicalPaperError, match=error_code):
        chemical_paper.import_chemical_paper(
            project,
            "study-1",
            PDF_SHA,
            archive,
            ACTOR,
        )

    assert not (
        project / "01_evidence/chemical_paper/study-1/state.json"
    ).exists()


def test_first_import_rejects_zip_path_replacement_without_mixed_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project = source_truth_project(tmp_path)
    original = write_chemical_zip(
        tmp_path / "chemical.zip",
        molecules=[{
            "mol_id": "old-carbon",
            "page_idx": 0,
            "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
            "smiles_expanded": "C",
            "smiles_unexpanded": "C",
            "mol_idt": "old-carbon",
            "mol_block": v2000(("C",)),
        }],
    )
    replacement = write_chemical_zip(
        tmp_path / "replacement.zip",
        molecules=[{
            "mol_id": "new-nitrogen",
            "page_idx": 0,
            "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
            "smiles_expanded": "N",
            "smiles_unexpanded": "N",
            "mol_idt": "new-nitrogen",
            "mol_block": v2000(("N",)),
        }],
    )
    replacement_sha256 = hashlib.sha256(replacement.read_bytes()).hexdigest()
    real_read_entry = chemical_paper._read_entry
    replaced = False

    def replace_path_after_entry_read(
        archive: zipfile.ZipFile,
        member: zipfile.ZipInfo,
    ) -> bytes:
        nonlocal replaced
        payload = real_read_entry(archive, member)
        if not replaced:
            os.replace(replacement, original)
            replaced = True
        return payload

    monkeypatch.setattr(chemical_paper, "_read_entry", replace_path_after_entry_read)

    with pytest.raises(ChemicalPaperError, match="ZIP_INPUT_STALE"):
        chemical_paper.import_chemical_paper(
            project,
            "study-1",
            PDF_SHA,
            original,
            ACTOR,
        )

    assert hashlib.sha256(original.read_bytes()).hexdigest() == replacement_sha256
    assert not (
        project / "01_evidence/chemical_paper/study-1/state.json"
    ).exists()


def test_first_import_rejects_symlink_zip_without_o_nofollow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project = source_truth_project(tmp_path)
    archive = write_chemical_zip(tmp_path / "outside.zip")
    linked = tmp_path / "linked.zip"
    linked.symlink_to(archive)
    monkeypatch.delattr(chemical_paper.os, "O_NOFOLLOW", raising=False)
    before = snapshot(project)

    with pytest.raises(ChemicalPaperError, match="ZIP_INVALID"):
        chemical_paper.import_chemical_paper(
            project,
            "study-1",
            PDF_SHA,
            linked,
            ACTOR,
        )

    assert snapshot(project) == before
    assert not (
        project / "01_evidence/chemical_paper/study-1/state.json"
    ).exists()


def test_first_import_rejects_dynamic_symlink_swap_without_o_nofollow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper
    from review_writer.project.chemical_paper import ChemicalPaperError

    project = source_truth_project(tmp_path)
    legitimate = write_chemical_zip(
        tmp_path / "input.zip",
        molecules=[{
            "mol_id": "legitimate",
            "page_idx": 0,
            "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
            "smiles_expanded": "C",
            "smiles_unexpanded": "C",
            "mol_idt": "legitimate",
            "mol_block": v2000(("C",)),
        }],
    )
    attacker = write_chemical_zip(
        tmp_path / "outside-attacker.zip",
        molecules=[{
            "mol_id": "attacker",
            "page_idx": 0,
            "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
            "smiles_expanded": "N",
            "smiles_unexpanded": "N",
            "mol_idt": "attacker",
            "mol_block": v2000(("N",)),
        }],
    )
    parked = tmp_path / "parked-legitimate.zip"
    real_open = chemical_paper.os.open
    swap_count = 0

    def swap_to_symlink_during_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swap_count
        if isinstance(path, (str, bytes, os.PathLike)) and Path(path) == legitimate:
            legitimate.rename(parked)
            legitimate.symlink_to(attacker)
            try:
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
            finally:
                legitimate.unlink()
                parked.rename(legitimate)
            swap_count += 1
            return descriptor
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.delattr(chemical_paper.os, "O_NOFOLLOW", raising=False)
    monkeypatch.setattr(chemical_paper.os, "open", swap_to_symlink_during_open)
    before = snapshot(project)

    with pytest.raises(ChemicalPaperError, match="ZIP_INVALID"):
        chemical_paper.import_chemical_paper(
            project,
            "study-1",
            PDF_SHA,
            legitimate,
            ACTOR,
        )

    assert swap_count == 1
    assert snapshot(project) == before
    assert not (
        project / "01_evidence/chemical_paper/study-1/state.json"
    ).exists()


def test_first_import_supports_regular_zip_without_o_nofollow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.chemical_paper as chemical_paper

    project = source_truth_project(tmp_path)
    archive = write_chemical_zip(tmp_path / "regular.zip")
    monkeypatch.delattr(chemical_paper.os, "O_NOFOLLOW", raising=False)

    result = chemical_paper.import_chemical_paper(
        project,
        "study-1",
        PDF_SHA,
        archive,
        ACTOR,
    )

    assert result["status"] == "imported"
    state = chemical_paper.load_chemical_paper_state(project, "study-1")
    assert state["molecules"][0]["molecule_id"] == "mol-1"


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
        "resolved_smiles",
        "N",
        ACTOR,
        reason="Checked against the original PDF.",
        pdf_locator={"page": 1},
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
    assert projection["studies"][0]["molecules"][1]["resolved_smiles"] == "N"

    before = snapshot(project)
    with pytest.raises(ChemicalPaperError, match="STALE_CHEMICAL_PAPER_STATE"):
        append_chemical_field_correction(
            project, "study-1", "mol-2", "mol_idt", "amine", ACTOR,
            reason="Original PDF review.", expected_version_token=imported["version_token"],
            pdf_locator={"page": 1},
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
        "required_fields": ["resolved_smiles"],
    }])
    assert text_only["dependency_status"] == "ready"
    assert chemical["dependency_status"] == "blocked_unresolved"
    assert chemical["gaps"] == ["study-1/mol-2:resolved_smiles:unresolved"]


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
    assert projected["missing_fields"] == ["mol_idt", "resolved_smiles"]


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
        field="resolved_smiles",
        value="N",
        actor=ACTOR,
        reason="Checked against the original PDF.",
        pdf_locator={"page": 1},
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
    assert molecule["resolved_smiles"] == "N"
    assert molecule["smiles_candidates"]["unexpanded"] is None


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


def test_manuscript_bindings_use_exact_frozen_v2_shapes(tmp_path: Path) -> None:
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
        "schema_version": "chemical-paper-safe-summary.v2",
        "route": "chemical-paper-zip-only",
        "study_count": 1,
        "molecule_count": 2,
        "missing_name_count": 1,
        "missing_resolved_smiles_count": 1,
        "ai_authored_smiles_count": 0,
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
            "required_fields": ["resolved_smiles"],
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
        "schema_version": "chemical-paper-dependency-currentness.v2",
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
                            "resolved_smiles": "unresolved",
                        },
                        "element_review_state": "not_reviewed",
                        "reaction_data_status": "unavailable_not_provided",
                        "blocking_reasons": [
                            "claim-1:elements:not_reviewed",
                            "claim-1:resolved_smiles:unresolved",
                        ],
                    }
                ],
                "blocking_reasons": [
                    "claim-1:elements:not_reviewed",
                    "claim-1:resolved_smiles:unresolved",
                ],
            }
        ],
        "can_release": False,
        "blocking_reasons": [
            "claim-1:elements:not_reviewed",
            "claim-1:resolved_smiles:unresolved",
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
