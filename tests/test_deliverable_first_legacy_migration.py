from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from review_writer.project.chemical_completion import (
    apply_chemical_completion_batch,
    chemical_completion_state,
)
from review_writer.project.chemical_paper import import_chemical_paper
from review_writer.project.deliverable_first_migration import (
    DeliverableFirstMigrationError,
    migrate_legacy_three_paper_project,
    strict_evidence_trace,
)
from review_writer.project.dual_source import write_dual_source_binding
from review_writer.project.paper_evidence import (
    apply_paper_evidence_decision,
    paper_evidence_state,
    register_paper_evidence_candidates,
)
from review_writer.project.parse_quality import (
    apply_parse_quality_decision,
    write_parse_quality_gate,
)
from review_writer.project.parse_reconciliation import write_parse_reconciliation
from review_writer.project.source_truth import (
    canonical_digest,
    load_source_truth_bundle,
    write_source_truth_bundle,
)
from test_chemical_paper_import import v2000, write_chemical_zip
from test_source_truth import _source_truth_project


STUDIES = (
    ("scholarly-a", "stud-a", "a", "10.1000/example-a"),
    ("scholarly-b", "stud-b", "b", "10.1000/example-b"),
    ("scholarly-c", "stud-c", "c", "10.1000/example-c"),
)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _snapshot(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _clone_three_source_inputs(project: Path) -> None:
    base_extracted = project / "01_evidence/parses/extracted/10_1000_example"
    base_mineru_markdown = project / "01_evidence/mineru/markdown/10_1000_example.md"
    base_parse_markdown = project / "01_evidence/parses/markdown/10_1000_example.md"
    base_reading = project / "01_evidence/text_layers/stud-a.reading.txt"
    base_layout = project / "01_evidence/text_layers/stud-a.layout.txt"

    receipt = _read_json(project / "00_sources/acquisition_final_receipt.json")
    coverage = _read_json(project / "00_sources/source_coverage.json")
    identity = _read_json(project / "00_sources/source_identity_audit.json")
    mineru = _read_json(project / "01_evidence/mineru/manifest.json")
    text_layers = _read_json(
        project / "01_evidence/text_layers/text_layers.manifest.json"
    )

    receipt_rows = []
    coverage_rows = []
    identity_rows = []
    mineru_rows = []
    text_rows = []
    candidate_rows = []
    for index, (study_id, source_id, suffix, doi) in enumerate(STUDIES, start=1):
        slug = f"10_1000_example_{suffix}"
        pdf_relative = f"papers/paper-{suffix}.pdf"
        pdf_bytes = f"%PDF-main-{suffix}".encode()
        pdf_path = project / "00_sources" / pdf_relative
        pdf_path.write_bytes(pdf_bytes)
        pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()

        extracted = project / "01_evidence/parses/extracted" / slug
        if extracted != base_extracted:
            shutil.copytree(base_extracted, extracted)
        mineru_markdown = project / "01_evidence/mineru/markdown" / f"{slug}.md"
        parse_markdown = project / "01_evidence/parses/markdown" / f"{slug}.md"
        if mineru_markdown != base_mineru_markdown:
            shutil.copy2(base_mineru_markdown, mineru_markdown)
            shutil.copy2(base_parse_markdown, parse_markdown)
        reading_name = f"{source_id}.reading.txt"
        layout_name = f"{source_id}.layout.txt"
        reading_path = project / "01_evidence/text_layers" / reading_name
        layout_path = project / "01_evidence/text_layers" / layout_name
        if reading_path != base_reading:
            shutil.copy2(base_reading, reading_path)
            shutil.copy2(base_layout, layout_path)

        receipt_rows.append(
            {
                "study_id": study_id,
                "doi": doi,
                "document_role": "MAIN",
                "status": "ACQUIRED",
                "main_pdf": {
                    "path": pdf_relative,
                    "sha256": pdf_sha,
                    "size_bytes": len(pdf_bytes),
                },
            }
        )
        coverage_rows.append(
            {
                "study_id": study_id,
                "available_roles": ["MAIN"],
                "main_policy": "REQUIRED",
                "si_policy": "NOT_REQUIRED",
                "study_status": "READY",
            }
        )
        identity_rows.append(
            {
                "candidate_id": study_id,
                "doi": doi,
                "title": f"Fixture study {index}",
                "verdict": "PASS",
            }
        )
        mineru_rows.append(
            {
                "data_id": f"00{index}-{slug}",
                "slug": slug,
                "state": "done",
                "relative_pdf_path": pdf_relative,
                "markdown_copy": f"markdown/{slug}.md",
            }
        )
        text_rows.append(
            {
                "source_id": source_id,
                "pdf_name": f"paper-{suffix}.pdf",
                "pdf_sha256": pdf_sha,
                "page_count": 1,
                "reading_order_path": reading_name,
                "reading_order_sha256": hashlib.sha256(
                    reading_path.read_bytes()
                ).hexdigest(),
                "layout_path": layout_name,
                "layout_sha256": hashlib.sha256(
                    layout_path.read_bytes()
                ).hexdigest(),
            }
        )
        candidate_rows.append(
            {
                "candidate_id": study_id,
                "study_id": study_id,
                "source_id": source_id,
                "tier": "core",
                "doi": doi,
                "title": f"Fixture study {index}",
                "document_role": "MAIN",
            }
        )

    receipt["studies"] = receipt_rows
    coverage["studies"] = coverage_rows
    identity["results"] = identity_rows
    mineru["completed"] = mineru_rows
    text_layers["sources"] = text_rows
    _write_json(project / "00_sources/acquisition_final_receipt.json", receipt)
    _write_json(project / "00_sources/source_coverage.json", coverage)
    _write_json(project / "00_sources/source_identity_audit.json", identity)
    _write_json(project / "01_evidence/mineru/manifest.json", mineru)
    _write_json(
        project / "01_evidence/text_layers/text_layers.manifest.json", text_layers
    )
    _write_json(
        project / "00_discovery/candidate_pool.json",
        {"schema_version": "candidate-pool.v1", "candidates": candidate_rows},
    )


def _approve_parse(project: Path, study_id: str) -> None:
    state = write_parse_quality_gate(project, study_id)
    for row in state["objects"]:
        if row["status"] == "usable":
            continue
        state = apply_parse_quality_decision(
            project,
            study_id,
            {
                "object_id": row["object_id"],
                "object_digest": row["object_digest"],
                "gate_digest": state["gate_digest"],
                "action": "approve_candidate_extraction",
                "note": "Compared with the synthetic original PDF.",
                "actor_type": "simulated_researcher_agent",
                "actor_label": "fixture-parse-reviewer",
            },
        )


def _candidate(study_id: str, source_id: str, index: int) -> dict:
    return {
        "evidence_id": f"{study_id}-evidence-{index}",
        "source_id": source_id,
        "epistemic_type": "experimental_observation",
        "statement": f"Study {study_id} reported bounded observation {index}.",
        "locator": {
            "source_mode": "parsed_candidate",
            "page": 1,
            "section_or_item": "Results",
            "figure_or_table": "Figure 1" if index == 1 else None,
            "exact_quote": f"Bounded excerpt {study_id} {index}.",
        },
        "reported_conditions": ["Synthetic condition"],
        "quantitative_results": ["Synthetic result"],
        "limitations": ["Synthetic fixture only"],
        "mechanism_grade": "not_applicable",
        "risk_classes": ["MECHANISM_CAUSALITY"],
        "field_dependencies": [],
    }


def _legacy_three_paper_project(
    tmp_path: Path,
    *,
    evidence_actor: tuple[str, str] = (
        "simulated_researcher_agent",
        "fixture-evidence-reviewer",
    ),
) -> tuple[Path, list[dict], list[tuple[str, str]]]:
    project = _source_truth_project(tmp_path / "source")
    _clone_three_source_inputs(project)
    for study_id, _, _, _ in STUDIES:
        write_source_truth_bundle(project, study_id)
        _approve_parse(project, study_id)

    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = _read_json(receipt_path)
    receipt.update(
        {"corpus_kind": "legacy_three_paper", "variable_n": False, "study_count": 3}
    )
    _write_json(receipt_path, receipt)

    expected_correction_actors = []
    for index, (study_id, _, suffix, _) in enumerate(STUDIES, start=1):
        bundle = load_source_truth_bundle(project, study_id)
        source_sha = bundle["sources"][0]["pdf"]["sha256"]
        archive = write_chemical_zip(
            tmp_path / f"chemical-{suffix}.zip",
            pages=1,
            molecules=[
                {
                    "mol_id": f"molecule-{suffix}",
                    "page_idx": 0,
                    "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
                    "smiles_expanded": "",
                    "smiles_unexpanded": "",
                    "mol_idt": f"compound-{suffix}",
                    "mol_block": v2000(),
                }
            ],
        )
        import_chemical_paper(
            project,
            study_id,
            source_sha,
            archive,
            {
                "actor_type": "simulated_researcher_agent",
                "actor_label": "fixture-importer",
            },
        )
        correction_actor = (
            ("human_researcher", "simulated_researcher")
            if index == 3
            else ("simulated_researcher_agent", "fixture-chemical-reviewer")
        )
        expected_correction_actors.append(correction_actor)
        gate = chemical_completion_state(project, study_id)
        apply_chemical_completion_batch(
            project,
            study_id,
            {
                "version_token": gate["version_token"],
                "actor_type": correction_actor[0],
                "actor_label": correction_actor[1],
                "corrections": [
                    {
                        "molecule_index": 0,
                        "field": "resolved_smiles",
                        "value": None,
                        "resolution_status": "BLOCKED",
                        "gap_reason": "The synthetic PDF does not uniquely resolve the structure.",
                        "reason": "Preserve the unresolved structure as blocked.",
                        "pdf_locator": {"page": 1, "figure_label": "Figure 1"},
                    }
                ],
            },
        )

    # The legacy fixed-309 completion digest is project-wide, so derive every
    # downstream binding only after all three Chemical states are present.
    for study_id, _, _, _ in STUDIES:
        write_dual_source_binding(project, study_id)
        write_parse_reconciliation(project, study_id)

    for study_id, source_id, _, _ in STUDIES:
        registered = register_paper_evidence_candidates(
            project,
            study_id,
            {"candidates": [_candidate(study_id, source_id, index) for index in range(1, 4)]},
        )
        for row in registered["candidates"]:
            apply_paper_evidence_decision(
                project,
                {
                    "evidence_id": row["evidence_id"],
                    "candidate_digest": row["candidate_digest"],
                    "bound_parse_object_digests": row["bound_parse_object_digests"],
                    "source_pdf_sha256": row["source_pdf_sha256"],
                    "action": "approve",
                    "reason": "Checked against the synthetic source.",
                    "actor_type": evidence_actor[0],
                    "actor_label": evidence_actor[1],
                },
            )

    expected_trace = (
        strict_evidence_trace(project)["rows"]
        if evidence_actor[0] == "simulated_researcher_agent"
        else []
    )
    assert paper_evidence_state(project)["workflow_can_continue"] is True
    for key in ("corpus_kind", "variable_n", "study_count"):
        receipt.pop(key)
    _write_json(receipt_path, receipt)
    target = project.with_name("case-deliverable-first-a2")
    project.rename(target)
    return target, expected_trace, expected_correction_actors


def test_migration_rebinds_only_legacy_three_paper_trace_and_preserves_science(
    tmp_path: Path,
) -> None:
    project, expected_trace, expected_correction_actors = _legacy_three_paper_project(
        tmp_path
    )
    before = _snapshot(project)

    report = migrate_legacy_three_paper_project(
        project,
        expected_source_project_id="case",
    )

    evidence = paper_evidence_state(project)
    trace = strict_evidence_trace(project)
    assert report["status"] == "MIGRATED"
    assert report["study_count"] == 3
    assert report["evidence_count"] == 9
    assert report["strict_evidence_count"] == 9
    assert evidence["workflow_can_continue"] is True
    assert {row["status"] for row in evidence["rows"]} == {"approved"}
    assert trace["rows"] == expected_trace
    assert trace["trace_digest"] == canonical_digest(trace["rows"])
    assert all(row["document_role"] == "MAIN" for row in trace["rows"])
    assert all(len(row["source_pdf_sha256"]) == 64 for row in trace["rows"])
    assert all(row["page"] == 1 and row["section_or_item"] for row in trace["rows"])
    assert all(len(row["excerpt_hash"]) == 64 for row in trace["rows"])
    assert all(len(row["locator_hash"]) == 64 for row in trace["rows"])

    after = _snapshot(project)
    changed = sorted(
        relative
        for relative in set(before) | set(after)
        if before.get(relative) != after.get(relative)
    )
    assert changed == report["changed_paths"]
    assert set(changed) == {
        "00_sources/acquisition_final_receipt.json",
        "01_evidence/paper_evidence_decisions.jsonl",
        "01_evidence/paper_evidence_projection.jsonl",
        *{
            f"01_evidence/source_truth/{study_id}/bundle.json"
            for study_id, _, _, _ in STUDIES
        },
        *{
            f"01_evidence/source_truth/{study_id}/parse_quality.json"
            for study_id, _, _, _ in STUDIES
        },
        *{
            f"01_evidence/chemical_paper/{study_id}/state.json"
            for study_id, _, _, _ in STUDIES
        },
        *{
            f"01_evidence/dual_source/{study_id}/binding.json"
            for study_id, _, _, _ in STUDIES
        },
        *{
            f"01_evidence/parse_reconciliation/{study_id}/registry.json"
            for study_id, _, _, _ in STUDIES
        },
        *{
            f"01_evidence/{study_id}/paper_evidence_candidates.json"
            for study_id, _, _, _ in STUDIES
        },
    }
    observed_correction_actors = []
    for study_id, _, _, _ in STUDIES:
        state = _read_json(
            project / f"01_evidence/chemical_paper/{study_id}/state.json"
        )
        actor = state["field_corrections"][0]["actor"]
        observed_correction_actors.append((actor["actor_type"], actor["actor_label"]))
    assert observed_correction_actors == expected_correction_actors


def test_migration_dry_run_is_zero_write(tmp_path: Path) -> None:
    project, _, _ = _legacy_three_paper_project(tmp_path)
    before = _snapshot(project)

    report = migrate_legacy_three_paper_project(
        project,
        expected_source_project_id="case",
        dry_run=True,
    )

    assert report["status"] == "DRY_RUN_READY"
    assert report["evidence_count"] == 9
    assert _snapshot(project) == before


def test_migration_cli_reports_only_safe_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.project import main

    project, _, _ = _legacy_three_paper_project(tmp_path)
    before = _snapshot(project)

    assert (
        main(
            [
                "migrate-deliverable-first-legacy",
                "--project",
                str(project),
                "--expected-source-project-id",
                "case",
                "--dry-run",
            ]
        )
        == 0
    )

    report = json.loads(capsys.readouterr().out)
    assert set(report) == {
        "changed_paths",
        "evidence_count",
        "project_id",
        "reason_code",
        "source_project_id",
        "status",
        "strict_evidence_count",
        "strict_trace_digest",
        "study_count",
    }
    assert report["status"] == "DRY_RUN_READY"
    assert str(project) not in json.dumps(report)
    assert _snapshot(project) == before


def test_migration_rejects_human_local_evidence_chain_without_writes(
    tmp_path: Path,
) -> None:
    project, _, _ = _legacy_three_paper_project(
        tmp_path,
        evidence_actor=("human_researcher", "local-researcher"),
    )
    before = _snapshot(project)

    with pytest.raises(
        DeliverableFirstMigrationError,
        match="LEGACY_EVIDENCE_ACTOR_NOT_ELIGIBLE",
    ):
        migrate_legacy_three_paper_project(
            project,
            expected_source_project_id="case",
        )

    assert _snapshot(project) == before


@pytest.mark.parametrize(
    "marker",
    [
        {
            "corpus_kind": "authoritative_variable_n",
            "variable_n": True,
            "study_count": 3,
        },
        {"corpus_kind": "legacy_three_paper", "variable_n": True, "study_count": 3},
    ],
)
def test_migration_rejects_scaled_or_variable_n_marker_without_writes(
    tmp_path: Path,
    marker: dict[str, object],
) -> None:
    project, _, _ = _legacy_three_paper_project(tmp_path)
    receipt_path = project / "00_sources/acquisition_final_receipt.json"
    receipt = _read_json(receipt_path)
    receipt.update(marker)
    _write_json(receipt_path, receipt)
    before = _snapshot(project)

    with pytest.raises(
        DeliverableFirstMigrationError,
        match="LEGACY_THREE_PAPER_MARKER_NOT_ELIGIBLE",
    ):
        migrate_legacy_three_paper_project(
            project,
            expected_source_project_id="case",
        )

    assert _snapshot(project) == before


def _add_raw_required_si_authority_without_generic_sidecars(project: Path) -> None:
    """Add the real input-provenance shape while deliberately omitting SI parse edges."""

    receipt = _read_json(project / "00_sources/acquisition_final_receipt.json")
    manifest_studies = []
    registry_resources = []
    downloads = []
    for study_id, source_id, suffix, doi in STUDIES:
        payload = f"%PDF-1.7\nraw-SI-{suffix}\n%%EOF\n".encode()
        canonical = project / "00_sources/supplements/imported" / f"{source_id}.pdf"
        alias = project / "00_sources/supplements/imported" / f"{study_id}.si.pdf"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_bytes(payload)
        alias.write_bytes(payload)
        si_sha = hashlib.sha256(payload).hexdigest()
        si_path = canonical.relative_to(project).as_posix()
        alias_path = alias.relative_to(project / "00_sources").as_posix()
        receipt_row = next(
            row for row in receipt["studies"] if row["study_id"] == study_id
        )
        receipt_row["source_id"] = source_id
        main = receipt_row["main_pdf"]
        bundle = load_source_truth_bundle(project, study_id)
        manifest_studies.append(
            {
                "study_id": study_id,
                "source_id": source_id,
                "main_pdf": {
                    "sha256": main["sha256"],
                    "page_count": bundle["sources"][0]["page_count"],
                    "source_truth_bundle_digest": bundle["bundle_digest"],
                },
                "generic_parse": {
                    "status": "current",
                    "parse_gate_digest": _read_json(
                        project / f"01_evidence/source_truth/{study_id}/parse_quality.json"
                    )["gate_digest"],
                    "source_truth_bundle_digest": bundle["bundle_digest"],
                },
                "si": {
                    "path": si_path,
                    "sha256": si_sha,
                    "page_count": 1,
                    "size_bytes": len(payload),
                    "status": "current",
                },
                "chemical_zip": {
                    "sha256": "0" * 64,
                    "page_count": 1,
                    "status": "declared",
                },
            }
        )
        registry_resources.append(
            {
                "study_id": study_id,
                "source_id": source_id,
                "document_role": "SI",
                "main_pdf_sha256": main["sha256"],
                "path": si_path,
                "sha256": si_sha,
                "size_bytes": len(payload),
                "page_count": 1,
                "status": "CURRENT",
                "authority": "INPUT_PROVENANCE_ONLY",
            }
        )
        downloads.append(
            {
                "download_id": f"{source_id}-si",
                "study_id": study_id,
                "document_role": "SI",
                "target_path": alias_path,
                "expected_sha256": si_sha,
                "doi": doi,
                "archive_names": [f"{source_id}-si.pdf"],
            }
        )

    manifest_body = {
        "schema_version": "input-provenance-manifest.v1",
        "canonical_artifact": "00_sources/input_provenance_manifest.json",
        "project_id": "case",
        "manifest_digest": "1" * 64,
        "status": "CURRENT",
        "counts": {"main_pdf": 3, "si": 3, "chemical_zip": 3, "generic_parse": 3},
        "derived_refreshes": [
            {"study_id": study_id, "status": "blocked", "stage": "source_truth"}
            for study_id, _, _, _ in STUDIES
        ],
        "studies": manifest_studies,
    }
    _write_json(
        project / "00_sources/input_provenance_manifest.json",
        {**manifest_body, "artifact_digest": canonical_digest(manifest_body)},
    )
    _write_json(project / "00_sources/acquisition_final_receipt.json", receipt)

    registry_body = {
        "schema_version": "si-resource-registry.v1",
        "canonical_artifact": "00_sources/si_resource_registry.json",
        "project_id": "case",
        "core_si_required": True,
        "raw_scientific_authority": "CANDIDATE_ONLY",
        "human_chemical_review_required_for_scientific_use": True,
        "integration_status": "CURRENT",
        "manifest_digest": manifest_body["manifest_digest"],
        "resources": registry_resources,
    }
    _write_json(
        project / "00_sources/si_resource_registry.json",
        {**registry_body, "registry_digest": canonical_digest(registry_body)},
    )
    _write_json(
        project / "00_sources/supplements/source-bundle-2026-08-01/si_acquisition_manifest.json",
        {"schema_version": "public-corpus-acquisition.v1", "downloads": downloads},
    )
    acquisition_path = project / (
        "00_sources/supplements/source-bundle-2026-08-01/si_acquisition_manifest.json"
    )
    _write_json(
        project / "00_sources/manual_import_receipt.json",
        {
            "schema_version": "manual-archive-import-receipt.v1",
            "manifest_sha256": hashlib.sha256(acquisition_path.read_bytes()).hexdigest(),
            "results": [
                {
                    "study_id": study_id,
                    "document_role": "SI",
                    "download_id": f"{source_id}-si",
                    "status": "IMPORTED",
                    "target_path": f"supplements/imported/{study_id}.si.pdf",
                    "sha256": next(
                        row["sha256"] for row in registry_resources if row["study_id"] == study_id
                    ),
                    "size_bytes": next(
                        row["size_bytes"]
                        for row in registry_resources
                        if row["study_id"] == study_id
                    ),
                }
                for study_id, source_id, _, _ in STUDIES
            ],
            "unmatched_count": 1,
            "unresolved": [],
        },
    )

    coverage = _read_json(project / "00_sources/source_coverage.json")
    for row in coverage["studies"]:
        row.update(
            {
                "available_roles": ["MAIN", "SI"],
                "si_policy": "REQUIRED",
                "study_status": "READY",
            }
        )
    _write_json(project / "00_sources/source_coverage.json", coverage)


def _add_required_si_generic_sidecars(project: Path) -> None:
    mineru = _read_json(project / "01_evidence/mineru/manifest.json")
    parses = _read_json(project / "01_evidence/parses/manifest.json")
    text_layers = _read_json(
        project / "01_evidence/text_layers/text_layers.manifest.json"
    )
    for study_id, source_id, suffix, _ in STUDIES:
        slug = f"si-{source_id}"
        markdown = b"# Supplementary Information\n\n## References\n\nFixture reference.\n"
        markdown_path = project / f"01_evidence/mineru/markdown/{slug}.md"
        parse_markdown_path = project / f"01_evidence/parses/markdown/{slug}.md"
        _write_json(
            project / f"01_evidence/parses/extracted/{slug}/parse_content_list.json",
            [{"type": "text", "text": "Fixture", "page_idx": 0, "bbox": [1, 2, 3, 4]}],
        )
        _write_json(
            project
            / f"01_evidence/parses/extracted/{slug}/parse_content_list_v2.json",
            [[
                {
                    "type": "text",
                    "bbox": [1, 2, 3, 4],
                    "content": {"content": "Fixture"},
                }
            ]],
        )
        _write_json(
            project / f"01_evidence/parses/extracted/{slug}/layout.json",
            {"pages": [{"page_idx": 0}]},
        )
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_bytes(markdown)
        parse_markdown_path.parent.mkdir(parents=True, exist_ok=True)
        parse_markdown_path.write_bytes(markdown)
        full_markdown_path = (
            project / f"01_evidence/parses/extracted/{slug}/full.md"
        )
        full_markdown_path.write_bytes(markdown)
        raw_zip = project / f"01_evidence/mineru/raw_zips/{slug}.zip"
        raw_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(raw_zip, "w") as archive:
            archive.writestr("full.md", markdown)

        si_pdf = _read_json(project / "00_sources/input_provenance_manifest.json")
        si_row = next(row for row in si_pdf["studies"] if row["study_id"] == study_id)
        si_descriptor = si_row["si"]
        relative_pdf = si_descriptor["path"].removeprefix("00_sources/")
        mineru["completed"].append(
            {
                "data_id": f"si-{source_id}",
                "slug": slug,
                "state": "done",
                "relative_pdf_path": relative_pdf,
                "source_pdf_sha256": si_descriptor["sha256"],
                "markdown_copy": f"markdown/{slug}.md",
            }
        )
        parses["completed"].append(
            {
                "data_id": f"si-{source_id}",
                "slug": slug,
                "state": "done",
                "relative_pdf_path": relative_pdf,
                "source_pdf_sha256": si_descriptor["sha256"],
                "full_md": f"extracted/{slug}/full.md",
                "extracted_dir": f"extracted/{slug}",
                "markdown_copy": f"markdown/{slug}.md",
            }
        )
        reading = project / f"01_evidence/text_layers/{source_id}-si.reading.txt"
        layout = project / f"01_evidence/text_layers/{source_id}-si.layout.txt"
        reading.write_bytes(b"Fixture SI reading\f")
        layout.write_bytes(b"Fixture SI layout\f")
        text_layers["sources"].append(
            {
                "source_id": f"{source_id}-si",
                "pdf_name": f"{source_id}.pdf",
                "pdf_sha256": si_descriptor["sha256"],
                "page_count": si_descriptor["page_count"],
                "reading_order_path": reading.name,
                "reading_order_sha256": hashlib.sha256(reading.read_bytes()).hexdigest(),
                "layout_path": layout.name,
                "layout_sha256": hashlib.sha256(layout.read_bytes()).hexdigest(),
            }
        )
    _write_json(project / "01_evidence/mineru/manifest.json", mineru)
    _write_json(project / "01_evidence/parses/manifest.json", parses)
    _write_json(
        project / "01_evidence/text_layers/text_layers.manifest.json", text_layers
    )


def test_required_si_raw_authority_without_generic_sidecars_refuses_zero_write(
    tmp_path: Path,
) -> None:
    project, _, _ = _legacy_three_paper_project(tmp_path)
    _add_raw_required_si_authority_without_generic_sidecars(project)
    before = _snapshot(project)

    with pytest.raises(
        DeliverableFirstMigrationError,
        match="SI_GENERIC_BINDING_MISSING",
    ):
        migrate_legacy_three_paper_project(
            project,
            expected_source_project_id="case",
            dry_run=True,
        )

    assert _snapshot(project) == before


def test_required_si_malformed_counts_refuses_with_zero_write(tmp_path: Path) -> None:
    project, _, _ = _legacy_three_paper_project(tmp_path)
    _add_raw_required_si_authority_without_generic_sidecars(project)
    manifest_path = project / "00_sources/input_provenance_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["counts"] = "malformed"
    body = {key: value for key, value in manifest.items() if key != "artifact_digest"}
    manifest["artifact_digest"] = canonical_digest(body)
    _write_json(manifest_path, manifest)
    before = _snapshot(project)

    with pytest.raises(
        DeliverableFirstMigrationError,
        match="SI_AUTHORITY_INVALID",
    ):
        migrate_legacy_three_paper_project(
            project,
            expected_source_project_id="case",
            dry_run=True,
        )

    assert _snapshot(project) == before


def test_required_si_generic_hash_provenance_mismatch_refuses_zero_write(
    tmp_path: Path,
) -> None:
    project, _, _ = _legacy_three_paper_project(tmp_path)
    _add_raw_required_si_authority_without_generic_sidecars(project)
    _add_required_si_generic_sidecars(project)
    manifest_path = project / "01_evidence/mineru/manifest.json"
    manifest = _read_json(manifest_path)
    si_row = next(
        row
        for row in manifest["completed"]
        if row.get("relative_pdf_path", "").startswith("supplements/imported/")
    )
    si_row["source_pdf_sha256"] = "0" * 64
    _write_json(manifest_path, manifest)
    before = _snapshot(project)

    with pytest.raises(
        DeliverableFirstMigrationError,
        match="SI_GENERIC_BINDING_MISSING",
    ):
        migrate_legacy_three_paper_project(
            project,
            expected_source_project_id="case",
            dry_run=True,
        )

    assert _snapshot(project) == before


def test_required_si_complete_binding_reaches_dry_run_ready_without_writes(
    tmp_path: Path,
) -> None:
    project, _, _ = _legacy_three_paper_project(tmp_path)
    _add_raw_required_si_authority_without_generic_sidecars(project)
    _add_required_si_generic_sidecars(project)
    before = _snapshot(project)

    report = migrate_legacy_three_paper_project(
        project,
        expected_source_project_id="case",
        dry_run=True,
    )

    assert report["status"] == "DRY_RUN_READY"
    assert report["evidence_count"] == 9
    assert _snapshot(project) == before

    migrate_legacy_three_paper_project(
        project,
        expected_source_project_id="case",
    )
    receipt = _read_json(project / "00_sources/acquisition_final_receipt.json")
    assert all(isinstance(row.get("si_pdf"), dict) for row in receipt["studies"])
    for study_id, _, _, _ in STUDIES:
        bundle = load_source_truth_bundle(project, study_id)
        assert {row["document_role"] for row in bundle["sources"]} == {"MAIN", "SI"}
        gate = _read_json(
            project / f"01_evidence/source_truth/{study_id}/parse_quality.json"
        )
        assert gate["workflow_can_continue"] is True
        assert not any(
            issue["code"] == "supplement_missing"
            for row in gate["objects"]
            for issue in row["issues"]
        )

    receipt = _read_json(project / "00_sources/acquisition_final_receipt.json")
    input_manifest = _read_json(project / "00_sources/input_provenance_manifest.json")
    coverage = _read_json(project / "00_sources/source_coverage.json")
    mineru = _read_json(project / "01_evidence/mineru/manifest.json")
    text_layers = _read_json(
        project / "01_evidence/text_layers/text_layers.manifest.json"
    )
    input_by_study = {row["study_id"]: row for row in input_manifest["studies"]}
    coverage_by_study = {row["study_id"]: row for row in coverage["studies"]}
    for study_id, source_id, _, _ in STUDIES:
        receipt_row = next(row for row in receipt["studies"] if row["study_id"] == study_id)
        si = input_by_study[study_id]["si"]
        assert receipt_row["si_pdf"]["path"] == si["path"].removeprefix("00_sources/")
        assert receipt_row["si_pdf"]["sha256"] == si["sha256"]
        bundle = load_source_truth_bundle(project, study_id)
        si_source = next(row for row in bundle["sources"] if row["document_role"] == "SI")
        gate = _read_json(
            project / f"01_evidence/source_truth/{study_id}/parse_quality.json"
        )
        assert input_by_study[study_id]["main_pdf"]["source_truth_bundle_digest"] == bundle["bundle_digest"]
        assert input_by_study[study_id]["generic_parse"]["parse_gate_digest"] == gate["gate_digest"]
        assert coverage_by_study[study_id]["generic_parse"]["parse_gate_digest"] == gate["gate_digest"]
        assert si_source["pdf"]["sha256"] == si["sha256"]
        generic = next(
            row
            for row in mineru["completed"]
            if row.get("relative_pdf_path") == si["path"].removeprefix("00_sources/")
        )
        assert generic["source_pdf_sha256"] == si["sha256"]
        assert any(
            row["pdf_sha256"] == si["sha256"]
            and row["source_id"] == si_source["source_id"]
            for row in text_layers["sources"]
        )
