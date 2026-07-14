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

from review_writer.phase8.v3_1_1_closure import prepare_phase8a_closure  # noqa: E402


SPOT_IDS = [
    "CL-SU-eb42b7e36b700462-004",
    "CL-SU-df53ec3ac051d023-004",
    "CL-SU-6a771b839d148d00-003",
    "CL-SU-eb42b7e36b700462-001",
]
SELECTED = [
    "删除 DBA-specific 条件后保留",
    "确认 conflict 真实并保留",
    "采用 Layer B entity 修正",
    "确认无问题",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Phase8V311ClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        self.layer_a = self.base / "layer-a"
        self.layer_b = self.base / "layer-b"
        self.reconciliation = self.base / "phase8_final_reconciliation_v3_1_1_20260714T010203Z"
        self.output_parent = self.base / "closure-output"
        self.confirmed_response = self.base / "confirmed_response.json"
        self._build_fixture()
        self.frozen_before = self._frozen_hashes()
        self.result = prepare_phase8a_closure(
            repo_root=self.repo,
            output_parent=self.output_parent,
            run_id="phase8a_closure_v3_1_1_20260714T020304Z",
            reconciliation_run=self.reconciliation,
            layer_a_workspace=self.layer_a,
            layer_b_workspace=self.layer_b,
            confirmed_response_path=self.confirmed_response,
            decision_time_utc="2026-07-14T02:03:04Z",
            coordinator_repo_head="d" * 40,
            expected_reconciliation_manifest_sha256=sha256(self.reconciliation / "HASH_MANIFEST.sha256"),
            expected_layer_a_results_sha256=self.a_results_hash,
            expected_layer_a_input_manifest_hash=self.a_input_hash,
            expected_layer_b_results_sha256=self.b_results_hash,
            expected_layer_b_output_manifest_sha256=self.b_output_hash,
            expected_layer_b_input_manifest_hash=self.b_input_hash,
            previous_human_budget_used=6,
        )
        self.closure = Path(self.result["closure_root"])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _frozen_hashes(self) -> dict[str, str]:
        return {
            "reconciliation_manifest": sha256(self.reconciliation / "HASH_MANIFEST.sha256"),
            "a_results": sha256(self.layer_a / "output/results.jsonl"),
            "a_input": sha256(self.layer_a / "INPUT_MANIFEST.json"),
            "b_results": sha256(self.layer_b / "output/results.jsonl"),
            "b_output": sha256(self.layer_b / "output/OUTPUT_MANIFEST.json"),
            "b_input": sha256(self.layer_b / "INPUT_MANIFEST.json"),
        }

    @staticmethod
    def _base_claim(claim_id: str) -> dict:
        return {
            "claim_id": claim_id,
            "claim_type": "scope_result",
            "conditions_as_reported": None,
            "directness": "DIRECT_TEXTUAL",
            "epistemic_class": "DIRECT_REPORTED_RESULT",
            "evidence_locator": {
                "entry_id": "entry",
                "figure_id": None,
                "page_window": None,
                "pdf_page_index": 0,
                "printed_page_label_observed": "S1",
                "scheme_id": None,
                "scope": "EXACT_PAGE",
                "section": "section",
                "table_id": None,
            },
            "evidence_modality": "TEXT",
            "intermediate_id": None,
            "metric_type": "not_applicable",
            "normalization_rule": None,
            "normalization_source_supported": False,
            "normalized_metric_type": None,
            "normalized_value_candidate": None,
            "paper_id": "P403",
            "pathway_status": "NOT_APPLICABLE",
            "product_id": "product",
            "reaction_entry": "entry",
            "reaction_stage": "target_catalytic_reaction",
            "reagent_or_partner_ids": [],
            "short_evidence": "Synthetic evidence.",
            "source_conflict": None,
            "source_conflict_detected": False,
            "source_document_id": "P403_SI",
            "source_role": "SI",
            "substrate_ids": ["substrate"],
            "unit_as_reported": None,
            "value_as_reported": None,
        }

    def _reconciliation_record(self, claim_id: str, disposition: str, claim: dict) -> dict:
        return {
            "schema_version": "3.1.1-final-reconciliation",
            "claim_id": claim_id,
            "source_unit_id": "SU-fixture",
            "layer_a_claim_hash": canonical_hash(claim),
            "layer_a_claim": copy.deepcopy(claim),
            "layer_b_verification": {"claim_id": claim_id},
            "applied_correction_fields": [],
            "reconciled_claim": None if disposition == "HUMAN_REVIEW_REQUIRED" else copy.deepcopy(claim),
            "final_disposition": disposition,
        }

    def _build_fixture(self) -> None:
        write_jsonl(self.layer_a / "output/results.jsonl", [{"fixture": "a"}])
        write_json(self.layer_a / "INPUT_MANIFEST.json", {"fixture": "a-input"})
        write_jsonl(self.layer_b / "output/results.jsonl", [{"fixture": "b"}])
        write_json(self.layer_b / "output/OUTPUT_MANIFEST.json", {"fixture": "b-output"})
        write_json(self.layer_b / "INPUT_MANIFEST.json", {"fixture": "b-input"})
        self.a_results_hash = sha256(self.layer_a / "output/results.jsonl")
        self.a_input_hash = sha256(self.layer_a / "INPUT_MANIFEST.json")
        self.b_results_hash = sha256(self.layer_b / "output/results.jsonl")
        self.b_output_hash = sha256(self.layer_b / "output/OUTPUT_MANIFEST.json")
        self.b_input_hash = sha256(self.layer_b / "INPUT_MANIFEST.json")

        dba = self._base_claim(SPOT_IDS[0])
        dba.update(
            {
                "claim_type": "stoichiometric_result",
                "conditions_as_reported": "THF, 20 deg C, DBA present (2 equiv to 5)",
                "intermediate_id": "complex 5",
                "metric_type": "isolated_yield",
                "product_id": "allene 3an",
                "reaction_entry": "stoichiometric reaction of isolated complex 5 with sodium salt of 2n",
                "reaction_stage": "stoichiometric_intermediate_reactivity",
                "reagent_or_partner_ids": ["dibenzalacetone"],
                "short_evidence": "The main text reports 76% yield for conversion to 3an in the presence of DBA.",
                "substrate_ids": ["complex 5", "sodium salt of 2n"],
                "unit_as_reported": "%",
                "value_as_reported": 76,
            }
        )
        dba["evidence_locator"]["entry_id"] = "3an with DBA"
        conflict = self._base_claim(SPOT_IDS[1])
        conflict.update(
            {
                "claim_type": "source_conflict",
                "source_conflict_detected": True,
                "source_conflict": {
                    "conflict_type": "SOURCE_INTERNAL_LABEL_CONFLICT",
                    "alternatives": [{"reported_value": "1q / 3qa"}, {"reported_value": "1a + 2a"}],
                },
            }
        )
        entity = self._base_claim(SPOT_IDS[2])
        entity["substrate_ids"] = ["allene-tethered hydroxyamines and hydrazines 139"]
        sampled = self._base_claim(SPOT_IDS[3])

        records = [
            self._reconciliation_record(SPOT_IDS[0], "HUMAN_REVIEW_REQUIRED", dba),
            self._reconciliation_record(SPOT_IDS[1], "SOURCE_CONFLICT_RETAINED", conflict),
            self._reconciliation_record(SPOT_IDS[2], "AI_CORRECTED_ENTITY_PENDING_SPOT_CHECK", entity),
            self._reconciliation_record(SPOT_IDS[3], "AI_SUPPORTED", sampled),
        ]
        for index in range(28):
            claim = self._base_claim(f"CL-supported-{index:02d}")
            records.append(self._reconciliation_record(claim["claim_id"], "AI_SUPPORTED", claim))
        for index in range(4):
            claim = self._base_claim(f"CL-locator-{index:02d}")
            records.append(self._reconciliation_record(claim["claim_id"], "AI_CORRECTED_LOCATOR", claim))
        for index in range(2):
            claim = self._base_claim(f"CL-stage-{index:02d}")
            records.append(self._reconciliation_record(claim["claim_id"], "AI_CORRECTED_REACTION_STAGE", claim))
        for index in range(6):
            claim = self._base_claim(f"CL-conflict-{index:02d}")
            claim.update(
                {
                    "claim_type": "source_conflict",
                    "source_conflict_detected": True,
                    "source_conflict": {"conflict_type": "SOURCE_INTERNAL_LABEL_CONFLICT", "alternatives": [{}, {}]},
                }
            )
            records.append(self._reconciliation_record(claim["claim_id"], "SOURCE_CONFLICT_RETAINED", claim))
        self.assertEqual(len(records), 44)
        write_jsonl(self.reconciliation / "reconciliation/reconciliation.jsonl", records)

        options = [
            ["保留原 claim", SELECTED[0], "unresolved/exclude"],
            [SELECTED[1], "conflict 记录需编辑", "unresolved/exclude"],
            [SELECTED[2], "保留 Layer A 泛称", "unresolved/exclude"],
            [SELECTED[3], "需要编辑", "unresolved/exclude"],
        ]
        queue = [
            {"claim_id": claim_id, "user_options": choices, "human_decision_recorded": False}
            for claim_id, choices in zip(SPOT_IDS, options)
        ]
        write_jsonl(self.reconciliation / "spot_checks/spot_check_queue.jsonl", queue)
        write_json(
            self.reconciliation / "spot_checks/human_response_template.json",
            {
                "schema_version": "3.1.1-human-spot-check-response",
                "human_decisions_recorded": False,
                "items": [
                    {"claim_id": claim_id, "selected_decision": None, "reviewer_note": None}
                    for claim_id in SPOT_IDS
                ],
            },
        )
        write_json(
            self.reconciliation / "coordinator/run_manifest.json",
            {
                "run_id": self.reconciliation.name,
                "stage": "PREPARED_FOR_FINAL_4_HUMAN_SPOT_CHECKS",
                "claim_count": 44,
                "human_decisions_recorded": False,
                "layer_c_created": False,
                "phase8b_started": False,
                "frozen_inputs": {
                    "layer_a_results_sha256": self.a_results_hash,
                    "layer_a_input_manifest_hash": self.a_input_hash,
                    "layer_b_results_sha256": self.b_results_hash,
                    "layer_b_output_manifest_sha256": self.b_output_hash,
                    "layer_b_input_manifest_hash": self.b_input_hash,
                },
            },
        )
        manifest_rows = []
        for path in sorted(path for path in self.reconciliation.rglob("*") if path.is_file()):
            manifest_rows.append(f"{sha256(path)}  {path.relative_to(self.reconciliation).as_posix()}")
        (self.reconciliation / "HASH_MANIFEST.sha256").write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")
        write_json(
            self.confirmed_response,
            {
                "schema_version": "3.1.1-human-spot-check-response",
                "human_decisions_recorded": True,
                "items": [
                    {"claim_id": claim_id, "selected_decision": selected, "reviewer_note": None}
                    for claim_id, selected in zip(SPOT_IDS, SELECTED)
                ],
            },
        )

    def test_records_exactly_four_hash_bound_decisions_and_closes_budget(self) -> None:
        decisions = read_jsonl(self.closure / "human_decisions/human_spot_check_decisions.jsonl")
        response = json.loads((self.closure / "human_decisions/human_response.json").read_text(encoding="utf-8"))
        queue_hash = sha256(self.reconciliation / "spot_checks/spot_check_queue.jsonl")
        queue = read_jsonl(self.reconciliation / "spot_checks/spot_check_queue.jsonl")
        self.assertEqual(len(decisions), 4)
        self.assertEqual([row["claim_id"] for row in decisions], SPOT_IDS)
        self.assertEqual([row["selected_decision"] for row in decisions], SELECTED)
        self.assertTrue(all(row["spot_check_queue_sha256"] == queue_hash for row in decisions))
        self.assertEqual([row["spot_check_item_hash"] for row in decisions], [canonical_hash(row) for row in queue])
        self.assertTrue(all(row["decision_time_utc"] == "2026-07-14T02:03:04Z" for row in decisions))
        self.assertTrue(all(row["reconciliation_run_id"] == self.reconciliation.name for row in decisions))
        self.assertTrue(response["human_decisions_recorded"])
        self.assertEqual(response["budget"], {"previously_used": 6, "newly_recorded": 4, "total_used": 10, "maximum": 10, "remaining": 0})

    def test_dba_binding_is_removed_consistently_without_changing_yield(self) -> None:
        rows = {row["claim_id"]: row for row in read_jsonl(self.closure / "final/final_reconciled_claims.jsonl")}
        row = rows[SPOT_IDS[0]]
        claim = row["final_claim"]
        self.assertEqual(row["final_disposition"], "HUMAN_SPOT_CHECKED_CORRECTED_ACCEPT")
        self.assertEqual(claim["value_as_reported"], 76)
        self.assertEqual(claim["unit_as_reported"], "%")
        self.assertEqual(claim["reaction_stage"], "target_stoichiometric_reaction")
        self.assertEqual(claim["conditions_as_reported"], "THF, 20 deg C")
        self.assertEqual(claim["reagent_or_partner_ids"], [])
        self.assertEqual(claim["evidence_locator"]["entry_id"], "3an")
        self.assertNotIn("dba", json.dumps(claim, ensure_ascii=False).casefold())
        self.assertNotIn("dibenzalacetone", json.dumps(claim, ensure_ascii=False).casefold())
        report = json.loads((self.closure / "human_decisions/human_decision_application_report.json").read_text(encoding="utf-8"))
        applied = next(row for row in report["applications"] if row["claim_id"] == SPOT_IDS[0])
        self.assertEqual(
            applied["changed_fields"],
            [
                "conditions_as_reported",
                "evidence_locator.entry_id",
                "reaction_stage",
                "reagent_or_partner_ids",
                "short_evidence",
            ],
        )
        self.assertEqual(applied["checked_unchanged_fields"], ["reaction_entry"])

    def test_final_records_cover_44_with_expected_dispositions_and_annotations(self) -> None:
        rows = read_jsonl(self.closure / "final/final_reconciled_claims.jsonl")
        summary = json.loads((self.closure / "final/phase8a_closure_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 44)
        self.assertEqual(
            summary["final_disposition_counts"],
            {
                "AI_SUPPORTED": 29,
                "AI_CORRECTED_LOCATOR": 4,
                "AI_CORRECTED_REACTION_STAGE": 2,
                "AI_CORRECTED_ENTITY": 1,
                "HUMAN_SPOT_CHECKED_CORRECTED_ACCEPT": 1,
                "SOURCE_CONFLICT_RETAINED": 7,
            },
        )
        self.assertEqual(summary["human_review_required_count"], 0)
        self.assertEqual(summary["usable_non_conflict_claim_count"], 37)
        self.assertEqual(summary["retained_source_conflict_count"], 7)
        by_id = {row["claim_id"]: row for row in rows}
        self.assertEqual(by_id[SPOT_IDS[1]]["human_spot_check_status"], "CONFIRMED_SOURCE_CONFLICT_RETAINED")
        self.assertEqual(by_id[SPOT_IDS[2]]["final_disposition"], "AI_CORRECTED_ENTITY")
        self.assertEqual(by_id[SPOT_IDS[2]]["human_spot_check_status"], "CONFIRMED_CORRECTION")
        self.assertEqual(by_id[SPOT_IDS[3]]["human_spot_check_status"], "PASSED")
        self.assertTrue(all(row["final_claim"] is not None for row in rows))

    def test_hash_manifest_stage_boundaries_and_frozen_inputs(self) -> None:
        for line in (self.closure / "HASH_MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
            digest, relative = line.split("  ", maxsplit=1)
            self.assertEqual(sha256(self.closure / relative), digest)
        serialized = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in self.closure.rglob("*")
            if path.is_file()
        ).casefold()
        for forbidden in ("human_verified", "fully_verified", "scientifically_verified", "publication-grade"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(self._frozen_hashes(), self.frozen_before)
        self.assertEqual(self.result["stage"], "PHASE8A_COMPLETE_PR3_READY_FOR_REVIEW")
        self.assertFalse(self.result["layer_c_created"])
        self.assertFalse(self.result["phase8b_started"])

    def test_rejects_extra_decision_and_wrong_frozen_hash(self) -> None:
        response = json.loads(self.confirmed_response.read_text(encoding="utf-8"))
        response["items"].append({"claim_id": "CL-extra", "selected_decision": "确认无问题", "reviewer_note": None})
        bad_response = self.base / "bad_response.json"
        write_json(bad_response, response)
        with self.assertRaises(ValueError):
            prepare_phase8a_closure(
                repo_root=self.repo,
                output_parent=self.base / "bad-output",
                run_id="phase8a_closure_v3_1_1_20260714T030405Z",
                reconciliation_run=self.reconciliation,
                layer_a_workspace=self.layer_a,
                layer_b_workspace=self.layer_b,
                confirmed_response_path=bad_response,
                decision_time_utc="2026-07-14T03:04:05Z",
                coordinator_repo_head="d" * 40,
                expected_reconciliation_manifest_sha256=self.frozen_before["reconciliation_manifest"],
                expected_layer_a_results_sha256=self.a_results_hash,
                expected_layer_a_input_manifest_hash=self.a_input_hash,
                expected_layer_b_results_sha256="0" * 64,
                expected_layer_b_output_manifest_sha256=self.b_output_hash,
                expected_layer_b_input_manifest_hash=self.b_input_hash,
                previous_human_budget_used=6,
            )

    def test_rejects_reconciliation_manifest_with_mismatched_upstream_binding(self) -> None:
        manifest_path = self.reconciliation / "coordinator/run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["frozen_inputs"]["layer_b_results_sha256"] = "f" * 64
        write_json(manifest_path, manifest)
        hash_manifest = self.reconciliation / "HASH_MANIFEST.sha256"
        rows = []
        for path in sorted(
            path for path in self.reconciliation.rglob("*") if path.is_file() and path != hash_manifest
        ):
            rows.append(f"{sha256(path)}  {path.relative_to(self.reconciliation).as_posix()}")
        hash_manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            prepare_phase8a_closure(
                repo_root=self.repo,
                output_parent=self.base / "bad-binding-output",
                run_id="phase8a_closure_v3_1_1_20260714T040506Z",
                reconciliation_run=self.reconciliation,
                layer_a_workspace=self.layer_a,
                layer_b_workspace=self.layer_b,
                confirmed_response_path=self.confirmed_response,
                decision_time_utc="2026-07-14T04:05:06Z",
                coordinator_repo_head="d" * 40,
                expected_reconciliation_manifest_sha256=sha256(hash_manifest),
                expected_layer_a_results_sha256=self.a_results_hash,
                expected_layer_a_input_manifest_hash=self.a_input_hash,
                expected_layer_b_results_sha256=self.b_results_hash,
                expected_layer_b_output_manifest_sha256=self.b_output_hash,
                expected_layer_b_input_manifest_hash=self.b_input_hash,
                previous_human_budget_used=6,
            )

    def test_public_docs_report_phase8a_closure_without_private_paths(self) -> None:
        report = json.loads((REPO_ROOT / "docs/phase8/phase8a_status_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["checkpoint"], "PHASE8A_COMPLETE_PR3_READY_FOR_REVIEW")
        self.assertEqual(report["scientific_layer_a_row_count"], 8)
        self.assertEqual(report["scientific_layer_a_claim_count"], 44)
        self.assertEqual(report["layer_b_completed_count"], 44)
        self.assertEqual(report["human_budget"]["total_used"], 10)
        self.assertEqual(report["human_budget"]["remaining"], 0)
        self.assertFalse(report["layer_c_created"])
        self.assertFalse(report["phase8b_started"])
        public_paths = [
            REPO_ROOT / "README.md",
            REPO_ROOT / "docs/handoff/CURRENT.md",
            REPO_ROOT / "docs/phase8/README.md",
            REPO_ROOT / "docs/phase8/phase8a_status_report.md",
            REPO_ROOT / "docs/phase8/phase8a_status_report.json",
        ]
        public_text = "\n".join(path.read_text(encoding="utf-8") for path in public_paths)
        self.assertIn("HUMAN_SPOT_CHECKED_AI_ADJUDICATION", public_text)
        self.assertIn("PHASE8A_COMPLETE_PR3_READY_FOR_REVIEW", public_text)
        self.assertNotIn("/home/", public_text)
        self.assertNotIn("AI_REVIEW_WORKSPACES", public_text)
        builder = (REPO_ROOT / "scripts/phase8/build_phase8_review_package.py").read_text(encoding="utf-8")
        self.assertNotIn('default=Path("docs/phase8/phase8a_status_report.json")', builder)
        self.assertNotIn('default=Path("docs/phase8/phase8a_status_report.md")', builder)


if __name__ == "__main__":
    unittest.main(verbosity=2)
