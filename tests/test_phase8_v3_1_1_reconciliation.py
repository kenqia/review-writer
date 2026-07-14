#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.v3_1_1_reconciliation import (  # noqa: E402
    deterministic_supported_spot_claim_id,
    prepare_final_reconciliation,
    reconcile_claims,
)


FIXED_IDS = [
    "CL-SU-eb42b7e36b700462-004",
    "CL-SU-df53ec3ac051d023-004",
    "CL-SU-6a771b839d148d00-003",
]


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


class Phase8V311ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.repo = cls.base / "repo"
        cls.repo.mkdir()
        (cls.repo / ".git").mkdir()
        cls.layer_a = cls.base / "layer-a"
        cls.layer_b = cls.base / "layer-b"
        cls.output_parent = cls.base / "output"
        cls.repo_head = "c" * 40
        cls._build_inputs()
        cls.a_results_hash = sha256(cls.layer_a / "output/results.jsonl")
        cls.a_input_hash = sha256(cls.layer_a / "INPUT_MANIFEST.json")
        cls.b_results_hash = sha256(cls.layer_b / "output/results.jsonl")
        cls.b_output_manifest_hash = sha256(cls.layer_b / "output/OUTPUT_MANIFEST.json")
        cls.b_input_hash = sha256(cls.layer_b / "INPUT_MANIFEST.json")
        cls.input_hashes_before = cls._input_hashes()
        cls.result = prepare_final_reconciliation(
            repo_root=cls.repo,
            output_parent=cls.output_parent,
            run_id="phase8_final_reconciliation_v3_1_1_20260714T010203Z",
            layer_a_workspace=cls.layer_a,
            layer_b_workspace=cls.layer_b,
            expected_layer_a_results_sha256=cls.a_results_hash,
            expected_layer_a_input_manifest_hash=cls.a_input_hash,
            expected_layer_b_results_sha256=cls.b_results_hash,
            expected_layer_b_output_manifest_sha256=cls.b_output_manifest_hash,
            expected_layer_b_input_manifest_hash=cls.b_input_hash,
            expected_layer_b_repo_head=cls.repo_head,
            coordinator_repo_head="d" * 40,
            page_renderer=cls._fixture_renderer,
        )
        cls.run_root = Path(cls.result["run_root"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    @classmethod
    def _input_hashes(cls) -> dict[str, str]:
        return {
            "a_results": sha256(cls.layer_a / "output/results.jsonl"),
            "a_input": sha256(cls.layer_a / "INPUT_MANIFEST.json"),
            "b_results": sha256(cls.layer_b / "output/results.jsonl"),
            "b_output_manifest": sha256(cls.layer_b / "output/OUTPUT_MANIFEST.json"),
            "b_input": sha256(cls.layer_b / "INPUT_MANIFEST.json"),
        }

    @staticmethod
    def _fixture_renderer(source: Path, packaged_page_index: int, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")

    @staticmethod
    def _locator() -> dict:
        return {
            "scope": "EXACT_PAGE",
            "pdf_page_index": 0,
            "page_window": None,
            "printed_page_label_observed": "S1",
            "section": "Synthetic section",
            "table_id": None,
            "scheme_id": None,
            "figure_id": None,
            "entry_id": "entry",
        }

    @classmethod
    def _claim(cls, claim_id: str, index: int, claim_type: str) -> dict:
        conflict = claim_type == "source_conflict"
        locator = cls._locator()
        return {
            "claim_id": claim_id,
            "paper_id": "P403",
            "source_document_id": "P403_SI",
            "source_role": "SI",
            "claim_type": claim_type,
            "substrate_ids": [f"substrate-{index}"],
            "reagent_or_partner_ids": ["partner"],
            "product_id": f"product-{index}",
            "intermediate_id": None,
            "reaction_stage": "target_catalytic_reaction",
            "reaction_entry": f"entry-{index}",
            "conditions_as_reported": "Synthetic conditions.",
            "metric_type": "not_applicable" if conflict else "isolated_yield",
            "value_as_reported": None if conflict else 70 + index % 20,
            "unit_as_reported": None if conflict else "%",
            "normalized_value_candidate": None,
            "normalized_metric_type": None,
            "normalization_rule": None,
            "normalization_source_supported": False,
            "evidence_locator": locator,
            "short_evidence": "Synthetic Layer A evidence.",
            "evidence_modality": "TEXT",
            "directness": "DIRECT_TEXTUAL" if conflict else "DIRECT_NUMERIC",
            "epistemic_class": "DIRECT_REPORTED_RESULT",
            "pathway_status": "NOT_APPLICABLE",
            "source_conflict_detected": conflict,
            "source_conflict": {
                "conflict_type": "SOURCE_INTERNAL_LABEL_CONFLICT",
                "alternatives": [
                    {"reported_value": "alpha", "locator": copy.deepcopy(locator)},
                    {"reported_value": "beta", "locator": copy.deepcopy(locator)},
                ],
            } if conflict else None,
        }

    @classmethod
    def _build_inputs(cls) -> None:
        synthetic_ids = [f"CL-SU-{index + 1:016x}-001" for index in range(41)]
        claim_ids = [*FIXED_IDS, *synthetic_ids]
        verdicts = ["INSUFFICIENT_EVIDENCE", "SOURCE_CONFLICT", "ENTITY_BINDING_ERROR"]
        verdicts += ["SOURCE_CONFLICT"] * 6 + ["LOCATOR_ERROR"] * 4 + ["REACTION_STAGE_ERROR"] * 2 + ["SUPPORTED"] * 29
        claims = []
        b_rows = []
        tasks = []
        for index, (claim_id, verdict) in enumerate(zip(claim_ids, verdicts)):
            claim_type = "source_conflict" if verdict == "SOURCE_CONFLICT" else "scope_result"
            claim = cls._claim(claim_id, index, claim_type)
            claims.append(claim)
            corrected = None
            if verdict == "LOCATOR_ERROR":
                corrected = {"evidence_locator": {**cls._locator(), "entry_id": f"corrected-{index}"}}
            elif verdict == "REACTION_STAGE_ERROR":
                corrected = {"reaction_stage": f"corrected-stage-{index}"}
            elif verdict == "ENTITY_BINDING_ERROR":
                corrected = {"substrate_ids": ["specific substrate"]}
            b_rows.append(
                {
                    "verifier_task_id": f"VB-{index + 1:016x}",
                    "claim_id": claim_id,
                    "claim_hash": hashlib.sha256(json.dumps(claim, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()).hexdigest(),
                    "task_hash": "e" * 64,
                    "input_manifest_hash": "f" * 64,
                    "verdict": verdict,
                    "corrected_fields": corrected,
                    "observed_evidence_locator": copy.deepcopy(claim["evidence_locator"]),
                    "short_independent_evidence": "Synthetic independent Layer B evidence.",
                    "error_categories": ["source_conflict"] if verdict == "SOURCE_CONFLICT" else [],
                    "source_conflict_assessment": "FAITHFULLY_RECORDED" if verdict == "SOURCE_CONFLICT" else "NOT_APPLICABLE",
                    "risk_level": 3 if verdict in {"SOURCE_CONFLICT", "ENTITY_BINDING_ERROR"} else 0,
                }
            )
            artifact = f"sources/VB-{index + 1:016x}__P403_SI.pdf"
            source = cls.layer_b / artifact
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"%PDF synthetic\n")
            tasks.append(
                {
                    "verifier_task_id": f"VB-{index + 1:016x}",
                    "claim_id": claim_id,
                    "claim_hash": b_rows[-1]["claim_hash"],
                    "task_hash": b_rows[-1]["task_hash"],
                    "source_artifact": artifact,
                    "source_binding": {
                        "packaged_artifact_sha256": sha256(source),
                        "original_to_packaged_page_index": {"0": 0},
                        "printed_page_labels": {"0": "S1"},
                    },
                }
            )
        distribution = [6, 6, 6, 6, 5, 5, 5, 5]
        a_rows = []
        offset = 0
        for count in distribution:
            a_rows.append({"source_unit_id": f"SU-{offset + 1:016x}", "claims": claims[offset:offset + count]})
            offset += count
        write_json(cls.layer_a / "INPUT_MANIFEST.json", {"schema_version": "3.1.1"})
        write_jsonl(cls.layer_a / "output/results.jsonl", a_rows)
        write_json(
            cls.layer_b / "INPUT_MANIFEST.json",
            {
                "schema_version": "3.1.1-layer-b",
                "repo_head": cls.repo_head,
                "upstream_layer_a_results_sha256": sha256(cls.layer_a / "output/results.jsonl"),
                "upstream_layer_a_input_manifest_hash": sha256(cls.layer_a / "INPUT_MANIFEST.json"),
            },
        )
        write_jsonl(cls.layer_b / "input/verifier_tasks.jsonl", tasks)
        manifest_hash = sha256(cls.layer_b / "INPUT_MANIFEST.json")
        for row in b_rows:
            row["input_manifest_hash"] = manifest_hash
        write_jsonl(cls.layer_b / "output/results.jsonl", b_rows)
        write_json(
            cls.layer_b / "output/OUTPUT_MANIFEST.json",
            {
                "status": "PASS",
                "package_role": "EXACT_CLAIM_VERIFICATION",
                "result_count": 44,
                "source_conflict_result_count": 7,
                "repo_head": cls.repo_head,
                "upstream_layer_a_results_sha256": sha256(cls.layer_a / "output/results.jsonl"),
                "upstream_layer_a_input_manifest_hash": sha256(cls.layer_a / "INPUT_MANIFEST.json"),
                "input_manifest_hash": sha256(cls.layer_b / "INPUT_MANIFEST.json"),
                "results_sha256": sha256(cls.layer_b / "output/results.jsonl"),
            },
        )

    def test_reconciliation_applies_only_allowed_fields_and_counts_dispositions(self) -> None:
        rows = read_jsonl(self.run_root / "reconciliation/reconciliation.jsonl")
        summary = json.loads((self.run_root / "reconciliation/reconciliation_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 44)
        self.assertEqual(
            summary["disposition_counts"],
            {
                "AI_SUPPORTED": 29,
                "AI_CORRECTED_LOCATOR": 4,
                "AI_CORRECTED_REACTION_STAGE": 2,
                "AI_CORRECTED_ENTITY_PENDING_SPOT_CHECK": 1,
                "SOURCE_CONFLICT_RETAINED": 7,
                "HUMAN_REVIEW_REQUIRED": 1,
            },
        )
        by_id = {row["claim_id"]: row for row in rows}
        self.assertIsNone(by_id[FIXED_IDS[0]]["reconciled_claim"])
        self.assertEqual(by_id[FIXED_IDS[1]]["reconciled_claim"]["source_conflict"], by_id[FIXED_IDS[1]]["layer_a_claim"]["source_conflict"])
        self.assertEqual(by_id[FIXED_IDS[2]]["applied_correction_fields"], ["substrate_ids"])
        locator_row = next(row for row in rows if row["final_disposition"] == "AI_CORRECTED_LOCATOR")
        original = locator_row["layer_a_claim"]
        reconciled = locator_row["reconciled_claim"]
        self.assertEqual({key: value for key, value in original.items() if key != "evidence_locator"}, {key: value for key, value in reconciled.items() if key != "evidence_locator"})

    def test_spot_check_package_has_fixed_three_and_deterministic_supported_fourth(self) -> None:
        queue = read_jsonl(self.run_root / "spot_checks/spot_check_queue.jsonl")
        b_rows = read_jsonl(self.layer_b / "output/results.jsonl")
        expected_random = min(
            (row["claim_id"] for row in b_rows if row["verdict"] == "SUPPORTED"),
            key=lambda claim_id: hashlib.sha256(f"phase8a-final-spotcheck-v1:{claim_id}".encode()).hexdigest(),
        )
        self.assertEqual([row["claim_id"] for row in queue], [*FIXED_IDS, expected_random])
        self.assertEqual(deterministic_supported_spot_claim_id(b_rows), expected_random)
        self.assertEqual(len(list((self.run_root / "spot_checks/screenshots").glob("*.png"))), 4)
        for row in queue:
            self.assertTrue((self.run_root / row["card_path"]).is_file())
            self.assertTrue((self.run_root / row["screenshot_path"]).is_file())
            self.assertGreaterEqual(len(row["user_options"]), 3)
        response = json.loads((self.run_root / "spot_checks/human_response_template.json").read_text(encoding="utf-8"))
        self.assertEqual(len(response["items"]), 4)
        self.assertTrue(all(row["selected_decision"] is None for row in response["items"]))
        self.assertFalse(response["human_decisions_recorded"])

    def test_hash_manifest_and_stage_boundaries(self) -> None:
        manifest = self.run_root / "HASH_MANIFEST.sha256"
        for line in manifest.read_text(encoding="utf-8").splitlines():
            digest, relative = line.split("  ", maxsplit=1)
            self.assertEqual(sha256(self.run_root / relative), digest)
        serialized = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in self.run_root.rglob("*") if path.is_file() and path.suffix != ".png").casefold()
        for forbidden in ("human_verified", "fully_verified", "scientifically_verified", "publication-grade validation"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(self.result["stage"], "PREPARED_FOR_FINAL_4_HUMAN_SPOT_CHECKS")
        self.assertFalse(self.result["layer_c_created"])
        self.assertFalse(self.result["phase8b_started"])
        self.assertEqual(self._input_hashes(), self.input_hashes_before)

    def test_reconciliation_rejects_wrong_correction_shape_and_hashes(self) -> None:
        a_rows = read_jsonl(self.layer_a / "output/results.jsonl")
        b_rows = read_jsonl(self.layer_b / "output/results.jsonl")
        bad = copy.deepcopy(b_rows)
        locator_index = next(index for index, row in enumerate(bad) if row["verdict"] == "LOCATOR_ERROR")
        bad[locator_index]["corrected_fields"]["reaction_stage"] = "not-allowed-here"
        with self.assertRaises(ValueError):
            reconcile_claims(a_rows, bad)
        with self.assertRaises(ValueError):
            prepare_final_reconciliation(
                repo_root=self.repo,
                output_parent=self.base / "bad-output",
                run_id="phase8_final_reconciliation_v3_1_1_20260714T020304Z",
                layer_a_workspace=self.layer_a,
                layer_b_workspace=self.layer_b,
                expected_layer_a_results_sha256="0" * 64,
                expected_layer_a_input_manifest_hash=self.a_input_hash,
                expected_layer_b_results_sha256=self.b_results_hash,
                expected_layer_b_output_manifest_sha256=self.b_output_manifest_hash,
                expected_layer_b_input_manifest_hash=self.b_input_hash,
                expected_layer_b_repo_head=self.repo_head,
                coordinator_repo_head="d" * 40,
                page_renderer=self._fixture_renderer,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
