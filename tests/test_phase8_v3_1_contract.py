#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.v3_1_source_first import (  # noqa: E402
    evaluate_v3_1_calibration,
    prepare_v3_1_workspaces,
    validate_v3_1_workspace,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


class Phase8V31ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.repo = cls.base / "repo"
        cls.external = cls.base / "external"
        (cls.repo / ".git").mkdir(parents=True)
        cls.sources = cls._make_sources()
        cls.source_metadata = {
            source_id: {
                "source_document_id": source_id,
                "paper_id": source_id.split("_")[0],
                "source_role": source_id.rsplit("_", 1)[1],
                "page_count": page_count,
                "sha256": sha256(cls.sources[source_id]),
                "printed_page_labels": {str(index): f"{prefix}-{index + 1}" for index in range(page_count)},
            }
            for source_id, (page_count, prefix) in cls._source_specifications().items()
        }
        cls.audits = {
            source_id: {
                "source_document_id": source_id,
                "paper_id": source_id.split("_")[0],
                "source_role": source_id.rsplit("_", 1)[1],
                "status": "IDENTITY_VALIDATED_STRONG",
                "sha256": sha256(path),
            }
            for source_id, path in cls.sources.items()
        }
        cls.event = {
            "core_review_item_id": "RU-SYNTHETIC-CALIBRATION",
            "final_decision": "edit",
            "edited_value": "61% synthetic preparation yield",
            "classification": "substrate_preparation_yield / substrate_synthesis",
            "target_catalytic_reaction_relevance": "low",
            "source_locator": {
                "source_document_id": "P403_SI",
                "pdf_page_index": 11,
                "printed_page_label": "stale-label",
                "compound_label": "aa",
            },
        }
        cls.result = prepare_v3_1_workspaces(
            repo_root=cls.repo,
            workspace_parent=cls.external,
            run_id="phase8_source_first_v3_1_20260713T010203Z",
            sources=cls.sources,
            identity_audits=cls.audits,
            human_events=[cls.event],
            repo_head="deadbeef",
            branch="feature",
            pr_number=3,
            random_seed=80423,
            instruction_sources=[],
            source_metadata=cls.source_metadata,
            pdf_slice_writer=cls._fixture_slice_writer,
        )
        cls.scientific = Path(cls.result["layerA_inventory_workspace"])
        cls.calibration = Path(cls.result["calibration_layerA_workspace"])
        cls.initial_outputs_empty = {
            cls.scientific: list((cls.scientific / "output").iterdir()) == [],
            cls.calibration: list((cls.calibration / "output").iterdir()) == [],
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    @classmethod
    def _make_pdf(cls, path: Path, page_count: int, prefix: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"%PDF synthetic fixture {prefix} pages={page_count}\n".encode())

    @staticmethod
    def _source_specifications() -> dict[str, tuple[int, str]]:
        return {
            "F3I_MAIN": (39, "F3I"),
            "F47A_MAIN": (2, "F47M"),
            "F47A_SI": (3, "F47S"),
            "P403_MAIN": (10, "P403M"),
            "P403_SI": (190, "TESTS"),
        }

    @classmethod
    def _make_sources(cls) -> dict[str, Path]:
        sources = {}
        for source_id, (page_count, prefix) in cls._source_specifications().items():
            path = cls.repo / "local/phase8_evidence/sources" / source_id.split("_")[0] / f"{source_id}.pdf"
            cls._make_pdf(path, page_count, prefix)
            sources[source_id] = path
        return sources

    @staticmethod
    def _fixture_slice_writer(source: Path, destination: Path, original_page_indices: list[int]) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes() + json.dumps(original_page_indices).encode())

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _tasks(self, workspace: Path | None = None) -> list[dict]:
        return self._read_jsonl((workspace or self.scientific) / "input/source_units.jsonl")

    def _manifest_hash(self, workspace: Path | None = None) -> str:
        return sha256((workspace or self.scientific) / "INPUT_MANIFEST.json")

    def _coverage(self, task: dict, *, complete: bool = True) -> dict:
        required = task["completion_criteria"]["required_page_indices"]
        pages = copy.deepcopy(required if complete else required[:1])
        return {
            "coverage_summary": "Synthetic contract coverage.",
            "pages_examined": pages,
            "sections_examined": ["synthetic section"] if pages else [],
            "status_reason": None if complete else "Synthetic partial coverage.",
        }

    def _partial_coverage(self, task: dict) -> dict:
        first = task["completion_criteria"]["required_page_indices"][0]
        return {
            "coverage_summary": "Synthetic proper-subset coverage.",
            "pages_examined": [{"source_document_id": first["source_document_id"], "page_indices": [first["page_indices"][0]]}],
            "sections_examined": ["synthetic partial section"],
            "status_reason": "Synthetic partial coverage.",
        }

    @staticmethod
    def _as_nonnumeric(claim: dict) -> dict:
        claim.update(
            {
                "product_id": None,
                "reaction_entry": None,
                "conditions_as_reported": None,
                "metric_type": "not_applicable",
                "value_as_reported": None,
                "unit_as_reported": None,
                "normalized_value_candidate": None,
                "normalized_metric_type": None,
                "normalization_rule": None,
                "normalization_source_supported": False,
                "directness": "DIRECT_TEXTUAL",
            }
        )
        return claim

    def _calibration_gold_claim(self, task: dict, *, sequence: int = 1) -> dict:
        claim = self._claim(task, sequence=sequence)
        claim.update(
            {
                "claim_type": "substrate_preparation_numeric_outcome",
                "product_id": "aa",
                "reaction_stage": "substrate_synthesis",
                "metric_type": "isolated_yield",
                "value_as_reported": "61%",
                "unit_as_reported": "%",
                "epistemic_class": "DIRECT_REPORTED_RESULT",
            }
        )
        return claim

    def _claim(self, task: dict, *, sequence: int = 1) -> dict:
        source_id = task["source_document_ids"][0]
        page_index = task["completion_criteria"]["required_page_indices"][0]["page_indices"][0]
        label = task["printed_page_labels"][source_id][str(page_index)]
        claim_type = "target_reaction_numeric_outcome"
        reaction_stage = "target_catalytic_reaction"
        epistemic_class = "DIRECT_REPORTED_RESULT"
        if task["paper_id"] == "F3I":
            claim_type = "scope_result"
            epistemic_class = "REVIEW_ARTICLE_SUMMARY"
        elif "target_reaction_numeric_outcome" not in task["included_claim_classes"]:
            if "substrate_preparation_numeric_outcome" in task["included_claim_classes"]:
                claim_type = "substrate_preparation_numeric_outcome"
                reaction_stage = "substrate_synthesis"
            else:
                claim_type = "optimization_result"
                reaction_stage = "optimization"
        return {
            "claim_id": f"CL-{task['source_unit_id']}-{sequence:03d}",
            "paper_id": task["paper_id"],
            "source_document_id": source_id,
            "source_role": task["source_roles"][source_id],
            "claim_type": claim_type,
            "substrate_ids": ["substrate-fixture"],
            "reagent_or_partner_ids": ["partner-fixture"],
            "product_id": "product-fixture",
            "intermediate_id": None,
            "reaction_stage": reaction_stage,
            "reaction_entry": "entry-fixture",
            "conditions_as_reported": "Synthetic conditions.",
            "metric_type": "isolated_yield",
            "value_as_reported": "61%",
            "unit_as_reported": "%",
            "normalized_value_candidate": 61,
            "normalized_metric_type": "isolated_yield",
            "normalization_rule": "Remove the percent sign without changing the metric.",
            "normalization_source_supported": True,
            "evidence_locator": {
                "scope": "EXACT_PAGE",
                "pdf_page_index": page_index,
                "page_window": None,
                "printed_page_label_observed": label,
                "section": "synthetic section",
                "table_id": None,
                "scheme_id": None,
                "figure_id": None,
                "entry_id": "entry-fixture",
            },
            "short_evidence": "Synthetic direct numeric evidence.",
            "evidence_modality": "TEXT",
            "directness": "DIRECT_NUMERIC",
            "epistemic_class": epistemic_class,
            "pathway_status": "NOT_APPLICABLE",
            "source_conflict_detected": False,
            "source_conflict": None,
        }

    def _valid_scientific_rows(self) -> list[dict]:
        rows = []
        for task in self._tasks():
            rows.append(
                {
                    "source_unit_id": task["source_unit_id"],
                    "source_unit_status": "COMPLETED",
                    "input_manifest_hash": self._manifest_hash(),
                    "task_hash": task["task_hash"],
                    **self._coverage(task),
                    "claims": [self._claim(task)],
                }
            )
        return rows

    def _finalize(self, workspace: Path, rows: list[dict]) -> subprocess.CompletedProcess[str]:
        output = workspace / "output"
        for name in ("OUTPUT_MANIFEST.json", "OUTPUT_MANIFEST.sha256"):
            (output / name).unlink(missing_ok=True)
        write_jsonl(output / "results.jsonl", rows)
        return subprocess.run(
            [sys.executable, str(workspace / "input/finalize_output.py")],
            cwd=workspace,
            capture_output=True,
            text=True,
        )

    def _finalize_and_evaluate_calibration(self, claims: list[dict]) -> tuple[subprocess.CompletedProcess[str], dict]:
        task = self._tasks(self.calibration)[0]
        row = {
            "source_unit_id": task["source_unit_id"],
            "source_unit_status": "COMPLETED",
            "input_manifest_hash": self._manifest_hash(self.calibration),
            "task_hash": task["task_hash"],
            **self._coverage(task),
            "claims": claims,
        }
        finalized = self._finalize(self.calibration, [row])
        report = evaluate_v3_1_calibration(Path(self.result["run_root"]))
        return finalized, report

    def test_workspaces_are_separate_immutable_and_scientific_has_eight_shards(self) -> None:
        scientific_tasks = self._tasks()
        calibration_tasks = self._tasks(self.calibration)
        self.assertEqual(len(scientific_tasks), 8)
        self.assertEqual(len(calibration_tasks), 1)
        self.assertTrue(all(task["unit_kind"] == "SCIENTIFIC" for task in scientific_tasks))
        self.assertEqual(calibration_tasks[0]["unit_kind"], "CALIBRATION")
        self.assertFalse(any(11 in group["page_indices"] for task in scientific_tasks for group in task["completion_criteria"]["required_page_indices"] if group["source_document_id"] == "P403_SI"))
        self.assertEqual(calibration_tasks[0]["completion_criteria"]["required_page_indices"][0]["page_indices"], [11])
        self.assertFalse((Path(self.result["run_root"]) / "layerB_verifier").exists())
        self.assertFalse((Path(self.result["run_root"]) / "layerC_adjudicator").exists())
        for workspace, expected_role in ((self.scientific, "SCIENTIFIC_INVENTORY"), (self.calibration, "HIDDEN_CALIBRATION")):
            report = validate_v3_1_workspace(workspace, repo_root=self.repo, expected_package_role=expected_role)
            self.assertEqual(report["status"], "PASS", report["issues"])
            self.assertTrue(self.initial_outputs_empty[workspace])

    def test_eight_audit_bypasses_are_rejected(self) -> None:
        tasks = self._tasks()
        cases: dict[str, list[dict]] = {}
        empty = self._valid_scientific_rows()
        for row in empty:
            row["claims"] = []
        cases["all_empty_finalizes"] = empty

        unreadable = self._valid_scientific_rows()
        unreadable[0]["source_unit_status"] = "SOURCE_UNREADABLE"
        unreadable[0]["status_reason"] = "Synthetic unreadable source."
        cases["source_unreadable_with_claims"] = unreadable

        wrong_role = self._valid_scientific_rows()
        wrong_role[3]["claims"][0]["source_role"] = "SI"
        cases["wrong_source_role"] = wrong_role

        wrong_page = self._valid_scientific_rows()
        wrong_page[0]["claims"][0]["evidence_locator"]["pdf_page_index"] = 9999
        cases["nonexistent_page"] = wrong_page

        visual = self._valid_scientific_rows()
        visual[0]["claims"][0]["evidence_modality"] = "FIGURE"
        cases["visual_without_component_locator"] = visual

        unbound = self._valid_scientific_rows()
        unbound[0]["claims"][0].update({"product_id": None, "reaction_entry": None, "conditions_as_reported": None, "metric_type": "not_applicable", "value_as_reported": None, "unit_as_reported": None})
        cases["numeric_without_binding"] = unbound

        wrong_ee = self._valid_scientific_rows()
        wrong_ee[0]["claims"][0].update({"metric_type": "ee", "unit_as_reported": "hours", "normalized_value_candidate": "99:1 er", "normalized_metric_type": "er"})
        cases["ee_wrong_unit_and_normalization"] = wrong_ee

        calibration_task = self._tasks(self.calibration)[0]
        calibration_row = {
            "source_unit_id": calibration_task["source_unit_id"],
            "source_unit_status": "COMPLETED",
            "input_manifest_hash": self._manifest_hash(self.calibration),
            "task_hash": calibration_task["task_hash"],
            **self._coverage(calibration_task),
            "claims": [{**self._claim(calibration_task), "evidence_locator": {**self._claim(calibration_task)["evidence_locator"], "printed_page_label_observed": "wrong-label"}}],
        }

        for name, rows in cases.items():
            with self.subTest(name=name):
                completed = self._finalize(self.scientific, rows)
                self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertFalse((self.scientific / "output/OUTPUT_MANIFEST.json").exists())
        completed = self._finalize(self.calibration, [calibration_row])
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_valid_populated_partial_unreadable_and_conflict_rows_finalize(self) -> None:
        rows = self._valid_scientific_rows()
        rows[0]["source_unit_status"] = "PARTIAL"
        rows[0].update(self._partial_coverage(self._tasks()[0]))
        rows[1]["source_unit_status"] = "SOURCE_UNREADABLE"
        rows[1]["status_reason"] = "Synthetic source could not be decoded."
        rows[1]["coverage_summary"] = "Open attempt recorded; no pages were readable."
        rows[1]["pages_examined"] = []
        rows[1]["sections_examined"] = []
        rows[1]["claims"] = []

        conflict_claim = self._claim(self._tasks()[5])
        locator = conflict_claim["evidence_locator"]
        conflict_claim.update(
            {
                "claim_type": "source_conflict",
                "metric_type": "not_applicable",
                "value_as_reported": None,
                "unit_as_reported": None,
                "normalized_value_candidate": None,
                "normalized_metric_type": None,
                "normalization_rule": None,
                "normalization_source_supported": False,
                "source_conflict_detected": True,
                "source_conflict": {
                    "conflict_type": "SOURCE_INTERNAL_LABEL_CONFLICT",
                    "alternatives": [
                        {"reported_value": "label-alpha", "locator": locator},
                        {"reported_value": "label-beta", "locator": {**locator, "table_id": "Table synthetic"}},
                    ],
                },
            }
        )
        rows[5]["claims"] = [conflict_claim]
        completed = self._finalize(self.scientific, rows)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue((self.scientific / "output/OUTPUT_MANIFEST.json").is_file())

    def test_no_qualifying_evidence_requires_full_coverage(self) -> None:
        rows = self._valid_scientific_rows()
        for row in rows[1:]:
            row.update(
                {
                    "source_unit_status": "NO_QUALIFYING_EVIDENCE",
                    "coverage_summary": "Synthetic empty coverage bypass.",
                    "pages_examined": [],
                    "sections_examined": [],
                    "status_reason": "No qualifying evidence was reported.",
                    "claims": [],
                }
            )
        completed = self._finalize(self.scientific, rows)
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_full_coverage_no_qualifying_evidence_is_valid(self) -> None:
        rows = self._valid_scientific_rows()
        for index, row in enumerate(rows[1:], start=1):
            task = self._tasks()[index]
            row.update(
                {
                    "source_unit_status": "NO_QUALIFYING_EVIDENCE",
                    "coverage_summary": "Every required page was inspected without finding a qualifying claim.",
                    "pages_examined": copy.deepcopy(task["completion_criteria"]["required_page_indices"]),
                    "sections_examined": ["PAGE_ONLY_COVERAGE_COMPLETE"],
                    "status_reason": "No qualifying evidence was reported after complete inspection.",
                    "claims": [],
                }
            )
        completed = self._finalize(self.scientific, rows)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_partial_claim_locator_must_be_examined(self) -> None:
        rows = self._valid_scientific_rows()
        task = self._tasks()[0]
        rows[0]["source_unit_status"] = "PARTIAL"
        rows[0].update(self._partial_coverage(task))
        last_page = task["completion_criteria"]["required_page_indices"][0]["page_indices"][-1]
        rows[0]["claims"][0]["evidence_locator"].update(
            {
                "pdf_page_index": last_page,
                "printed_page_label_observed": task["printed_page_labels"]["F3I_MAIN"][str(last_page)],
            }
        )
        completed = self._finalize(self.scientific, rows)
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_conflict_alternative_locator_must_be_examined(self) -> None:
        rows = self._valid_scientific_rows()
        task = self._tasks()[5]
        rows[5]["source_unit_status"] = "PARTIAL"
        rows[5].update(self._partial_coverage(task))
        claim = self._as_nonnumeric(self._claim(task))
        claim.update({"claim_type": "source_conflict", "source_conflict_detected": True})
        first_locator = copy.deepcopy(claim["evidence_locator"])
        last_page = task["completion_criteria"]["required_page_indices"][0]["page_indices"][-1]
        last_locator = {
            **first_locator,
            "pdf_page_index": last_page,
            "printed_page_label_observed": task["printed_page_labels"]["P403_SI"][str(last_page)],
            "table_id": "Table synthetic",
        }
        claim["source_conflict"] = {
            "conflict_type": "SOURCE_INTERNAL_LABEL_CONFLICT",
            "alternatives": [
                {"reported_value": "label-alpha", "locator": first_locator},
                {"reported_value": "label-beta", "locator": last_locator},
            ],
        }
        rows[5]["claims"] = [claim]
        completed = self._finalize(self.scientific, rows)
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_honest_partial_claim_on_examined_page_is_valid(self) -> None:
        rows = self._valid_scientific_rows()
        rows[0]["source_unit_status"] = "PARTIAL"
        rows[0].update(self._partial_coverage(self._tasks()[0]))
        completed = self._finalize(self.scientific, rows)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_f3i_review_mechanism_is_representable(self) -> None:
        task = self._tasks()[0]
        mechanism_rows = self._valid_scientific_rows()
        mechanism = self._as_nonnumeric(self._claim(task))
        mechanism.update(
            {
                "claim_type": "author_proposed_mechanism",
                "reaction_stage": "mechanistic_observation",
                "epistemic_class": "REVIEW_ARTICLE_SUMMARY",
                "pathway_status": "AUTHOR_PROPOSED",
                "directness": "AUTHOR_INTERPRETATION",
            }
        )
        mechanism_rows[0]["claims"] = [mechanism]
        mechanism_result = self._finalize(self.scientific, mechanism_rows)
        self.assertEqual(mechanism_result.returncode, 0, mechanism_result.stdout + mechanism_result.stderr)

    def test_f3i_qualitative_scope_is_representable(self) -> None:
        task = self._tasks()[0]
        scope_rows = self._valid_scientific_rows()
        scope = self._as_nonnumeric(self._claim(task))
        scope.update({"claim_type": "scope_result", "epistemic_class": "REVIEW_ARTICLE_SUMMARY", "pathway_status": "NOT_APPLICABLE"})
        scope_rows[0]["claims"] = [scope]
        scope_result = self._finalize(self.scientific, scope_rows)
        self.assertEqual(scope_result.returncode, 0, scope_result.stdout + scope_result.stderr)

    def test_mechanism_source_identity_stage_is_rejected(self) -> None:
        mechanism_rows = self._valid_scientific_rows()
        mechanism = self._as_nonnumeric(self._claim(self._tasks()[4]))
        mechanism.update(
            {
                "claim_type": "author_proposed_mechanism",
                "reaction_stage": "source_identity",
                "epistemic_class": "AUTHOR_PROPOSED_MECHANISM",
                "pathway_status": "AUTHOR_PROPOSED",
                "directness": "AUTHOR_INTERPRETATION",
            }
        )
        mechanism_rows[4]["claims"] = [mechanism]
        mechanism_result = self._finalize(self.scientific, mechanism_rows)
        self.assertNotEqual(mechanism_result.returncode, 0, mechanism_result.stdout + mechanism_result.stderr)

    def test_arbitrary_ratio_normalization_is_rejected(self) -> None:
        ratio_rows = self._valid_scientific_rows()
        ratio_rows[4]["claims"][0].update(
            {
                "metric_type": "er",
                "value_as_reported": "95:5 er",
                "unit_as_reported": "er",
                "normalized_value_candidate": "50:50 er",
                "normalized_metric_type": "er",
                "normalization_rule": "Canonicalize the reported ratio.",
                "normalization_source_supported": True,
            }
        )
        ratio_result = self._finalize(self.scientific, ratio_rows)
        self.assertNotEqual(ratio_result.returncode, 0, ratio_result.stdout + ratio_result.stderr)

    def test_equivalent_er_and_dr_normalizations_are_valid(self) -> None:
        for metric in ("er", "dr"):
            with self.subTest(metric=metric):
                ratio_rows = self._valid_scientific_rows()
                ratio_rows[4]["claims"][0].update(
                    {
                        "metric_type": metric,
                        "value_as_reported": f"95:5 {metric}",
                        "unit_as_reported": metric,
                        "normalized_value_candidate": "95:5",
                        "normalized_metric_type": metric,
                        "normalization_rule": "Canonicalize spacing while preserving ordered components.",
                        "normalization_source_supported": True,
                    }
                )
                ratio_result = self._finalize(self.scientific, ratio_rows)
                self.assertEqual(ratio_result.returncode, 0, ratio_result.stdout + ratio_result.stderr)

    def test_calibration_rejects_gold_plus_disguised_forbidden_extra(self) -> None:
        task = self._tasks(self.calibration)[0]
        gold = self._calibration_gold_claim(task)
        extra = self._claim(task, sequence=2)
        extra.update({"claim_type": "explicit_limitation", "reaction_stage": "target_catalytic_reaction"})
        row = {
            "source_unit_id": task["source_unit_id"],
            "source_unit_status": "COMPLETED",
            "input_manifest_hash": self._manifest_hash(self.calibration),
            "task_hash": task["task_hash"],
            **self._coverage(task),
            "claims": [gold, extra],
        }
        finalized = self._finalize(self.calibration, [row])
        report = evaluate_v3_1_calibration(Path(self.result["run_root"]))
        self.assertTrue(
            finalized.returncode != 0 and report["status"] == "FAIL",
            {"finalizer_returncode": finalized.returncode, "finalizer_stdout": finalized.stdout, "evaluator": report},
        )

    def test_stage_epistemic_and_conflict_conflations_are_rejected(self) -> None:
        task = self._tasks()[3]
        base = self._valid_scientific_rows()
        mutations = []

        substrate = self._claim(self._tasks()[6])
        substrate.update({"reaction_stage": "target_catalytic_reaction"})
        mutations.append(substrate)

        intermediate = self._claim(task)
        intermediate.update(
            {
                "claim_type": "intermediate_isolation_result",
                "reaction_stage": "intermediate_isolation",
                "epistemic_class": "INTERMEDIATE_ISOLATION",
                "pathway_status": "EXPERIMENTALLY_OBSERVED",
            }
        )
        mutations.append(intermediate)

        proposed = self._claim(self._tasks()[4])
        proposed.update(
            {
                "claim_type": "author_proposed_mechanism",
                "metric_type": "not_applicable",
                "value_as_reported": None,
                "unit_as_reported": None,
                "normalized_value_candidate": None,
                "normalized_metric_type": None,
                "normalization_rule": None,
                "normalization_source_supported": False,
                "epistemic_class": "EXPERIMENTAL_MECHANISTIC_OBSERVATION",
                "pathway_status": "EXPERIMENTALLY_OBSERVED",
            }
        )
        mutations.append(proposed)

        collapsed = self._claim(self._tasks()[5])
        collapsed.update(
            {
                "claim_type": "source_conflict",
                "metric_type": "not_applicable",
                "value_as_reported": None,
                "unit_as_reported": None,
                "normalized_value_candidate": None,
                "normalized_metric_type": None,
                "normalization_rule": None,
                "normalization_source_supported": False,
                "source_conflict_detected": False,
                "source_conflict": None,
            }
        )
        mutations.append(collapsed)

        row_indices = [6, 3, 4, 5]
        for index, claim in zip(row_indices, mutations):
            rows = copy.deepcopy(base)
            rows[index]["claims"] = [claim]
            completed = self._finalize(self.scientific, rows)
            self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_calibration_evaluator_uses_private_gold_and_rejects_wrong_fields(self) -> None:
        task = self._tasks(self.calibration)[0]
        claim = self._calibration_gold_claim(task)
        row = {
            "source_unit_id": task["source_unit_id"],
            "source_unit_status": "COMPLETED",
            "input_manifest_hash": self._manifest_hash(self.calibration),
            "task_hash": task["task_hash"],
            **self._coverage(task),
            "claims": [claim],
        }
        completed = self._finalize(self.calibration, [row])
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = evaluate_v3_1_calibration(Path(self.result["run_root"]))
        self.assertEqual(report["status"], "PASS", report)

        row["claims"][0]["product_id"] = "wrong-compound"
        completed = self._finalize(self.calibration, [row])
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = evaluate_v3_1_calibration(Path(self.result["run_root"]))
        self.assertEqual(report["status"], "FAIL")

    def test_calibration_evaluator_canonicalizes_compound_label_and_percent_value(self) -> None:
        private_path = Path(self.result["run_root"]) / "coordinator/private_calibration.json"
        original_private = private_path.read_text(encoding="utf-8")
        private = json.loads(original_private)
        private["expected"].update({"product_id": "2d", "value_as_reported": "54%", "unit_as_reported": "%"})
        private_path.write_text(json.dumps(private, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            for value in (54, 54.0, "54"):
                with self.subTest(value=value):
                    claim = self._calibration_gold_claim(self._tasks(self.calibration)[0])
                    claim.update(
                        {
                            "product_id": "5-(synthetic-name)-oxazolidine-2,4-dione (2D)",
                            "value_as_reported": value,
                            "normalized_value_candidate": None,
                            "normalized_metric_type": None,
                            "normalization_rule": None,
                            "normalization_source_supported": False,
                        }
                    )
                    finalized, report = self._finalize_and_evaluate_calibration([claim])
                    self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
                    self.assertEqual(report["status"], "PASS", report)
                    self.assertEqual(report["match_count"], 1, report)
        finally:
            private_path.write_text(original_private, encoding="utf-8")

    def test_calibration_evaluator_rejects_near_labels_wrong_value_locator_and_stage(self) -> None:
        private_path = Path(self.result["run_root"]) / "coordinator/private_calibration.json"
        original_private = private_path.read_text(encoding="utf-8")
        private = json.loads(original_private)
        private["expected"].update({"product_id": "2d", "value_as_reported": "54%", "unit_as_reported": "%"})
        private_path.write_text(json.dumps(private, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            task = self._tasks(self.calibration)[0]
            cases = []
            for product_id in ("2e", "12d"):
                claim = self._calibration_gold_claim(task)
                claim.update({"product_id": product_id, "value_as_reported": 54, "normalized_value_candidate": 54})
                cases.append((f"product-{product_id}", claim))
            wrong_value = self._calibration_gold_claim(task)
            wrong_value.update({"product_id": "2d", "value_as_reported": 55, "normalized_value_candidate": 55})
            cases.append(("wrong-value", wrong_value))
            wrong_stage = self._calibration_gold_claim(task)
            wrong_stage.update({"product_id": "2d", "value_as_reported": 54, "normalized_value_candidate": 54, "reaction_stage": "target_catalytic_reaction"})
            cases.append(("wrong-stage", wrong_stage))
            wrong_label = self._calibration_gold_claim(task)
            wrong_label.update({"product_id": "2d", "value_as_reported": 54, "normalized_value_candidate": 54})
            wrong_label["evidence_locator"]["printed_page_label_observed"] = "wrong-label"
            cases.append(("wrong-printed-label", wrong_label))
            wrong_page = self._calibration_gold_claim(task)
            wrong_page.update({"product_id": "2d", "value_as_reported": 54, "normalized_value_candidate": 54})
            wrong_page["evidence_locator"]["pdf_page_index"] += 1
            cases.append(("wrong-page", wrong_page))
            for name, claim in cases:
                with self.subTest(name=name):
                    _, report = self._finalize_and_evaluate_calibration([claim])
                    self.assertEqual(report["status"], "FAIL", report)
        finally:
            private_path.write_text(original_private, encoding="utf-8")

    def test_calibration_evaluator_rejects_gold_plus_extra_quantitative_claim(self) -> None:
        task = self._tasks(self.calibration)[0]
        gold = self._calibration_gold_claim(task)
        extra = self._calibration_gold_claim(task, sequence=2)
        extra.update({"product_id": "extra-compound", "value_as_reported": 62, "normalized_value_candidate": 62})
        _, report = self._finalize_and_evaluate_calibration([gold, extra])
        self.assertEqual(report["status"], "FAIL", report)

    def test_private_gold_stores_percentage_as_a_numeric_value(self) -> None:
        private = json.loads((Path(self.result["run_root"]) / "coordinator/private_calibration.json").read_text(encoding="utf-8"))
        self.assertEqual(private["expected"]["value_as_reported"], 61)
        self.assertEqual(private["expected"]["unit_as_reported"], "%")

    def test_v3_1_1_run_uses_new_checkpoint_and_empty_outputs(self) -> None:
        external = self.base / "external-v3-1-1"
        result = prepare_v3_1_workspaces(
            repo_root=self.repo,
            workspace_parent=external,
            run_id="phase8_source_first_v3_1_1_20260713T020304Z",
            sources=self.sources,
            identity_audits=self.audits,
            human_events=[self.event],
            repo_head="feedface",
            branch="feature",
            pr_number=3,
            random_seed=80423,
            instruction_sources=[],
            source_metadata=self.source_metadata,
            pdf_slice_writer=self._fixture_slice_writer,
        )
        self.assertEqual(result["schema_version"], "3.1.1")
        self.assertEqual(result["stage"], "PREPARED_FOR_SOURCE_FIRST_LAYER_A_V3_1_1")
        for key in ("layerA_inventory_workspace", "calibration_layerA_workspace"):
            workspace = Path(result[key])
            self.assertEqual(list((workspace / "output").iterdir()), [])
            manifest = json.loads((workspace / "INPUT_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "3.1.1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
