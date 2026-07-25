#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.phase8b_grounded_revision import prepare_grounded_vertical_slice  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Phase8BGroundedVerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        self.final_claims = self.base / "final_reconciled_claims.jsonl"
        self.closure_manifest = self.base / "closure_HASH_MANIFEST.sha256"
        self.phase7_claims = self.base / "phase7_claims.json"
        self.output_parent = self.base / "external"
        self._build_inputs()
        self.input_hashes_before = self._input_hashes()
        self.result = prepare_grounded_vertical_slice(
            repo_root=self.repo,
            output_parent=self.output_parent,
            run_id="phase8b_grounded_vertical_slice_20260714T010203Z",
            final_claims_path=self.final_claims,
            closure_manifest_path=self.closure_manifest,
            phase7_claims_path=self.phase7_claims,
            expected_final_claims_sha256=sha256(self.final_claims),
            expected_closure_manifest_sha256=sha256(self.closure_manifest),
            expected_phase7_claims_sha256=sha256(self.phase7_claims),
            repo_head="a" * 40,
        )
        self.run_root = Path(self.result["run_root"])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _input_hashes(self) -> dict[str, str]:
        return {
            "final_claims": sha256(self.final_claims),
            "closure_manifest": sha256(self.closure_manifest),
            "phase7_claims": sha256(self.phase7_claims),
        }

    @staticmethod
    def _claim(claim_id: str, paper_id: str, index: int, claim_type: str) -> dict:
        numeric = claim_type in {"target_reaction_numeric_outcome", "optimization_result"}
        return {
            "schema_version": "3.1.1-phase8a-final-claim",
            "claim_id": claim_id,
            "final_claim": {
                "claim_id": claim_id,
                "paper_id": paper_id,
                "source_document_id": f"{paper_id}_MAIN",
                "claim_type": claim_type,
                "reaction_entry": f"representative reaction {index}",
                "reaction_stage": "target_catalytic_reaction",
                "substrate_ids": [f"substrate {index}"],
                "reagent_or_partner_ids": [f"partner {index}"],
                "product_id": f"product {index}",
                "metric_type": "isolated_yield" if numeric else "not_applicable",
                "value_as_reported": 70 + index if numeric else None,
                "unit_as_reported": "%" if numeric else None,
                "short_evidence": f"Source-grounded {paper_id} evidence statement {index}.",
                "source_conflict_detected": False,
                "source_conflict": None,
            },
            "final_disposition": "AI_SUPPORTED",
            "human_spot_check_status": None,
            "method_label": "HUMAN_SPOT_CHECKED_AI_ADJUDICATION",
        }

    def _build_inputs(self) -> None:
        rows = []
        distribution = {"F3I": 14, "F47A": 7, "P403": 16}
        claim_types = [
            "target_reaction_numeric_outcome",
            "scope_result",
            "experimental_mechanistic_observation",
            "explicit_limitation",
            "author_proposed_mechanism",
        ]
        global_index = 0
        for paper_id, count in distribution.items():
            for index in range(count):
                claim_id = f"CL-{paper_id}-{index + 1:03d}"
                rows.append(self._claim(claim_id, paper_id, global_index, claim_types[index % len(claim_types)]))
                global_index += 1
        for index in range(7):
            claim_id = f"CL-P403-CONFLICT-{index + 1:03d}"
            row = self._claim(claim_id, "P403", global_index + index, "source_conflict")
            row["final_claim"].update(
                {
                    "short_evidence": f"Source-internal conflict {index + 1}.",
                    "source_conflict_detected": True,
                    "source_conflict": {
                        "conflict_type": "SOURCE_INTERNAL_LABEL_CONFLICT",
                        "alternatives": [
                            {"reported_value": f"alternative A{index}"},
                            {"reported_value": f"alternative B{index}"},
                        ],
                    },
                }
            )
            row["final_disposition"] = "SOURCE_CONFLICT_RETAINED"
            rows.append(row)
        self.assertEqual(len(rows), 44)
        write_jsonl(self.final_claims, rows)
        self.closure_manifest.write_text("fixture closure manifest\n", encoding="utf-8")
        phase7 = []
        citations = [["F3I"], [], [], ["F47A"], [], [], ["P403"], [], [], []]
        for index in range(10):
            phase7.append(
                {
                    "claim_id": f"PHASE7-C{index + 1:02d}",
                    "sentence_id": f"PHASE7-S{index + 1:02d}",
                    "claim_text": (
                        f"Metadata-only Phase 7 payload sentence {index + 1} "
                        + (f"[{citations[index][0]}]." if citations[index] else "without chemical evidence.")
                    ),
                    "citation_ids": citations[index],
                    "support_status": "HUMAN_REVIEW_REQUIRED",
                }
            )
        write_json(self.phase7_claims, {"claims": phase7})

    def test_accounts_for_all_final_claims_and_keeps_conflicts_out_of_prose(self) -> None:
        mappings = read_jsonl(self.run_root / "mapping/claim_to_sentence_map.jsonl")
        summary = json.loads((self.run_root / "reports/vertical_slice_summary.json").read_text(encoding="utf-8"))
        revision = (self.run_root / "revision/grounded_revision.md").read_text(encoding="utf-8")
        self.assertEqual(len(mappings), 44)
        self.assertEqual(summary["final_claim_count"], 44)
        self.assertEqual(summary["usable_non_conflict_claim_count"], 37)
        self.assertEqual(summary["retained_source_conflict_count"], 7)
        self.assertEqual(sum(row["integration_status"] == "SOURCE_CONFLICT_RETAINED_NOT_ASSERTED" for row in mappings), 7)
        self.assertTrue(all(not row["revised_sentence_ids"] for row in mappings if row["integration_status"] == "SOURCE_CONFLICT_RETAINED_NOT_ASSERTED"))
        self.assertNotIn("Source-internal conflict", revision)
        self.assertEqual({row["paper_id"] for row in mappings if row["integration_status"] == "USED_IN_GROUNDED_REVISION"}, {"F3I", "F47A", "P403"})

    def test_rebuilds_phase7_before_assesses_ten_sentences_and_writes_traceable_revision(self) -> None:
        before = (self.run_root / "revision/before_section.md").read_text(encoding="utf-8")
        revision = (self.run_root / "revision/grounded_revision.md").read_text(encoding="utf-8")
        assessments = read_jsonl(self.run_root / "mapping/phase7_sentence_assessment.jsonl")
        sentence_map = read_jsonl(self.run_root / "mapping/revised_sentences.jsonl")
        self.assertEqual(len(assessments), 10)
        self.assertIn("Metadata-only Phase 7 payload sentence 1", before)
        self.assertNotIn("Metadata-only Phase 7 payload", revision)
        self.assertIn("## Representative strategies for asymmetric allene synthesis", revision)
        self.assertIn("[F3I]", revision)
        self.assertIn("[F47A]", revision)
        self.assertIn("[P403]", revision)
        self.assertTrue(sentence_map)
        for sentence in sentence_map:
            self.assertEqual(sentence["citation_ids"], [sentence["paper_id"]])
            self.assertTrue(sentence["final_claim_ids"])
            self.assertIn(f"[{sentence['paper_id']}]", sentence["text"])
        diff = (self.run_root / "revision/revision.diff").read_text(encoding="utf-8")
        self.assertIn("--- phase7_before.md", diff)
        self.assertIn("+++ phase8b_grounded_revision.md", diff)

    def test_remaining_attention_contains_exactly_seven_conflicts_without_new_decisions(self) -> None:
        attention = json.loads((self.run_root / "reports/remaining_human_attention.json").read_text(encoding="utf-8"))
        decisions = list(self.run_root.rglob("*decision*.jsonl"))
        self.assertEqual(attention["item_count"], 7)
        self.assertEqual(len(attention["items"]), 7)
        self.assertTrue(all(row["status"] == "SOURCE_CONFLICT_RETAINED" for row in attention["items"]))
        self.assertEqual(attention["human_budget_remaining"], 0)
        self.assertFalse(attention["additional_human_decisions_created"])
        self.assertEqual(decisions, [])

    def test_hash_manifest_input_binding_and_stage_boundaries(self) -> None:
        for line in (self.run_root / "HASH_MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
            digest, relative = line.split("  ", maxsplit=1)
            self.assertEqual(sha256(self.run_root / relative), digest)
        manifest = json.loads((self.run_root / "coordinator/run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["input_hashes"], self.input_hashes_before)
        self.assertEqual(self._input_hashes(), self.input_hashes_before)
        self.assertEqual(manifest["stage"], "PHASE8B_GROUNDED_REVISION_VERTICAL_SLICE_COMPLETE")
        self.assertEqual(manifest["section_count"], 1)
        self.assertFalse(manifest["network_used"])
        serialized = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in self.run_root.rglob("*")
            if path.is_file()
        ).casefold()
        self.assertNotIn("/home/", serialized)
        self.assertNotIn("chain_of_thought", serialized)
        self.assertNotIn("fully_verified", serialized)

    def test_rejects_wrong_final_claim_hash(self) -> None:
        with self.assertRaises(ValueError):
            prepare_grounded_vertical_slice(
                repo_root=self.repo,
                output_parent=self.base / "bad-output",
                run_id="phase8b_grounded_vertical_slice_20260714T020304Z",
                final_claims_path=self.final_claims,
                closure_manifest_path=self.closure_manifest,
                phase7_claims_path=self.phase7_claims,
                expected_final_claims_sha256="0" * 64,
                expected_closure_manifest_sha256=sha256(self.closure_manifest),
                expected_phase7_claims_sha256=sha256(self.phase7_claims),
                repo_head="a" * 40,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
