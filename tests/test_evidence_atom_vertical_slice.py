#!/usr/bin/env python3
"""Synthetic-only tests for the bounded evidence-atom vertical slice."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "evidence"))

from assemble_evidence_candidate_from_atoms import assemble  # noqa: E402
from evidence_atom_core import canonical_json_sha256, canonicalize_text  # noqa: E402


FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "evidence_atom_vertical_slice" / "packet"
FAKE_RENDERER = (
    REPO_ROOT / "tests" / "fixtures" / "evidence_atom_vertical_slice" / "fake_pdftoppm.py"
)
SOURCE_PLACEHOLDER = FIXTURE_ROOT / "sources" / "SYNTH_MAIN.fakepdf"
CROP_MANIFEST = FIXTURE_ROOT / "input" / "crops" / "SYNTH_MAIN.page-1.crop-manifest.json"
CROP_RENDERER = REPO_ROOT / "scripts" / "evidence" / "render_evidence_page_crop.py"
JOB = FIXTURE_ROOT / "input" / "extraction_job.json"
VALID_SELECTION = FIXTURE_ROOT / "input" / "selection.valid.json"
ATOM_BUILDER = REPO_ROOT / "scripts" / "evidence" / "build_evidence_atoms.py"
ATOM_SCHEMA = REPO_ROOT / "schemas" / "evidence" / "evidence_atom_catalog.v1.schema.json"
ASSEMBLER = REPO_ROOT / "scripts" / "evidence" / "assemble_evidence_candidate_from_atoms.py"
SEMANTIC_SCHEMA = (
    REPO_ROOT / "schemas" / "evidence" / "evidence_atom_semantic_decision.v1.schema.json"
)
CANDIDATE_SCHEMA = REPO_ROOT / "schemas" / "evidence" / "evidence_candidate.v2.schema.json"
VALIDATOR = REPO_ROOT / "scripts" / "evidence" / "validate_evidence_candidate.py"
VALID_SEMANTIC = FIXTURE_ROOT / "input" / "semantic.valid.json"
SEMANTIC_TEMPLATE = (
    REPO_ROOT / "templates" / "evidence" / "evidence_atom_semantic_decision.v1.template.json"
)


def rehash_catalog(catalog: dict) -> None:
    for atom in catalog["atoms"]:
        atom["atom_sha256"] = canonical_json_sha256(
            {key: value for key, value in atom.items() if key != "atom_sha256"}
        )
    catalog["catalog_sha256"] = canonical_json_sha256(
        {key: value for key, value in catalog.items() if key != "catalog_sha256"}
    )


def render_fake_page(source_pdf: Path, page: int, asset: Path) -> subprocess.CompletedProcess[str]:
    asset.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            str(FAKE_RENDERER),
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            "144",
            "-png",
            "-singlefile",
            str(source_pdf),
            str(asset.with_suffix("")),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


class EvidenceAtomBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.selection = json.loads(VALID_SELECTION.read_text(encoding="utf-8"))

    def run_builder(self, selection: dict) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selection_path = root / "selection.json"
            output_path = root / "catalog.json"
            selection_path.write_text(
                json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ATOM_BUILDER),
                    "--job",
                    str(JOB),
                    "--selection",
                    str(selection_path),
                    "--packet-root",
                    str(FIXTURE_ROOT),
                    "--schema",
                    str(ATOM_SCHEMA),
                    "--output",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else {}
        return result, payload

    def one_text_selection(self, raw_source_span: str, *, page: int = 1) -> dict:
        selection = copy.deepcopy(self.selection)
        selection["atoms"] = [
            {
                "atom_id": "ATOM-TEST",
                "source_id": "SYNTH_MAIN",
                "page": page,
                "evidence_mode": "TEXT_QUOTE",
                "raw_source_span": raw_source_span,
            }
        ]
        return selection

    def test_builder_emits_page_local_text_and_independent_visual_atoms(self) -> None:
        result, catalog = self.run_builder(self.selection)
        self.assertEqual(0, result.returncode, result.stderr)
        atoms = {atom["atom_id"]: atom for atom in catalog["atoms"]}
        self.assertEqual(
            "The catalyst afforded product 2a in 91% yield.",
            atoms["ATOM-WHITESPACE"]["canonical_span"],
        )
        self.assertEqual(
            'The first "Cu-O" complex was CuSO4·5H2O.',
            atoms["ATOM-UNICODE"]["canonical_span"],
        )
        self.assertEqual(
            "The transformation was stereoselective and retained alpha-beta.",
            atoms["ATOM-SOFT-HYPHEN"]["canonical_span"],
        )
        self.assertEqual(
            "A • bullet remains a prose bullet.",
            atoms["ATOM-PROSE-BULLET"]["canonical_span"],
        )
        visual = atoms["ATOM-VISUAL"]
        self.assertEqual("FIGURE_TABLE_IMAGE", visual["evidence_mode"])
        self.assertIsNone(visual["raw_source_span"])
        self.assertIsNone(visual["canonical_span"])
        self.assertEqual("assets/page-1-crop.png", visual["asset_path"])
        self.assertEqual(
            hashlib.sha256((FIXTURE_ROOT / visual["asset_path"]).read_bytes()).hexdigest(),
            visual["asset_sha256"],
        )
        self.assertEqual(["FIGURE_TABLE_CHEMISTRY"], visual["r3_floor_categories"])
        self.assertEqual(
            ["MECHANISM_CAUSALITY", "NEGATIVE_GENERALIZATION"],
            atoms["ATOM-UNICODE"]["r3_floor_categories"],
        )
        self.assertEqual(
            "input/crops/SYNTH_MAIN.page-1.crop-manifest.json",
            visual["crop_manifest_path"],
        )
        self.assertEqual(len(atoms), len({atom["atom_sha256"] for atom in atoms.values()}))

    def test_fixed_single_page_crop_step_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            packet_root = Path(temp_dir) / "packet"
            manifest = packet_root / "input" / "crops" / CROP_MANIFEST.name
            command = [
                sys.executable,
                str(CROP_RENDERER),
                "--source-id",
                "SYNTH_MAIN",
                "--source-pdf",
                str(SOURCE_PLACEHOLDER),
                "--page",
                "1",
                "--renderer",
                str(FAKE_RENDERER),
                "--packet-root",
                str(packet_root),
                "--asset-path",
                "assets/page-1-crop.png",
                "--manifest-output",
                str(manifest),
            ]
            first = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(0, first.returncode, first.stderr)
            first_asset = (packet_root / "assets" / "page-1-crop.png").read_bytes()
            first_manifest = manifest.read_bytes()
            second = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(first_asset, (packet_root / "assets" / "page-1-crop.png").read_bytes())
            self.assertEqual(first_manifest, manifest.read_bytes())
            self.assertEqual((FIXTURE_ROOT / "assets" / "page-1-crop.png").read_bytes(), first_asset)
            self.assertEqual(CROP_MANIFEST.read_bytes(), first_manifest)
            manifest_payload = json.loads(first_manifest.decode("utf-8"))
            self.assertEqual("png", manifest_payload["renderer_contract"]["format"])
            self.assertEqual("assets/page-1-crop.png", manifest_payload["asset_path"])

    def test_renderer_source_fixture_is_not_ignored(self) -> None:
        relative = SOURCE_PLACEHOLDER.relative_to(REPO_ROOT).as_posix()
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--", relative],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, ignored.returncode, f"fixture is ignored: {relative}")

    def test_changed_word_number_or_chemical_entity_is_rejected(self) -> None:
        for invalid_span in (
            "The catalyst afforded product 2b in 91% yield.",
            "The catalyst afforded product 2a in 92% yield.",
            "The first CuCl complex was isolated.",
        ):
            with self.subTest(invalid_span=invalid_span):
                result, _ = self.run_builder(self.one_text_selection(invalid_span))
                self.assertEqual(1, result.returncode)
                self.assertIn("TEXT_SPAN_NOT_CONTIGUOUS_ON_PAGE", result.stderr)

    def test_wrong_page_cross_page_and_non_contiguous_splices_are_rejected(self) -> None:
        cases = (
            self.one_text_selection("The catalyst\nafforded product 2a in 91% yield.", page=2),
            self.one_text_selection("End of page one.Start of page two."),
            self.one_text_selection("alpha omega"),
        )
        for selection in cases:
            with self.subTest(selection=selection):
                result, _ = self.run_builder(selection)
                self.assertEqual(1, result.returncode)
                self.assertIn("TEXT_SPAN_NOT_CONTIGUOUS_ON_PAGE", result.stderr)

    def test_visual_asset_hash_drift_is_rejected(self) -> None:
        selection = copy.deepcopy(self.selection)
        selection["atoms"] = [copy.deepcopy(selection["atoms"][-1])]
        selection["atoms"][0]["crop_manifest_path"] = "input/crops/missing.json"
        result, _ = self.run_builder(selection)
        self.assertEqual(1, result.returncode)
        self.assertIn("VISUAL_MANIFEST_JOB_MISMATCH", result.stderr)

    def test_chemical_middle_dot_glyph_rule_is_bounded_and_reproducible(self) -> None:
        for glyph in ("*", "\u2022", "\u2219", "\u22c5"):
            self.assertEqual("CuSO4\u00b75H2O", canonicalize_text(f"CuSO4{glyph}5H2O"))
            self.assertEqual(f"A {glyph} bullet", canonicalize_text(f"A {glyph} bullet"))
        synthetic_spans = [f"Salt{i}*5H2O" for i in range(22)] + [
            f"Item {i} * bullet" for i in range(9)
        ]
        changed = sum(canonicalize_text(value) != value for value in synthetic_spans)
        self.assertEqual(22, changed)

    def test_semantic_schema_requires_explicit_risk_classification(self) -> None:
        schema = json.loads(SEMANTIC_SCHEMA.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        semantic = json.loads(VALID_SEMANTIC.read_text(encoding="utf-8"))
        self.assertEqual([], list(validator.iter_errors(semantic)))

        missing_classification = copy.deepcopy(semantic)
        missing_classification["decisions"][1].pop("risk_classification")
        self.assertNotEqual([], list(validator.iter_errors(missing_classification)))

        missing_categories = copy.deepcopy(semantic)
        missing_categories["decisions"][1].pop("semantic_risk_categories")
        self.assertNotEqual([], list(validator.iter_errors(missing_categories)))


class EvidenceAtomAssemblerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.semantic = json.loads(VALID_SEMANTIC.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "catalog.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ATOM_BUILDER),
                    "--job",
                    str(JOB),
                    "--selection",
                    str(VALID_SELECTION),
                    "--packet-root",
                    str(FIXTURE_ROOT),
                    "--schema",
                    str(ATOM_SCHEMA),
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                raise AssertionError(result.stderr)
            cls.catalog = json.loads(output.read_text(encoding="utf-8"))

    def run_assembler(
        self,
        catalog: dict,
        semantic: dict,
        *,
        packet_root: Path = FIXTURE_ROOT,
        job_path: Path = JOB,
        source_pdf: Path = SOURCE_PLACEHOLDER,
    ) -> tuple[subprocess.CompletedProcess[str], dict, subprocess.CompletedProcess[str] | None]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog_path = root / "catalog.json"
            semantic_path = root / "semantic.json"
            candidate_path = root / "candidate.json"
            report_path = root / "validator-report.json"
            catalog_path.write_text(
                json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            semantic_path.write_text(
                json.dumps(semantic, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ASSEMBLER),
                    "--job",
                    str(job_path),
                    "--packet-root",
                    str(packet_root),
                    "--catalog",
                    str(catalog_path),
                    "--semantic",
                    str(semantic_path),
                    "--catalog-schema",
                    str(ATOM_SCHEMA),
                    "--semantic-schema",
                    str(SEMANTIC_SCHEMA),
                    "--candidate-schema",
                    str(CANDIDATE_SCHEMA),
                    "--source-pdf",
                    f"SYNTH_MAIN={source_pdf}",
                    "--renderer",
                    str(FAKE_RENDERER),
                    "--output",
                    str(candidate_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            candidate = json.loads(candidate_path.read_text(encoding="utf-8")) if candidate_path.exists() else {}
            validator_result = None
            if candidate_path.exists():
                validator_result = subprocess.run(
                    [
                        sys.executable,
                        str(VALIDATOR),
                        "--job",
                        str(job_path),
                        "--candidate",
                        str(candidate_path),
                        "--packet-root",
                        str(packet_root),
                        "--schema",
                        str(CANDIDATE_SCHEMA),
                        "--report-json",
                        str(report_path),
                    ],
                    cwd=REPO_ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
        return result, candidate, validator_result

    def test_cli_rejects_stale_job_binding_before_reading_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job = json.loads(JOB.read_text(encoding="utf-8"))
            job["source_files"][0]["source_binary_sha256"] = "0" * 64
            job_path = root / "job.json"
            catalog_path = root / "catalog.json"
            semantic_path = root / "semantic.json"
            job_path.write_text(json.dumps(job) + "\n", encoding="utf-8")
            catalog_path.write_text(json.dumps(self.catalog) + "\n", encoding="utf-8")
            semantic_path.write_text("not-json\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ASSEMBLER),
                    "--job",
                    str(job_path),
                    "--packet-root",
                    str(FIXTURE_ROOT),
                    "--catalog",
                    str(catalog_path),
                    "--semantic",
                    str(semantic_path),
                    "--catalog-schema",
                    str(ATOM_SCHEMA),
                    "--semantic-schema",
                    str(SEMANTIC_SCHEMA),
                    "--candidate-schema",
                    str(CANDIDATE_SCHEMA),
                    "--output",
                    str(root / "candidate.json"),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("JOB_BINDING_INVALID", result.stderr)

    def assert_assembly_rejected(self, catalog: dict, semantic: dict, code: str) -> None:
        result, candidate, _ = self.run_assembler(catalog, semantic)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual({}, candidate)
        self.assertIn(code, result.stderr)

    def test_assembler_restores_grounding_and_passes_existing_validator(self) -> None:
        result, candidate, validator_result = self.run_assembler(self.catalog, self.semantic)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIsNotNone(validator_result)
        self.assertEqual(0, validator_result.returncode, validator_result.stderr)
        self.assertEqual("evidence-candidate.v2", candidate["schema_version"])
        visual_unit = candidate["reaction_units"][0]
        self.assertEqual("R3", visual_unit["risk_level"])
        self.assertIn("FIGURE_TABLE_CHEMISTRY", visual_unit["risk_categories"])
        visual_ref = visual_unit["evidence_refs"][0]
        self.assertIsNone(visual_ref["exact_quote"])
        self.assertEqual(["R3_SOURCE_DEPICTION_REQUIRED"], visual_ref["r3_flags"])
        self.assertEqual(["synthetic product label", "91% yield"], visual_ref["transcribed_values"])
        claim = candidate["claims"][0]
        self.assertEqual("RU-VISUAL", candidate["anchor_reaction_unit_id"])
        self.assertEqual("RU-VISUAL", visual_unit["reaction_unit_id"])
        self.assertEqual("CL-HIGH-RISK", claim["claim_id"])
        self.assertEqual("R3", claim["risk_level"])
        self.assertEqual(
            {
                "STRUCTURE",
                "STEREOCHEMISTRY",
                "MECHANISM_CAUSALITY",
                "NEGATIVE_GENERALIZATION",
                "MATERIAL_COMPARISON",
                "FIGURE_TABLE_CHEMISTRY",
            },
            set(claim["risk_categories"]),
        )
        mappings = {item["target_id"]: item for item in candidate["r3_review_items"]}
        self.assertTrue(set(claim["risk_categories"]).issubset(mappings["CL-HIGH-RISK"]["risk_categories"]))
        self.assertEqual(3, candidate["source_coverage"]["SYNTH_MAIN"]["evidence_ref_count"])

    def test_study_namespace_maps_local_target_ids_without_mutating_semantic_input(self) -> None:
        def assembled(study_id: str) -> tuple[dict, dict]:
            namespace = "study-" + hashlib.sha256(study_id.encode("utf-8")).hexdigest()
            job = {
                "job_id": f"JOB-{study_id}",
                "study": {"study_id": study_id},
                "target_namespace": namespace,
                "source_files": [{"source_id": "SOURCE"}],
            }
            semantic = {
                "job_id": job["job_id"],
                "study_id": study_id,
                "eligibility_status": "SCIENTIFICALLY_ELIGIBLE_CORE",
                "decisions": [
                    {
                        "target_kind": "ELIGIBILITY",
                        "target_id": "eligibility",
                        "statement": "Eligible.",
                        "evidence_summary": "Eligibility evidence.",
                        "atom_ids": ["atom-eligibility"],
                    },
                    {
                        "target_kind": "REACTION_UNIT",
                        "target_id": "reaction-unit-01",
                        "statement": "Local reaction unit.",
                        "evidence_summary": "Reaction evidence.",
                        "atom_ids": ["atom-reaction"],
                    },
                    {
                        "target_kind": "CLAIM",
                        "target_id": "claim-01",
                        "statement": "Local claim.",
                        "evidence_summary": "Claim evidence.",
                        "atom_ids": ["atom-claim"],
                        "semantic_risk_categories": ["MECHANISM_CAUSALITY"],
                    },
                ],
            }
            atoms = {
                atom_id: {
                    "atom_id": atom_id,
                    "source_id": "SOURCE",
                    "page": 1,
                    "evidence_mode": "TEXT_QUOTE",
                    "raw_source_span": f"Source text for {atom_id}.",
                    "r3_floor_categories": [],
                }
                for atom_id in ("atom-eligibility", "atom-reaction", "atom-claim")
            }
            semantic_before = copy.deepcopy(semantic)

            candidate = assemble(job, {}, semantic, atoms)

            self.assertEqual(semantic_before, semantic)
            return candidate, semantic

        first, first_semantic = assembled("STUDY-A")
        second, second_semantic = assembled("STUDY-B")

        first_namespace = "study-" + hashlib.sha256(b"STUDY-A").hexdigest()
        second_namespace = "study-" + hashlib.sha256(b"STUDY-B").hexdigest()
        self.assertEqual(
            f"{first_namespace}:reaction-unit-01",
            first["reaction_units"][0]["reaction_unit_id"],
        )
        self.assertEqual(
            first["reaction_units"][0]["reaction_unit_id"],
            first["anchor_reaction_unit_id"],
        )
        self.assertEqual(f"{first_namespace}:claim-01", first["claims"][0]["claim_id"])
        self.assertEqual(
            f"{first_namespace}:claim-01",
            first["r3_review_items"][0]["target_id"],
        )
        self.assertEqual(f"{second_namespace}:claim-01", second["claims"][0]["claim_id"])
        self.assertNotEqual(first["claims"][0]["claim_id"], second["claims"][0]["claim_id"])
        self.assertEqual("claim-01", first_semantic["decisions"][2]["target_id"])
        self.assertEqual("claim-01", second_semantic["decisions"][2]["target_id"])

    def test_unknown_duplicate_and_hash_drift_atoms_are_rejected(self) -> None:
        semantic = copy.deepcopy(self.semantic)
        semantic["decisions"][0]["atom_ids"] = ["ATOM-UNKNOWN"]
        self.assert_assembly_rejected(self.catalog, semantic, "UNKNOWN_ATOM_ID")

        catalog = copy.deepcopy(self.catalog)
        catalog["atoms"].append(copy.deepcopy(catalog["atoms"][0]))
        self.assert_assembly_rejected(catalog, self.semantic, "DUPLICATE_ATOM_ID")

        catalog = copy.deepcopy(self.catalog)
        catalog["atoms"][0]["canonical_span"] = "drift"
        self.assert_assembly_rejected(catalog, self.semantic, "ATOM_HASH_MISMATCH")

        catalog = copy.deepcopy(self.catalog)
        catalog["atoms"].pop()
        self.assert_assembly_rejected(catalog, self.semantic, "CATALOG_HASH_MISMATCH")

        semantic = copy.deepcopy(self.semantic)
        semantic["decisions"][1]["atom_ids"] = ["ATOM-WHITESPACE"]
        semantic["decisions"][1].pop("visual_transcribed_values")
        self.assert_assembly_rejected(self.catalog, semantic, "DUPLICATE_ATOM_CONSUMPTION")

    def test_assembler_revalidates_text_atoms_against_bound_source_layers(self) -> None:
        cases = []

        raw_drift = copy.deepcopy(self.catalog)
        raw_drift["atoms"][0]["raw_source_span"] = "fabricated source text"
        raw_drift["atoms"][0]["canonical_span"] = "fabricated source text"
        cases.append((raw_drift, "ATOM_TEXT_NOT_CONTIGUOUS_ON_PAGE"))

        page_drift = copy.deepcopy(self.catalog)
        page_drift["atoms"][0]["page"] = 2
        cases.append((page_drift, "ATOM_TEXT_NOT_CONTIGUOUS_ON_PAGE"))

        source_drift = copy.deepcopy(self.catalog)
        source_drift["atoms"][0]["source_id"] = "UNKNOWN_SOURCE"
        cases.append((source_drift, "ATOM_SOURCE_UNKNOWN"))

        canonical_drift = copy.deepcopy(self.catalog)
        canonical_drift["atoms"][0]["canonical_span"] = "wrong canonical form"
        cases.append((canonical_drift, "ATOM_CANONICAL_MISMATCH"))

        for catalog, code in cases:
            with self.subTest(code=code):
                rehash_catalog(catalog)
                self.assert_assembly_rejected(catalog, self.semantic, code)

    def test_assembler_revalidates_source_layer_hashes_and_page_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            packet_root = Path(temp_dir) / "packet"
            shutil.copytree(FIXTURE_ROOT, packet_root)
            reading = packet_root / "sources" / "SYNTH_MAIN.reading.txt"
            reading.write_text(reading.read_text(encoding="utf-8") + "drift", encoding="utf-8")
            result, candidate, _ = self.run_assembler(
                self.catalog,
                self.semantic,
                packet_root=packet_root,
                job_path=packet_root / "input" / "extraction_job.json",
                source_pdf=packet_root / "sources" / "SYNTH_MAIN.fakepdf",
            )
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertEqual({}, candidate)
            self.assertIn("SOURCE_LAYER_HASH_MISMATCH", result.stderr)

        with tempfile.TemporaryDirectory() as temp_dir:
            packet_root = Path(temp_dir) / "packet"
            shutil.copytree(FIXTURE_ROOT, packet_root)
            job_path = packet_root / "input" / "extraction_job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["source_files"][0]["page_count"] = 3
            job_path.write_text(
                json.dumps(job, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            catalog = copy.deepcopy(self.catalog)
            catalog["job_sha256"] = hashlib.sha256(job_path.read_bytes()).hexdigest()
            rehash_catalog(catalog)
            result, candidate, _ = self.run_assembler(
                catalog,
                self.semantic,
                packet_root=packet_root,
                job_path=job_path,
                source_pdf=packet_root / "sources" / "SYNTH_MAIN.fakepdf",
            )
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertEqual({}, candidate)
            self.assertIn("SOURCE_PAGE_COUNT_MISMATCH", result.stderr)

    def test_visual_page_and_manifest_rewrite_cannot_bypass_job_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            packet_root = Path(temp_dir) / "packet"
            shutil.copytree(FIXTURE_ROOT, packet_root)
            manifest_path = packet_root / "input" / "crops" / CROP_MANIFEST.name
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["page"] = 2
            manifest["asset_path"] = "assets/page-2-crop.png"
            page_two_asset = packet_root / manifest["asset_path"]
            rendered = render_fake_page(
                packet_root / "sources" / "SYNTH_MAIN.fakepdf",
                2,
                page_two_asset,
            )
            self.assertEqual(0, rendered.returncode, rendered.stderr)
            manifest["asset_sha256"] = hashlib.sha256(page_two_asset.read_bytes()).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            catalog = copy.deepcopy(self.catalog)
            visual = next(atom for atom in catalog["atoms"] if atom["evidence_mode"] == "FIGURE_TABLE_IMAGE")
            visual["page"] = 2
            visual["asset_path"] = manifest["asset_path"]
            visual["asset_sha256"] = manifest["asset_sha256"]
            visual["crop_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            rehash_catalog(catalog)
            result, candidate, _ = self.run_assembler(
                catalog,
                self.semantic,
                packet_root=packet_root,
                job_path=packet_root / "input" / "extraction_job.json",
                source_pdf=packet_root / "sources" / "SYNTH_MAIN.fakepdf",
            )
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertEqual({}, candidate)
            self.assertIn("VISUAL_MANIFEST_JOB_MISMATCH", result.stderr)

    def test_visual_crop_rewrite_cannot_bypass_local_pdf_rerender(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            packet_root = Path(temp_dir) / "packet"
            shutil.copytree(FIXTURE_ROOT, packet_root)
            asset = packet_root / "assets" / "page-1-crop.png"
            rendered = render_fake_page(
                packet_root / "sources" / "SYNTH_MAIN.fakepdf",
                2,
                asset,
            )
            self.assertEqual(0, rendered.returncode, rendered.stderr)
            asset_hash = hashlib.sha256(asset.read_bytes()).hexdigest()

            manifest_path = packet_root / "input" / "crops" / CROP_MANIFEST.name
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["asset_sha256"] = asset_hash
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

            job_path = packet_root / "input" / "extraction_job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["visual_crops"][0]["manifest_sha256"] = manifest_hash
            job_path.write_text(
                json.dumps(job, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            catalog = copy.deepcopy(self.catalog)
            catalog["job_sha256"] = hashlib.sha256(job_path.read_bytes()).hexdigest()
            visual = next(atom for atom in catalog["atoms"] if atom["evidence_mode"] == "FIGURE_TABLE_IMAGE")
            visual["asset_sha256"] = asset_hash
            visual["crop_manifest_sha256"] = manifest_hash
            rehash_catalog(catalog)
            result, candidate, _ = self.run_assembler(
                catalog,
                self.semantic,
                packet_root=packet_root,
                job_path=job_path,
                source_pdf=packet_root / "sources" / "SYNTH_MAIN.fakepdf",
            )
            self.assertEqual(1, result.returncode, result.stderr)
            self.assertEqual({}, candidate)
            self.assertIn("VISUAL_RERENDER_HASH_MISMATCH", result.stderr)

    def test_semantic_schema_forbids_mechanical_grounding_fields_and_defaults(self) -> None:
        for forbidden_key, value in (
            ("source_id", "SYNTH_MAIN"),
            ("page", 1),
            ("exact_quote", "not allowed"),
            ("depiction_locator", "not allowed"),
            ("source_coverage", {}),
            ("coverage", []),
            ("r3_flags", []),
            ("transcribed_values", []),
        ):
            semantic = copy.deepcopy(self.semantic)
            semantic["decisions"][0][forbidden_key] = value
            with self.subTest(forbidden_key=forbidden_key):
                self.assert_assembly_rejected(self.catalog, semantic, "SEMANTIC_SCHEMA_INVALID")

        semantic = copy.deepcopy(self.semantic)
        semantic["self_check"] = {"read_all": True}
        self.assert_assembly_rejected(self.catalog, semantic, "SEMANTIC_SCHEMA_INVALID")

        semantic = copy.deepcopy(self.semantic)
        semantic["decisions"][1].pop("risk_classification")
        self.assert_assembly_rejected(self.catalog, semantic, "SEMANTIC_SCHEMA_INVALID")

        semantic = copy.deepcopy(self.semantic)
        semantic["decisions"][1].pop("semantic_risk_categories")
        self.assert_assembly_rejected(self.catalog, semantic, "SEMANTIC_SCHEMA_INVALID")

    def test_atom_r3_floor_cannot_be_lowered_by_semantic_omission(self) -> None:
        semantic = copy.deepcopy(self.semantic)
        claim = semantic["decisions"][2]
        claim["risk_classification"] = "NO_HIGH_RISK"
        claim.pop("semantic_risk_categories")
        result, candidate, validator_result = self.run_assembler(self.catalog, semantic)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIsNotNone(validator_result)
        self.assertEqual(0, validator_result.returncode, validator_result.stderr)
        output_claim = candidate["claims"][0]
        self.assertEqual("R3", output_claim["risk_level"])
        self.assertEqual(
            {"MECHANISM_CAUSALITY", "NEGATIVE_GENERALIZATION"},
            set(output_claim["risk_categories"]),
        )

    def test_template_and_generic_make_gate_keep_the_slice_bounded(self) -> None:
        semantic_schema = json.loads(SEMANTIC_SCHEMA.read_text(encoding="utf-8"))
        template = json.loads(SEMANTIC_TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual([], list(Draft202012Validator(semantic_schema).iter_errors(template)))
        self.assertEqual(
            {"ELIGIBILITY", "REACTION_UNIT", "CLAIM"},
            {decision["target_kind"] for decision in template["decisions"]},
        )
        self.assertTrue(all("risk_classification" in item for item in template["decisions"]))
        self.assertTrue(any("semantic_risk_categories" in item for item in template["decisions"]))
        self.assertTrue(any("visual_transcribed_values" in item for item in template["decisions"]))
        serialized = json.dumps(template, sort_keys=True)
        self.assertIn("<EXISTING_TEXT_ATOM_ID>", serialized)
        self.assertIn("<EXISTING_VISUAL_ATOM_ID>", serialized)
        for forbidden_key in (
            "source_id",
            "page",
            "exact_quote",
            "depiction_locator",
            "source_coverage",
            "r3_flags",
            "transcribed_values",
            "self_check",
        ):
            self.assertNotIn(f'"{forbidden_key}"', serialized)
        makefile_path = REPO_ROOT / "Makefile"
        self.assertTrue(makefile_path.is_file(), makefile_path)
        makefile = makefile_path.read_text(encoding="utf-8")
        self.assertIn("evidence-grounding-check:", makefile)
        for test_path in (
            "tests/test_evidence_grounding_v2.py",
            "tests/test_evidence_atom_vertical_slice.py",
            "tests/test_page_atom_catalog.py",
        ):
            self.assertIn(test_path, makefile)


if __name__ == "__main__":
    unittest.main(verbosity=2)
