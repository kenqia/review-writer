#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.v3_source_first import (  # noqa: E402
    build_adversarial_dataset,
    build_source_units,
    prepare_v3_workspace,
    validate_v3_workspace,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def scalar_values(value: object):
    if isinstance(value, dict):
        for child in value.values():
            yield from scalar_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from scalar_values(child)
    else:
        yield value


class Phase8V3SourceFirstTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.evidence = self.repo / "local/phase8_evidence"
        self.external = self.base / "external"
        (self.repo / ".git").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _v2_fixture(self) -> Path:
        run = self.base / "v2"
        mapping = {}
        tasks1 = []
        tasks2 = []
        results1 = []
        results2 = []
        for index in range(41):
            blind_id = f"BT-{index:016x}"
            mapping[blind_id] = {"review_item_id": f"RU-{index:03d}"}
            base = {
                "blind_task_id": blind_id,
                "source_document_id": "P403_SI",
                "task_mode": "BLIND_DUAL_EXTRACTION",
                "fact_type": "yield",
                "entity": "document_level",
                "reaction_stage": "target_catalytic_reaction",
                "evidence_target": "one fact",
                "locator_quality": "PAGE_WINDOW",
                "locator_hint": {"source_document_id": "P403_SI", "page_window": [0, 1]},
            }
            tasks1.append(base)
            tasks2.append(base)
            result = {
                "blind_task_id": blind_id,
                "task_mode": "BLIND_DUAL_EXTRACTION",
                "fact_type": "yield",
                "entity": "document_level",
                "reaction_stage": "target_catalytic_reaction",
                "value_as_reported": None,
                "unit_as_reported": None,
                "normalized_value_candidate": None,
                "source_document_id": "P403_SI",
                "pdf_page_index": None,
                "printed_page_label": None,
                "section": None,
                "table_scheme_entry_compound": None,
                "short_evidence": None,
                "directness": "NOT_FOUND",
                "source_found": False,
                "ambiguity_reason": "fixture",
                "input_manifest_hash": "a" * 64,
            }
            results1.append(result)
            results2.append({**result, "error_categories": []})
        write_json(run / "coordinator/private_task_mapping.json", mapping)
        write_jsonl(run / "layer1_extractor/input/tasks.jsonl", tasks1)
        write_jsonl(run / "layer2_verifier/input/tasks.jsonl", tasks2)
        write_jsonl(run / "layer1_extractor/output/results.jsonl", results1)
        write_jsonl(run / "layer2_verifier/output/results.jsonl", results2)
        return run

    def _sources(self) -> tuple[dict[str, Path], dict[str, dict]]:
        source_ids = ["F3I_MAIN", "F47A_MAIN", "F47A_SI", "P403_MAIN", "P403_SI"]
        sources = {}
        audits = {}
        for source_id in source_ids:
            paper_id = source_id.split("_")[0]
            path = self.evidence / "sources" / paper_id / f"{source_id}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"%PDF-1.4 fixture {source_id}\n".encode())
            sources[source_id] = path
            audits[source_id] = {
                "source_document_id": source_id,
                "paper_id": paper_id,
                "source_role": source_id.split("_")[1],
                "status": "IDENTITY_VALIDATED_STRONG",
                "sha256": sha256(path),
            }
        return sources, audits

    def _human_event(self) -> dict:
        return {
            "core_review_item_id": "RU-CAL-FIXTURE",
            "final_decision": "edit",
            "edited_value": "61% substrate preparation yield",
            "classification": "substrate_preparation_yield / substrate_synthesis",
            "target_catalytic_reaction_relevance": "low",
            "source_locator": {
                "source_document_id": "P403_SI",
                "pdf_page_index": 11,
                "printed_page_label": "S12",
                "compound_label": "2d",
            },
        }

    def test_adversarial_dataset_preserves_41_items_without_inventing_per_item_labels(self) -> None:
        run = self._v2_fixture()
        dataset = build_adversarial_dataset(run)
        self.assertEqual(len(dataset["items"]), 41)
        self.assertTrue(all(row["semantic_audit_label"] == "NOT_PROVIDED" for row in dataset["items"]))
        self.assertTrue(all(row["layer1_task_hash"] and row["layer2_result_hash"] for row in dataset["items"]))
        self.assertEqual(sum(dataset["aggregate_semantic_distribution"].values()), 41)
        self.assertEqual(dataset["metric_boundary"], "TASK_REJECTION_SAFETY_ONLY")

    def test_source_units_are_three_scientific_plus_one_opaque_calibration(self) -> None:
        units, private = build_source_units(
            run_id="phase8_source_first_v3_20260713T010203Z",
            human_events=[self._human_event()],
        )
        self.assertEqual(len(units), 4)
        self.assertEqual(sum(unit["locator_scope"] == "FULL_SOURCE" for unit in units), 3)
        self.assertEqual(sum(unit["locator_scope"] == "EXACT_PAGE" for unit in units), 1)
        self.assertEqual({source for unit in units for source in unit["source_document_ids"]}, {"F3I_MAIN", "F47A_MAIN", "F47A_SI", "P403_MAIN", "P403_SI"})
        public = json.dumps(units, sort_keys=True)
        self.assertNotIn("61%", public)
        self.assertNotIn("2d", set(scalar_values(units)))
        self.assertNotIn("calibration", public.casefold())
        self.assertEqual(private["gold"]["value"], "61%")
        self.assertFalse(private["gold"]["consumes_additional_human_budget"])

    def test_workspace_is_external_immutable_strict_and_has_no_layer_b_or_c(self) -> None:
        sources, audits = self._sources()
        result = prepare_v3_workspace(
            repo_root=self.repo,
            workspace_parent=self.external,
            run_id="phase8_source_first_v3_20260713T010203Z",
            sources=sources,
            identity_audits=audits,
            human_events=[self._human_event()],
            adversarial_dataset=build_adversarial_dataset(self._v2_fixture()),
            repo_head="deadbeef",
            branch="feature",
            pr_number=3,
            random_seed=80423,
        )
        workspace = Path(result["layerA_workspace"])
        report = validate_v3_workspace(workspace, repo_root=self.repo)
        self.assertEqual(report["status"], "PASS", report["issues"])
        self.assertTrue((workspace / "AGENTS.override.md").is_file())
        self.assertTrue((workspace / "input/verify_input_package.py").is_file())
        self.assertTrue((workspace / "input/validate_results.py").is_file())
        self.assertTrue((workspace / "input/finalize_output.py").is_file())
        self.assertFalse((Path(result["run_root"]) / "layerB_verifier").exists())
        self.assertFalse((Path(result["run_root"]) / "layerC_adjudicator").exists())
        self.assertTrue(workspace.joinpath("output").stat().st_mode & stat.S_IWUSR)
        self.assertFalse(workspace.joinpath("input/source_units.jsonl").stat().st_mode & stat.S_IWUSR)
        checksum = subprocess.run(["sha256sum", "-c", "INPUT_MANIFEST.sha256"], cwd=workspace, capture_output=True, text=True)
        self.assertEqual(checksum.returncode, 0, checksum.stdout + checksum.stderr)
        self.assertGreater(len(checksum.stdout.splitlines()), 2)

    def test_finalizer_enforces_coverage_schema_uniqueness_hashes_and_closed_output(self) -> None:
        sources, audits = self._sources()
        result = prepare_v3_workspace(
            repo_root=self.repo,
            workspace_parent=self.external,
            run_id="phase8_source_first_v3_20260713T010203Z",
            sources=sources,
            identity_audits=audits,
            human_events=[self._human_event()],
            adversarial_dataset=build_adversarial_dataset(self._v2_fixture()),
            repo_head="deadbeef",
            branch="feature",
            pr_number=3,
            random_seed=80423,
        )
        workspace = Path(result["layerA_workspace"])
        manifest_hash = sha256(workspace / "INPUT_MANIFEST.json")
        tasks = [json.loads(line) for line in (workspace / "input/source_units.jsonl").read_text().splitlines()]
        rows = []
        for task in tasks:
            rows.append(
                {
                    "source_unit_id": task["source_unit_id"],
                    "source_unit_status": "COMPLETED",
                    "input_manifest_hash": manifest_hash,
                    "task_hash": task["task_hash"],
                    "claims": [],
                }
            )
        write_jsonl(workspace / "output/results.jsonl", rows)
        finalize = workspace / "input/finalize_output.py"
        ok = subprocess.run([sys.executable, str(finalize)], cwd=workspace, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertTrue((workspace / "output/OUTPUT_MANIFEST.json").is_file())

        (workspace / "output/OUTPUT_MANIFEST.json").unlink()
        (workspace / "output/OUTPUT_MANIFEST.sha256").unlink()
        write_jsonl(workspace / "output/results.jsonl", rows[:-1])
        bad_coverage = subprocess.run([sys.executable, str(finalize)], cwd=workspace, capture_output=True, text=True)
        self.assertNotEqual(bad_coverage.returncode, 0)
        self.assertFalse((workspace / "output/OUTPUT_MANIFEST.json").exists())

        write_jsonl(workspace / "output/results.jsonl", rows)
        (workspace / "output/unexpected.txt").write_text("not allowed\n", encoding="utf-8")
        unexpected = subprocess.run([sys.executable, str(finalize)], cwd=workspace, capture_output=True, text=True)
        self.assertNotEqual(unexpected.returncode, 0)
        (workspace / "output/unexpected.txt").unlink()
        (workspace / "output/nested").mkdir()
        (workspace / "output/nested/unexpected.txt").write_text("not allowed\n", encoding="utf-8")
        nested_unexpected = subprocess.run([sys.executable, str(finalize)], cwd=workspace, capture_output=True, text=True)
        self.assertNotEqual(nested_unexpected.returncode, 0)
        (workspace / "output/nested/unexpected.txt").unlink()
        (workspace / "output/nested").rmdir()

        claim_task_index = 1
        claim_task = tasks[claim_task_index]
        claim = {
            "claim_id": f"CL-{claim_task['source_unit_id']}-001",
            "paper_id": claim_task["paper_id"],
            "source_document_id": claim_task["source_document_ids"][0],
            "source_role": claim_task["source_roles"][claim_task["source_document_ids"][0]],
            "claim_type": "target_reaction_numeric_outcome",
            "substrate_ids": ["substrate-fixture"],
            "reagent_or_partner_ids": ["partner-fixture"],
            "product_id": "product-fixture",
            "intermediate_id": None,
            "reaction_stage": "target_catalytic_reaction",
            "reaction_entry": "entry-fixture",
            "conditions_as_reported": "fixture conditions",
            "metric_type": "isolated_yield",
            "value_as_reported": "61%",
            "unit_as_reported": "%",
            "normalized_value_candidate": 61,
            "locator_scope": claim_task["locator_scope"],
            "pdf_page_index": 0,
            "printed_page_label_observed": "fixture-page",
            "section": "fixture section",
            "table_id": None,
            "scheme_id": None,
            "figure_id": None,
            "entry_id": "entry-fixture",
            "short_evidence": "Synthetic direct evidence for validator testing.",
            "evidence_modality": "TEXT",
            "directness": "DIRECT_NUMERIC",
            "epistemic_class": "DIRECT_REPORTED_RESULT",
            "review_relevance": "HIGH",
        }
        populated_rows = json.loads(json.dumps(rows))
        populated_rows[claim_task_index]["claims"] = [claim]
        write_jsonl(workspace / "output/results.jsonl", populated_rows)
        populated = subprocess.run([sys.executable, str(finalize)], cwd=workspace, capture_output=True, text=True)
        self.assertEqual(populated.returncode, 0, populated.stdout + populated.stderr)
        (workspace / "output/OUTPUT_MANIFEST.json").unlink()
        (workspace / "output/OUTPUT_MANIFEST.sha256").unlink()

        duplicate_rows = json.loads(json.dumps(rows))
        duplicate_rows[claim_task_index]["claims"] = [claim]
        duplicate_rows[2]["claims"] = [{**claim, "paper_id": tasks[2]["paper_id"], "source_document_id": tasks[2]["source_document_ids"][0]}]
        write_jsonl(workspace / "output/results.jsonl", duplicate_rows)
        duplicate = subprocess.run([sys.executable, str(finalize)], cwd=workspace, capture_output=True, text=True)
        self.assertNotEqual(duplicate.returncode, 0)

        wrong_hash_rows = json.loads(json.dumps(rows))
        wrong_hash_rows[0]["task_hash"] = "f" * 64
        write_jsonl(workspace / "output/results.jsonl", wrong_hash_rows)
        wrong_hash = subprocess.run([sys.executable, str(finalize)], cwd=workspace, capture_output=True, text=True)
        self.assertNotEqual(wrong_hash.returncode, 0)

        invalid_claim_rows = json.loads(json.dumps(rows))
        invalid_claim_rows[claim_task_index]["claims"] = [{**claim, "product_id": None, "reaction_entry": None}]
        write_jsonl(workspace / "output/results.jsonl", invalid_claim_rows)
        invalid_claim = subprocess.run([sys.executable, str(finalize)], cwd=workspace, capture_output=True, text=True)
        self.assertNotEqual(invalid_claim.returncode, 0)

        write_jsonl(workspace / "output/results.jsonl", rows)
        tasks_path = workspace / "input/source_units.jsonl"
        tasks_path.chmod(0o644)
        tasks_path.write_text(tasks_path.read_text() + "\n", encoding="utf-8")
        mutated = subprocess.run([sys.executable, str(finalize)], cwd=workspace, capture_output=True, text=True)
        self.assertNotEqual(mutated.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
