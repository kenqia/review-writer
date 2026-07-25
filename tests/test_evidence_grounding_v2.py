#!/usr/bin/env python3
"""Contract tests for page-grounded evidence extraction v2."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "evidence_grounding_v2" / "packet"
VALIDATOR = REPO_ROOT / "scripts" / "evidence" / "validate_evidence_candidate.py"
PARSER = REPO_ROOT / "scripts" / "evidence" / "build_pdf_text_layers.py"
SCHEMA = REPO_ROOT / "schemas" / "evidence" / "evidence_candidate.v2.schema.json"


class EvidenceGroundingV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = FIXTURE_ROOT / "input" / "extraction_job.json"
        self.valid_path = FIXTURE_ROOT / "output" / "valid_candidate.json"
        self.valid = json.loads(self.valid_path.read_text(encoding="utf-8"))

    def validate(
        self,
        candidate: dict,
        *,
        job: Path | None = None,
        packet_root: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate_path = Path(temp_dir) / "candidate.json"
            report_path = Path(temp_dir) / "report.json"
            candidate_path.write_text(
                json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--job",
                    str(job or self.job),
                    "--candidate",
                    str(candidate_path),
                    "--packet-root",
                    str(packet_root or FIXTURE_ROOT),
                    "--schema",
                    str(SCHEMA),
                    "--report-json",
                    str(report_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        return result, report

    def assert_rejected(self, candidate: dict, code: str) -> None:
        result, report = self.validate(candidate)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("R0_FAIL_GROUNDING_CONTRACT", report.get("status"))
        self.assertIn(code, {finding["code"] for finding in report.get("findings", [])})

    def test_synthetic_valid_fixture_passes(self) -> None:
        result, report = self.validate(self.valid)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("R0_PASS", report.get("status"))
        self.assertEqual([], report.get("findings"))

    def test_paraphrase_cannot_masquerade_as_text_quote_even_if_self_check_is_true(self) -> None:
        candidate = copy.deepcopy(self.valid)
        candidate["claims"][0]["evidence_refs"][0]["exact_quote"] = (
            "Blue-light catalysis furnished 2a in a 91% isolated yield."
        )
        candidate["self_check"]["all_grounding_valid"] = True
        self.assert_rejected(candidate, "EXACT_QUOTE_NOT_FOUND_ON_PAGE")

    def test_exact_quote_on_wrong_page_is_rejected(self) -> None:
        candidate = copy.deepcopy(self.valid)
        candidate["claims"][0]["evidence_refs"][0]["page"] = 1
        self.assert_rejected(candidate, "EXACT_QUOTE_NOT_FOUND_ON_PAGE")

    def test_figure_evidence_cannot_masquerade_as_verbatim_quote(self) -> None:
        candidate = copy.deepcopy(self.valid)
        ref = candidate["reaction_units"][0]["evidence_refs"][0]
        ref["exact_quote"] = "FIGURE 2 catalyst -> product 2a 91% isolated yield"
        self.assert_rejected(candidate, "SCHEMA_INVALID")

    def test_visual_evidence_cannot_bypass_parent_r3_mapping(self) -> None:
        candidate = copy.deepcopy(self.valid)
        unit = candidate["reaction_units"][0]
        unit["risk_level"] = "R1"
        unit["risk_categories"] = []
        candidate["r3_review_items"] = []
        self.assert_rejected(candidate, "VISUAL_PARENT_R3_INVALID")

    def test_visual_evidence_is_forbidden_in_unmapped_containers(self) -> None:
        candidate = copy.deepcopy(self.valid)
        ref = candidate["eligibility"]["evidence_refs"][0]
        ref.update(
            {
                "evidence_mode": "FIGURE_TABLE_IMAGE",
                "exact_quote": None,
                "depiction_locator": "Figure 2, reaction arrow",
                "transcribed_values": ["product 2a"],
                "r3_flags": ["R3_SOURCE_DEPICTION_REQUIRED"],
            }
        )
        self.assert_rejected(candidate, "VISUAL_EVIDENCE_UNMAPPED_CONTAINER")

    def test_high_risk_claim_requires_r3_level_and_review_mapping(self) -> None:
        candidate = copy.deepcopy(self.valid)
        claim = candidate["claims"][0]
        claim["risk_categories"] = ["MECHANISM_CAUSALITY"]
        self.assert_rejected(candidate, "HIGH_RISK_NOT_R3")

        candidate = copy.deepcopy(self.valid)
        candidate["r3_review_items"] = []
        self.assert_rejected(candidate, "R3_REVIEW_MAPPING_MISSING")

    def test_r3_review_mapping_must_cover_target_categories(self) -> None:
        candidate = copy.deepcopy(self.valid)
        claim = candidate["claims"][0]
        claim["risk_level"] = "R3"
        claim["risk_categories"] = ["MECHANISM_CAUSALITY"]
        candidate["r3_review_items"].append(
            {
                "target_id": "CL-1",
                "risk_categories": ["STRUCTURE"],
                "action_required": "Inspect the source.",
            }
        )
        self.assert_rejected(candidate, "R3_REVIEW_CATEGORY_MISMATCH")

    def test_target_and_review_mapping_ids_are_unambiguous(self) -> None:
        duplicate_claim = copy.deepcopy(self.valid)
        duplicate_claim["claims"].append(copy.deepcopy(duplicate_claim["claims"][0]))
        self.assert_rejected(duplicate_claim, "TARGET_ID_DUPLICATE")

        cross_collection = copy.deepcopy(self.valid)
        cross_collection["claims"][0]["claim_id"] = "RU-1"
        self.assert_rejected(cross_collection, "TARGET_ID_DUPLICATE")

        duplicate_review = copy.deepcopy(self.valid)
        duplicate_review["r3_review_items"].append(
            copy.deepcopy(duplicate_review["r3_review_items"][0])
        )
        self.assert_rejected(duplicate_review, "R3_REVIEW_TARGET_DUPLICATE")

        dangling_review = copy.deepcopy(self.valid)
        dangling_review["r3_review_items"].append(
            {
                "target_id": "UNKNOWN",
                "risk_categories": ["STRUCTURE"],
                "action_required": "Inspect the source.",
            }
        )
        self.assert_rejected(dangling_review, "R3_REVIEW_TARGET_UNKNOWN")

    def test_unresolved_locator_is_non_promotable(self) -> None:
        candidate = copy.deepcopy(self.valid)
        ref = candidate["claims"][0]["evidence_refs"][0]
        ref.update(
            {
                "evidence_mode": "LOCATOR_UNRESOLVED",
                "page": None,
                "exact_quote": None,
                "evidence_summary": "The claim could not be grounded exactly.",
                "unresolved_reason": "No continuous exact passage was found.",
            }
        )
        self.assert_rejected(candidate, "LOCATOR_UNRESOLVED")

    def test_source_coverage_must_be_complete_and_counted(self) -> None:
        candidate = copy.deepcopy(self.valid)
        candidate["source_coverage"] = {}
        self.assert_rejected(candidate, "SOURCE_COVERAGE_INCOMPLETE")

        candidate = copy.deepcopy(self.valid)
        candidate["source_coverage"]["SYNTH_MAIN"]["evidence_ref_count"] = 99
        self.assert_rejected(candidate, "SOURCE_COVERAGE_COUNT_MISMATCH")

    def test_bound_reading_layer_hash_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            packet = Path(temp_dir) / "packet"
            shutil.copytree(FIXTURE_ROOT, packet)
            reading = packet / "sources" / "SYNTH_MAIN.reading.txt"
            reading.write_text(reading.read_text(encoding="utf-8") + "drift", encoding="utf-8")
            result, report = self.validate(
                self.valid,
                job=packet / "input" / "extraction_job.json",
                packet_root=packet,
            )
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("SOURCE_HASH_MISMATCH", {item["code"] for item in report["findings"]})

    def test_pdf_parser_builds_distinct_reading_and_layout_layers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_pdf = root / "source.pdf"
            fake_pdf.write_bytes(b"%PDF synthetic placeholder")
            fake_pdftotext = root / "pdftotext"
            fake_pdftotext.write_text(
                "#!/bin/sh\n"
                "out=''\n"
                "for arg in \"$@\"; do out=$arg; done\n"
                "case \" $* \" in\n"
                "  *' -layout '*) printf 'layout page 1\\flayout page 2\\n' > \"$out\" ;;\n"
                "  *) printf 'reading page 1\\freading page 2\\n' > \"$out\" ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake_pdftotext.chmod(0o755)
            output_root = root / "layers"
            result = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    "--source",
                    f"SYNTH_MAIN={fake_pdf}",
                    "--output-root",
                    str(output_root),
                    "--pdftotext",
                    str(fake_pdftotext),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            reading = output_root / "SYNTH_MAIN.reading.txt"
            layout = output_root / "SYNTH_MAIN.layout.txt"
            manifest = json.loads((output_root / "text_layers.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("reading page 1\freading page 2\n", reading.read_text(encoding="utf-8"))
            self.assertEqual("layout page 1\flayout page 2\n", layout.read_text(encoding="utf-8"))
            self.assertEqual(2, manifest["sources"][0]["page_count"])
            self.assertEqual("pdftotext-default-reading-order", manifest["sources"][0]["reading_order_method"])
            self.assertEqual("pdftotext-layout-visual-locator-only", manifest["sources"][0]["layout_method"])

    def test_generic_make_gate_runs_the_complete_grounding_suite(self) -> None:
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
