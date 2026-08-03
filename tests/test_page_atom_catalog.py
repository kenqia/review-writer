#!/usr/bin/env python3
"""Tests for deterministic locator-first page atom catalog construction."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.evidence.build_page_atom_catalog import PageCatalogError, build_page_atom_catalog
from scripts.evidence.evidence_atom_core import canonical_json_sha256


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SCRIPTS = REPO_ROOT / "scripts" / "evidence"
CATALOG_BUILDER = EVIDENCE_SCRIPTS / "build_page_atom_catalog.py"
CATALOG_SCHEMA = REPO_ROOT / "schemas" / "evidence" / "evidence_atom_catalog.v1.schema.json"
VISUAL_FIXTURE_ROOT = (
    REPO_ROOT / "tests" / "fixtures" / "evidence_atom_vertical_slice" / "packet"
)
VISUAL_JOB = VISUAL_FIXTURE_ROOT / "input" / "extraction_job.json"

READING_TEXT = (
    "First exact paragraph.\n\n"
    "Second paragraph with 82% yield.\f"
    "SI page text.\f"
)
LAYOUT_TEXT = "First visual page.\fSecond visual page.\f"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def make_bound_packet(tmp_path: Path) -> tuple[Path, Path, dict]:
    packet_root = tmp_path / "packet"
    sources = packet_root / "sources"
    sources.mkdir(parents=True)
    reading_path = sources / "MAIN.reading.txt"
    layout_path = sources / "MAIN.layout.txt"
    source_binary = sources / "MAIN.fakepdf"
    reading_path.write_text(READING_TEXT, encoding="utf-8")
    layout_path.write_text(LAYOUT_TEXT, encoding="utf-8")
    source_binary.write_bytes(b"synthetic source bytes\n")

    job = {
        "schema_version": "sealed-evidence-extraction-job.v2",
        "job_id": "PAGE-CATALOG-JOB",
        "mode": "EVIDENCE_ATOM_SEMANTIC_DECISION_V1",
        "study": {"study_id": "PAGE-CATALOG-STUDY"},
        "source_files": [
            {
                "source_id": "MAIN",
                "document_role": "MAIN",
                "source_binary_sha256": sha256_bytes(source_binary.read_bytes()),
                "reading_order_path": "sources/MAIN.reading.txt",
                "reading_order_sha256": sha256_bytes(reading_path.read_bytes()),
                "layout_path": "sources/MAIN.layout.txt",
                "layout_sha256": sha256_bytes(layout_path.read_bytes()),
                "page_count": 2,
                "visual_evidence_allowed": True,
            }
        ],
        "visual_crops": [],
    }
    job_path = packet_root / "input" / "extraction_job.json"
    write_json(job_path, job)
    return packet_root, job_path, job


def load_schema() -> dict:
    return json.loads(CATALOG_SCHEMA.read_text(encoding="utf-8"))


def without_hash(payload: dict, field: str) -> dict:
    return {key: value for key, value in payload.items() if key != field}


def test_builds_stable_page_local_text_atoms_and_atomic_cli_output(tmp_path: Path) -> None:
    packet_root, job_path, _ = make_bound_packet(tmp_path)
    schema = load_schema()

    assert list(inspect.signature(build_page_atom_catalog).parameters) == [
        "job_path",
        "packet_root",
    ]
    first = build_page_atom_catalog(job_path, packet_root)
    second = build_page_atom_catalog(job_path, packet_root)

    assert first == second
    Draft202012Validator(schema).validate(first)
    text_atoms = [atom for atom in first["atoms"] if atom["evidence_mode"] == "TEXT_QUOTE"]
    assert [atom["atom_id"] for atom in text_atoms] == [
        "MAIN:p1:t1",
        "MAIN:p1:t2",
        "MAIN:p2:t1",
    ]
    assert [atom["source_id"] for atom in text_atoms] == ["MAIN", "MAIN", "MAIN"]
    assert [atom["page"] for atom in text_atoms] == [1, 1, 2]
    assert text_atoms[1]["raw_source_span"] == "Second paragraph with 82% yield."
    assert text_atoms[1]["canonical_span"] == "Second paragraph with 82% yield."
    assert text_atoms[1]["asset_path"] is None
    assert text_atoms[1]["crop_manifest_path"] is None
    assert text_atoms[1]["r3_floor_categories"] == []
    for atom in text_atoms:
        assert atom["atom_sha256"] == canonical_json_sha256(without_hash(atom, "atom_sha256"))
    assert first["catalog_sha256"] == canonical_json_sha256(
        without_hash(first, "catalog_sha256")
    )

    output = tmp_path / "output" / "page-atoms.json"
    command = [
        sys.executable,
        str(CATALOG_BUILDER),
        "--job",
        str(job_path),
        "--packet-root",
        str(packet_root),
        "--schema",
        str(CATALOG_SCHEMA),
        "--output",
        str(output),
    ]
    first_run = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    assert first_run.returncode == 0, first_run.stderr
    first_bytes = output.read_bytes()
    second_run = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    assert second_run.returncode == 0, second_run.stderr
    assert output.read_bytes() == first_bytes
    assert json.loads(first_bytes.decode("utf-8")) == first
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_rejects_hash_mismatch_unbound_visual_and_cross_page_jobs(tmp_path: Path) -> None:
    packet_root, _, valid_job = make_bound_packet(tmp_path)

    invalid_jobs = []
    hash_mismatch = copy.deepcopy(valid_job)
    hash_mismatch["source_files"][0]["reading_order_sha256"] = "0" * 64
    invalid_jobs.append((hash_mismatch, "SOURCE_LAYER_HASH_MISMATCH"))

    unbound_visual = copy.deepcopy(valid_job)
    unbound_visual["visual_crops"] = [
        {
            "source_id": "UNBOUND",
            "page": 1,
            "manifest_path": "input/crops/unbound.json",
            "manifest_sha256": "0" * 64,
        }
    ]
    invalid_jobs.append((unbound_visual, "VISUAL_SOURCE_UNBOUND"))

    cross_page = copy.deepcopy(valid_job)
    cross_page["source_files"][0]["page_count"] = 1
    invalid_jobs.append((cross_page, "SOURCE_PAGE_COUNT_MISMATCH"))

    for index, (invalid_job, expected_code) in enumerate(invalid_jobs, start=1):
        invalid_path = packet_root / "input" / f"invalid-{index}.json"
        write_json(invalid_path, invalid_job)
        try:
            build_page_atom_catalog(invalid_path, packet_root)
        except PageCatalogError as exc:
            assert exc.code == expected_code
        else:
            raise AssertionError(f"invalid job unexpectedly accepted: {expected_code}")


def test_rejects_hash_bound_layout_page_count_mismatch(tmp_path: Path) -> None:
    packet_root, _, job = make_bound_packet(tmp_path)
    layout_path = packet_root / job["source_files"][0]["layout_path"]
    layout_path.write_text("Only one visual page.\f", encoding="utf-8")
    job["source_files"][0]["layout_sha256"] = sha256_bytes(layout_path.read_bytes())
    invalid_path = packet_root / "input" / "layout-page-count-mismatch.json"
    write_json(invalid_path, job)

    try:
        build_page_atom_catalog(invalid_path, packet_root)
    except PageCatalogError as exc:
        assert exc.code == "SOURCE_PAGE_COUNT_MISMATCH"
    else:
        raise AssertionError("hash-bound one-page layout unexpectedly accepted for a two-page source")


def test_visual_atom_is_derived_only_from_hash_bound_job_and_manifest() -> None:
    catalog = build_page_atom_catalog(VISUAL_JOB, VISUAL_FIXTURE_ROOT)
    visual_atoms = [
        atom for atom in catalog["atoms"] if atom["evidence_mode"] == "FIGURE_TABLE_IMAGE"
    ]

    assert len(visual_atoms) == 1
    visual = visual_atoms[0]
    declaration = json.loads(VISUAL_JOB.read_text(encoding="utf-8"))["visual_crops"][0]
    manifest_path = VISUAL_FIXTURE_ROOT / declaration["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert visual["atom_id"] == "SYNTH_MAIN:p1:v1"
    assert visual["source_id"] == declaration["source_id"] == manifest["source_id"]
    assert visual["page"] == declaration["page"] == manifest["page"]
    assert visual["asset_path"] == manifest["asset_path"]
    assert visual["asset_sha256"] == manifest["asset_sha256"]
    assert visual["crop_manifest_path"] == declaration["manifest_path"]
    assert visual["crop_manifest_sha256"] == declaration["manifest_sha256"]
    assert visual["source_binary_sha256"] == manifest["source_binary_sha256"]
    assert visual["renderer_contract"] == manifest["renderer_contract"]
    assert visual["renderer_sha256"] == manifest["renderer_sha256"]
    assert visual["r3_floor_categories"] == ["FIGURE_TABLE_CHEMISTRY"]
    assert visual["raw_source_span"] is None
    assert visual["canonical_span"] is None
    assert visual["atom_sha256"] == canonical_json_sha256(without_hash(visual, "atom_sha256"))
