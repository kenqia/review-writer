#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.v3_1_1_layer_b import (  # noqa: E402
    prepare_v3_1_1_layer_b,
    validate_layer_b_workspace,
)


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


class Phase8V311LayerBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.repo = cls.base / "repo"
        cls.repo.mkdir()
        (cls.repo / ".git").mkdir()
        cls.upstream = cls.base / "upstream-layer-a"
        cls.external = cls.base / "external"
        cls.repo_head = "a" * 40
        cls._build_upstream()
        cls.results_hash = sha256(cls.upstream / "output/results.jsonl")
        cls.input_manifest_hash = sha256(cls.upstream / "INPUT_MANIFEST.json")
        cls.result = prepare_v3_1_1_layer_b(
            repo_root=cls.repo,
            workspace_parent=cls.external,
            run_id="phase8_exact_claim_layer_b_v3_1_1_20260714T010203Z",
            layer_a_workspace=cls.upstream,
            expected_layer_a_results_sha256=cls.results_hash,
            expected_layer_a_input_manifest_hash=cls.input_manifest_hash,
            repo_head=cls.repo_head,
            branch="feature",
            pr_number=3,
            pdf_slice_writer=cls._fixture_slice_writer,
        )
        cls.workspace = Path(cls.result["layer_b_workspace"])
        cls.initial_output_empty = list((cls.workspace / "output").iterdir()) == []

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    @staticmethod
    def _fixture_slice_writer(source: Path, destination: Path, page_positions: list[int]) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes() + json.dumps(page_positions).encode())

    @classmethod
    def _claim(cls, unit_id: str, sequence: int, global_index: int) -> dict:
        page = global_index % 2
        locator = {
            "scope": "EXACT_PAGE",
            "pdf_page_index": page,
            "page_window": None,
            "printed_page_label_observed": f"S{page + 1}",
            "section": "Synthetic section",
            "table_id": None,
            "scheme_id": None,
            "figure_id": None,
            "entry_id": f"entry-{global_index}",
        }
        claim = {
            "claim_id": f"CL-{unit_id}-{sequence:03d}",
            "paper_id": "P403",
            "source_document_id": "P403_SI",
            "source_role": "SI",
            "claim_type": "target_reaction_numeric_outcome",
            "substrate_ids": [f"substrate-{global_index}"],
            "reagent_or_partner_ids": ["partner"],
            "product_id": f"product-{global_index}",
            "intermediate_id": None,
            "reaction_stage": "target_catalytic_reaction",
            "reaction_entry": f"entry-{global_index}",
            "conditions_as_reported": "Synthetic conditions.",
            "metric_type": "isolated_yield",
            "value_as_reported": 70 + global_index % 20,
            "unit_as_reported": "%",
            "normalized_value_candidate": None,
            "normalized_metric_type": None,
            "normalization_rule": None,
            "normalization_source_supported": False,
            "evidence_locator": locator,
            "short_evidence": "Synthetic exact-claim evidence.",
            "evidence_modality": "TEXT",
            "directness": "DIRECT_NUMERIC",
            "epistemic_class": "DIRECT_REPORTED_RESULT",
            "pathway_status": "NOT_APPLICABLE",
            "source_conflict_detected": False,
            "source_conflict": None,
        }
        if global_index < 7:
            claim.update(
                {
                    "claim_type": "source_conflict",
                    "metric_type": "not_applicable",
                    "value_as_reported": None,
                    "unit_as_reported": None,
                    "source_conflict_detected": True,
                    "source_conflict": {
                        "conflict_type": "SOURCE_INTERNAL_VALUE_CONFLICT",
                        "alternatives": [
                            {"reported_value": "alpha", "locator": copy.deepcopy(locator)},
                            {"reported_value": "beta", "locator": copy.deepcopy(locator)},
                        ],
                    },
                }
            )
        if global_index == 43:
            claim["evidence_locator"].update(
                {
                    "scope": "PAGE_WINDOW",
                    "pdf_page_index": 0,
                    "page_window": [0, 1],
                    "printed_page_label_observed": "S1",
                }
            )
        return claim

    @classmethod
    def _build_upstream(cls) -> None:
        rows = []
        source_units = []
        bindings = {}
        distribution = [6, 6, 6, 6, 5, 5, 5, 5]
        global_index = 0
        for row_index, claim_count in enumerate(distribution):
            unit_id = f"SU-{row_index + 1:016x}"
            artifact = f"sources/{unit_id}__P403_SI.pdf"
            source_path = cls.upstream / artifact
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(f"%PDF synthetic source unit {row_index}\n".encode())
            claims = []
            for sequence in range(1, claim_count + 1):
                claims.append(cls._claim(unit_id, sequence, global_index))
                global_index += 1
            rows.append({"source_unit_id": unit_id, "claims": claims})
            source_units.append(
                {
                    "source_unit_id": unit_id,
                    "paper_id": "P403",
                    "source_document_ids": ["P403_SI"],
                    "source_roles": {"P403_SI": "SI"},
                    "source_artifacts": {"P403_SI": artifact},
                    "printed_page_labels": {"P403_SI": {"0": "S1", "1": "S2"}},
                }
            )
            bindings[artifact] = {
                "source_document_id": "P403_SI",
                "source_role": "SI",
                "original_source_sha256": "b" * 64,
                "original_page_count": 190,
                "original_page_indices": [0, 1],
                "printed_page_labels": {"0": "S1", "1": "S2"},
                "artifact_sha256": sha256(source_path),
            }
        write_json(cls.upstream / "INPUT_MANIFEST.json", {"schema_version": "3.1.1", "package_role": "SCIENTIFIC_INVENTORY"})
        write_jsonl(cls.upstream / "input/source_units.jsonl", source_units)
        write_json(cls.upstream / "input/source_bindings.json", {"schema_version": "3.1.1", "artifacts": bindings})
        write_jsonl(cls.upstream / "output/results.jsonl", rows)
        write_json(
            cls.upstream / "output/OUTPUT_MANIFEST.json",
            {
                "schema_version": "3.1.1",
                "package_role": "SCIENTIFIC_INVENTORY",
                "input_manifest_hash": sha256(cls.upstream / "INPUT_MANIFEST.json"),
                "results_sha256": sha256(cls.upstream / "output/results.jsonl"),
                "row_count": 8,
                "claim_count": 44,
                "status": "PASS",
            },
        )

    def _tasks(self, workspace: Path | None = None) -> list[dict]:
        return read_jsonl((workspace or self.workspace) / "input/verifier_tasks.jsonl")

    def _valid_results(self) -> list[dict]:
        manifest_hash = sha256(self.workspace / "INPUT_MANIFEST.json")
        rows = []
        for task in self._tasks():
            conflict = task["claim"]["claim_type"] == "source_conflict"
            rows.append(
                {
                    "verifier_task_id": task["verifier_task_id"],
                    "claim_id": task["claim_id"],
                    "claim_hash": task["claim_hash"],
                    "task_hash": task["task_hash"],
                    "input_manifest_hash": manifest_hash,
                    "verdict": "SOURCE_CONFLICT" if conflict else "SUPPORTED",
                    "corrected_fields": None,
                    "observed_evidence_locator": copy.deepcopy(task["claim"]["evidence_locator"]),
                    "short_independent_evidence": "Synthetic independent source verification.",
                    "error_categories": ["source_conflict"] if conflict else [],
                    "source_conflict_assessment": "FAITHFULLY_RECORDED" if conflict else "NOT_APPLICABLE",
                    "risk_level": 1 if conflict else 0,
                }
            )
        return rows

    def _finalize(self, rows: list[dict], workspace: Path | None = None) -> subprocess.CompletedProcess[str]:
        target = workspace or self.workspace
        output = target / "output"
        for name in ("OUTPUT_MANIFEST.json", "OUTPUT_MANIFEST.sha256"):
            (output / name).unlink(missing_ok=True)
        write_jsonl(output / "results.jsonl", rows)
        return subprocess.run([sys.executable, str(target / "input/finalize_output.py")], cwd=target, capture_output=True, text=True)

    def test_prepare_builds_44_exact_claim_tasks_with_closed_context(self) -> None:
        tasks = self._tasks()
        manifest = json.loads((self.workspace / "INPUT_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(len(tasks), 44)
        self.assertEqual(len({task["claim_id"] for task in tasks}), 44)
        self.assertEqual(sum(task["claim"]["claim_type"] == "source_conflict" for task in tasks), 7)
        self.assertEqual(self.result["stage"], "PREPARED_FOR_EXACT_CLAIM_LAYER_B_V3_1_1")
        self.assertEqual(manifest["upstream_layer_a_results_sha256"], self.results_hash)
        self.assertEqual(manifest["upstream_layer_a_input_manifest_hash"], self.input_manifest_hash)
        self.assertEqual(manifest["repo_head"], self.repo_head)
        self.assertEqual(manifest["claim_hashes"], {task["claim_id"]: task["claim_hash"] for task in tasks})
        self.assertTrue(self.initial_output_empty)
        serialized = json.dumps(tasks, ensure_ascii=True).casefold()
        for forbidden in ("locator_scope", "private_calibration", "reviewer_note", "final_decision", "human_review_required"):
            self.assertNotIn(forbidden, serialized)
        for task in tasks:
            self.assertIn("claim", task)
            self.assertNotIn("claims", task)
            self.assertEqual(task["source_binding"]["original_page_indices"], task["allowed_original_page_indices"])
            self.assertTrue((self.workspace / task["source_artifact"]).is_file())
        report = validate_layer_b_workspace(self.workspace, repo_root=self.repo)
        self.assertEqual(report["status"], "PASS", report)

    def test_structured_evidence_locator_controls_packaged_pages(self) -> None:
        tasks = self._tasks()
        self.assertEqual(sum(task["claim"]["evidence_locator"]["scope"] == "EXACT_PAGE" for task in tasks), 43)
        self.assertEqual(sum(task["claim"]["evidence_locator"]["scope"] == "PAGE_WINDOW" for task in tasks), 1)
        window = next(task for task in tasks if task["claim"]["evidence_locator"]["scope"] == "PAGE_WINDOW")
        self.assertEqual(window["allowed_original_page_indices"], [0, 1])
        exact = next(task for task in tasks if task["claim"]["evidence_locator"]["scope"] == "EXACT_PAGE")
        self.assertEqual(exact["allowed_original_page_indices"], [exact["claim"]["evidence_locator"]["pdf_page_index"]])

    def test_workspace_validation_rejects_input_mutation_and_unexpected_file(self) -> None:
        copied = self.base / "tampered-workspace"
        shutil.copytree(self.workspace, copied)
        task_path = copied / "input/verifier_tasks.jsonl"
        os.chmod(copied / "input", 0o755)
        os.chmod(task_path, 0o644)
        tasks = read_jsonl(task_path)
        tasks[0]["claim"]["product_id"] = "tampered"
        write_jsonl(task_path, tasks)
        (copied / "input/unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        report = validate_layer_b_workspace(copied, repo_root=self.repo)
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("hash" in issue or "unexpected" in issue for issue in report["issues"]), report)

    def test_finalizer_accepts_supported_and_faithful_source_conflict_results(self) -> None:
        completed = self._finalize(self._valid_results())
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        output_manifest = json.loads((self.workspace / "output/OUTPUT_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(output_manifest["result_count"], 44)
        self.assertEqual(output_manifest["upstream_layer_a_results_sha256"], self.results_hash)

    def test_finalizer_rejects_missing_task_wrong_hash_locator_and_conflict_misuse(self) -> None:
        mutations = []
        missing = self._valid_results()[:-1]
        mutations.append(("missing-task", missing))
        wrong_hash = self._valid_results()
        wrong_hash[0]["claim_hash"] = "0" * 64
        mutations.append(("wrong-hash", wrong_hash))
        wrong_locator = self._valid_results()
        wrong_locator[0]["observed_evidence_locator"]["pdf_page_index"] = 999
        mutations.append(("wrong-locator", wrong_locator))
        conflict_on_regular = self._valid_results()
        regular_index = next(index for index, task in enumerate(self._tasks()) if task["claim"]["claim_type"] != "source_conflict")
        conflict_on_regular[regular_index].update({"verdict": "SOURCE_CONFLICT", "source_conflict_assessment": "FAITHFULLY_RECORDED", "error_categories": ["source_conflict"]})
        mutations.append(("conflict-on-regular", conflict_on_regular))
        for name, rows in mutations:
            with self.subTest(name=name):
                completed = self._finalize(rows)
                self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_finalizer_enforces_closed_output_set(self) -> None:
        (self.workspace / "output/unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        try:
            completed = self._finalize(self._valid_results())
            self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        finally:
            (self.workspace / "output/unexpected.txt").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
