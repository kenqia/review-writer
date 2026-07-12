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

from review_writer.phase8.ai_adjudication import (
    build_anonymous_layer3_inputs,
    deterministic_rule_flags,
    prepare_ab_workspaces,
    prepare_layer3_workspace,
    reconcile_ai_with_human,
    select_human_spot_checks,
    validate_layer_output,
    validate_layer3_workspace,
    validate_workspace,
    verify_manifest,
)


TARGET_ID = "RU-P403-SI-FIELD-11"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase8AIAdjudicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.external = self.base / "external"
        self.evidence = self.repo / "local/phase8_evidence"
        (self.repo / ".git").mkdir(parents=True)
        self._build_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build_fixture(self) -> None:
        sources = []
        for document_id, paper_id, role in [
            ("P403_MAIN", "P403", "MAIN"),
            ("P403_SI", "P403", "SI"),
        ]:
            path = self.evidence / "sources" / paper_id / f"{document_id}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"%PDF fixture {document_id}\n".encode())
            sources.append(
                {
                    "source_document_id": document_id,
                    "paper_id": paper_id,
                    "source_role": role,
                    "status": "SOURCE_FOUND",
                    "sha256": sha256(path),
                    "page_count": 2,
                }
            )
        write_json(self.evidence / "inventories/source_inventory.local.json", sources)
        items = [
            {
                "review_item_id": TARGET_ID,
                "atomic_extended_review_item_ids": [TARGET_ID],
                "ai_record_hash": "a" * 64,
                "field_name": "failed or low-performing substrates",
                "candidate_value": "HUMAN_REVIEW_REQUIRED",
                "source_role": "SI",
                "source_locator": {
                    "source_document_id": "P403_SI",
                    "pdf_page_index": 1,
                    "printed_page_label": "S12",
                    "section_heading": "Preparation of substrate 2d",
                    "compound_label": "2d",
                },
            },
            {
                "review_item_id": "RU-P403-MAIN-YIELD-01",
                "atomic_extended_review_item_ids": ["RU-P403-MAIN-YIELD-01"],
                "ai_record_hash": "b" * 64,
                "field_name": "yield",
                "candidate_value": "81%",
                "source_role": "MAIN",
                "source_locator": {
                    "source_document_id": "P403_MAIN",
                    "pdf_page_index": 0,
                    "printed_page_label": "1",
                    "table_id": "Table 1",
                    "entry_id": "3a",
                },
            },
        ]
        write_json(self.evidence / "review_queue/core_review_queue.json", {"items": items})
        write_json(self.evidence / "review_queue/extended_review_queue.json", {"items": items})
        write_json(
            self.evidence / "review_queue/core_to_atomic_map.json",
            {"items": [{"core_review_item_id": row["review_item_id"], "atomic_extended_review_item_ids": row["atomic_extended_review_item_ids"]} for row in items]},
        )
        decisions = []
        for index in range(1, 7):
            item_id = TARGET_ID if index == 6 else f"RU-HUMAN-{index:02d}"
            decisions.append(
                {
                    "decision_id": f"human-{index}",
                    "core_review_item_id": item_id,
                    "review_item_id": item_id,
                    "final_decision": "edit" if index == 6 else "cannot_verify",
                    "classification": "substrate_preparation_yield / substrate_synthesis" if index == 6 else None,
                }
            )
        write_jsonl(self.evidence / "review_decisions/reviewer_1.jsonl", decisions)

    def prepare(self) -> dict:
        return prepare_ab_workspaces(
            repo_root=self.repo,
            evidence_root=self.evidence,
            workspace_parent=self.external,
            run_id="phase8_three_layer_20260712T120000Z",
            repo_head="deadbeef",
            branch="feature",
            pr_number=3,
            random_seed=80421,
        )

    def test_prepare_requires_external_workspace_and_builds_blinded_packages(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            prepare_ab_workspaces(
                repo_root=self.repo,
                evidence_root=self.evidence,
                workspace_parent=self.repo / "workspaces",
                run_id="phase8_three_layer_20260712T120000Z",
                repo_head="deadbeef",
                branch="feature",
                pr_number=3,
                random_seed=80421,
            )
        result = self.prepare()
        layer1 = Path(result["layer1_workspace"])
        layer2 = Path(result["layer2_workspace"])
        self.assertFalse((layer1 / ".git").exists())
        self.assertFalse((layer2 / ".git").exists())
        self.assertFalse(any(path.is_symlink() for root in (layer1, layer2) for path in root.rglob("*")))
        tasks1 = [json.loads(line) for line in (layer1 / "input/tasks.jsonl").read_text().splitlines()]
        tasks2 = [json.loads(line) for line in (layer2 / "input/tasks.jsonl").read_text().splitlines()]
        self.assertEqual([row["blind_task_id"] for row in tasks1], [row["blind_task_id"] for row in tasks2])
        self.assertNotIn("candidate_value", tasks1[0])
        self.assertIn("candidate_claim", tasks2[0])
        self.assertTrue(all(row["blind_task_id"].startswith("BT-") for row in tasks1))
        self.assertTrue(all("P403" not in row["blind_task_id"] for row in tasks1))
        self.assertEqual(result["source_hashes_layer1"], result["source_hashes_layer2"])
        self.assertNotEqual(result["layer1_manifest_hash"], result["layer2_manifest_hash"])
        self.assertEqual(result["input_blockers"], [])
        self.assertFalse((Path(result["run_root"]) / "layer3_adjudicator").exists())
        self.assertEqual(result, self.prepare())

    def test_manifests_permissions_and_leakage_checks(self) -> None:
        result = self.prepare()
        for key, layer in [("layer1", Path(result["layer1_workspace"])), ("layer2", Path(result["layer2_workspace"]))]:
            report = validate_workspace(layer, key, repo_root=self.repo)
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(verify_manifest(layer)["valid"])
            for folder in ("sources", "input", "schemas"):
                for path in (layer / folder).rglob("*"):
                    if path.is_file():
                        self.assertFalse(path.stat().st_mode & stat.S_IWUSR)
            self.assertTrue((layer / "output").stat().st_mode & stat.S_IWUSR)
            all_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in layer.rglob("*")
                if path.is_file() and path.suffix.lower() not in {".pdf"}
            )
            self.assertNotIn(str(self.repo), all_text)
            self.assertNotIn("chain_of_thought", all_text.lower())
        layer1 = Path(result["layer1_workspace"])
        tasks = layer1 / "input/tasks.jsonl"
        os.chmod(tasks, 0o644)
        tasks.write_text(tasks.read_text() + '{"candidate_value":"LEAK"}\n', encoding="utf-8")
        os.chmod(tasks, 0o444)
        report = validate_workspace(layer1, "layer1", repo_root=self.repo)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("candidate_value" in issue for issue in report["issues"]))

    def test_output_validation_detects_input_mutation_and_requires_manifest(self) -> None:
        result = self.prepare()
        layer1 = Path(result["layer1_workspace"])
        task = json.loads((layer1 / "input/tasks.jsonl").read_text().splitlines()[0])
        output = {
            "blind_task_id": task["blind_task_id"],
            "fact_type": task["fact_category"],
            "entity_or_compound": "2d",
            "reaction_stage": "substrate_preparation",
            "value_as_reported": "54%",
            "unit_as_reported": "%",
            "normalized_value_candidate": "54%",
            "source_document_id": "P403_SI",
            "pdf_page_index": 1,
            "printed_page_label": "S12",
            "section": "Preparation of substrate 2d",
            "table_scheme_entry_compound": "2d",
            "short_evidence": "isolated as a light yellow solid, 54%",
            "directness": "TABLE_SUPPORTED",
            "source_found": True,
            "ambiguity_reason": None,
            "input_manifest_hash": result["layer1_manifest_hash"],
        }
        write_jsonl(layer1 / "output/results.jsonl", [output])
        report = validate_layer_output(layer1, "layer1")
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("OUTPUT_MANIFEST.json", " ".join(report["issues"]))
        tasks = [json.loads(line) for line in (layer1 / "input/tasks.jsonl").read_text().splitlines()]
        outputs = []
        for item in tasks:
            row = dict(output)
            row["blind_task_id"] = item["blind_task_id"]
            row["source_document_id"] = item["source_document_id"]
            outputs.append(row)
        write_jsonl(layer1 / "output/results.jsonl", outputs)
        finalized = subprocess.run(
            [sys.executable, str(layer1 / "input/finalize_output.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        self.assertEqual(validate_layer_output(layer1, "layer1")["status"], "PASS")
        self.assertEqual(validate_workspace(layer1, "layer1", repo_root=self.repo)["status"], "PASS")
        input_file = layer1 / "input/tasks.jsonl"
        os.chmod(input_file, 0o644)
        input_file.write_text(input_file.read_text() + "\n", encoding="utf-8")
        os.chmod(input_file, 0o444)
        self.assertFalse(verify_manifest(layer1)["valid"])

    def test_anonymous_mapping_is_balanced_and_private(self) -> None:
        ids = [f"BT-{index:04d}" for index in range(7)]
        rows1 = [{"blind_task_id": item, "value_as_reported": str(index)} for index, item in enumerate(ids)]
        rows2 = [{"blind_task_id": item, "verdict": "SUPPORTED", "corrected_value_candidate": str(index)} for index, item in enumerate(ids)]
        package, private = build_anonymous_layer3_inputs(rows1, rows2, random_seed=80421)
        x_from_first = sum(mapping["candidate_x_source"] == "first" for mapping in private.values())
        self.assertLessEqual(abs(x_from_first - (len(ids) - x_from_first)), 1)
        serialized = json.dumps(package, sort_keys=True).lower()
        self.assertNotIn("layer1", serialized)
        self.assertNotIn("layer2", serialized)
        self.assertNotIn("extractor", serialized)
        self.assertNotIn("verifier", serialized)
        self.assertEqual({row["blind_task_id"] for row in package}, set(ids))

    def test_prepare_layer3_workspace_is_anonymous_external_and_idempotent(self) -> None:
        result = self.prepare()
        layer1 = Path(result["layer1_workspace"])
        layer2 = Path(result["layer2_workspace"])
        tasks1 = [json.loads(line) for line in (layer1 / "input/tasks.jsonl").read_text().splitlines()]
        tasks2 = [json.loads(line) for line in (layer2 / "input/tasks.jsonl").read_text().splitlines()]
        rows1 = []
        rows2 = []
        for task1, task2 in zip(tasks1, tasks2, strict=True):
            rows1.append(
                {
                    "blind_task_id": task1["blind_task_id"],
                    "fact_type": task1["fact_category"],
                    "entity_or_compound": "2d",
                    "reaction_stage": "substrate_preparation",
                    "value_as_reported": "54%",
                    "unit_as_reported": "%",
                    "normalized_value_candidate": "54%",
                    "source_document_id": task1["source_document_id"],
                    "pdf_page_index": 1,
                    "printed_page_label": "S12",
                    "section": "Preparation of substrate 2d",
                    "table_scheme_entry_compound": "2d",
                    "short_evidence": "isolated as a light yellow solid, 54%",
                    "directness": "TABLE_SUPPORTED",
                    "source_found": True,
                    "ambiguity_reason": None,
                    "input_manifest_hash": result["layer1_manifest_hash"],
                }
            )
            rows2.append(
                {
                    "blind_task_id": task2["blind_task_id"],
                    "verdict": "MISCLASSIFIED",
                    "corrected_value_candidate": "54%",
                    "fact_type_candidate": "substrate_preparation_yield",
                    "reaction_stage_candidate": "substrate_preparation",
                    "source_document_id": task2["source_document_id"],
                    "pdf_page_index": 1,
                    "printed_page_label": "S12",
                    "section": "Preparation of substrate 2d",
                    "table_scheme_entry_compound": "2d",
                    "short_evidence": "isolated as a light yellow solid, 54%",
                    "error_categories": ["substrate_preparation_vs_target_reaction"],
                    "human_escalation_recommended": False,
                    "input_manifest_hash": result["layer2_manifest_hash"],
                }
            )
        rows1[0]["short_evidence"] = "The author rationale is stated directly in the source."
        for workspace, rows in [(layer1, rows1), (layer2, rows2)]:
            write_jsonl(workspace / "output/results.jsonl", rows)
            finalized = subprocess.run(
                [sys.executable, str(workspace / "input/finalize_output.py")],
                capture_output=True,
                text=True,
            )
            self.assertEqual(finalized.returncode, 0, finalized.stderr)
        prepared = prepare_layer3_workspace(
            repo_root=self.repo,
            run_root=Path(result["run_root"]),
            layer1_workspace=layer1,
            layer2_workspace=layer2,
            random_seed=80421,
        )
        layer3 = Path(prepared["layer3_workspace"])
        self.assertEqual(validate_layer3_workspace(layer3, repo_root=self.repo)["status"], "PASS")
        self.assertFalse((layer3 / "output/results.jsonl").exists())
        self.assertFalse((layer3 / "coordinator").exists())
        self.assertTrue((Path(result["run_root"]) / "coordinator/private_layer_mapping.json").is_file())
        package_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in layer3.rglob("*")
            if path.is_file() and path.suffix.lower() != ".pdf"
        ).lower()
        for forbidden in ("layer1", "layer2", "extractor", "verifier", "reviewer_1", "human_verified"):
            self.assertNotIn(forbidden, package_text)
        self.assertLessEqual(abs(prepared["candidate_x_from_first"] - prepared["candidate_x_from_second"]), 1)
        self.assertEqual(prepared, prepare_layer3_workspace(
            repo_root=self.repo,
            run_root=Path(result["run_root"]),
            layer1_workspace=layer1,
            layer2_workspace=layer2,
            random_seed=80421,
        ))

    def test_deterministic_rules_flag_54_percent_substrate_preparation_and_other_risks(self) -> None:
        flags = deterministic_rule_flags(
            {
                "candidate_value": "54%",
                "fact_type": "failed or low-performing substrates",
                "reaction_stage": "target_reaction",
                "yield_type": "isolated_yield",
                "source_document_id": "P403_SI",
                "pdf_page_index": 11,
                "compound_label": "2d",
                "short_evidence": "Prepared according to general procedure A and isolated as a light yellow solid in 54% yield.",
                "negative_claim": "low-performing",
            }
        )
        codes = {flag["code"] for flag in flags}
        self.assertIn("SUBSTRATE_PREPARATION_VS_TARGET_REACTION", codes)
        self.assertIn("UNSUPPORTED_NEGATIVE_CLAIM", codes)
        self.assertNotIn("SENTINEL_SCIENTIFIC_VALUE", codes)
        sentinel = deterministic_rule_flags({"candidate_value": "HUMAN_REVIEW_REQUIRED", "source_document_id": "P403_SI"})
        self.assertIn("SENTINEL_SCIENTIFIC_VALUE", {flag["code"] for flag in sentinel})
        mechanism = deterministic_rule_flags({"candidate_value": "oxidative addition occurs", "fact_type": "mechanism", "mechanism_class": "AI inference", "source_document_id": "P403_MAIN", "pdf_page_index": 1})
        self.assertIn("MECHANISM_EPISTEMIC_CLASS", {flag["code"] for flag in mechanism})

    def test_human_precedence_and_spot_check_budget(self) -> None:
        human = [json.loads(line) for line in (self.evidence / "review_decisions/reviewer_1.jsonl").read_text().splitlines()]
        ai = [
            {"core_review_item_id": TARGET_ID, "final_ai_status": "AI_ADJUDICATED_ACCEPT", "human_risk_score": 0},
            {"core_review_item_id": "RU-A", "final_ai_status": "AI_UNRESOLVED", "human_risk_score": 4, "fact_type": "mechanism"},
            {"core_review_item_id": "RU-B", "final_ai_status": "RULE_BLOCKED", "human_risk_score": 4, "fact_type": "numeric"},
            {"core_review_item_id": "RU-C", "final_ai_status": "AI_CONSENSUS_ACCEPT", "human_risk_score": 0, "fact_type": "numeric", "rules_passed": True},
            {"core_review_item_id": "RU-D", "final_ai_status": "AI_CONSENSUS_ACCEPT", "human_risk_score": 1, "fact_type": "figure", "rules_passed": True},
            {"core_review_item_id": "RU-E", "final_ai_status": "AI_ADJUDICATED_EDIT", "human_risk_score": 3, "fact_type": "negative_claim"},
        ]
        reconciled = reconcile_ai_with_human(ai, human)
        target = next(row for row in reconciled if row["core_review_item_id"] == TARGET_ID)
        self.assertTrue(target["superseded_by_human_decision"])
        queue, report = select_human_spot_checks(reconciled, human, total_budget=10, random_seed=80421)
        self.assertEqual(report["used_budget"], 6)
        self.assertEqual(report["remaining_budget_before_selection"], 4)
        self.assertLessEqual(len(queue), 4)
        self.assertLessEqual(report["used_budget"] + len(queue), 10)
        self.assertTrue(any(row["selection_reason"] == "seeded_low_risk_consensus_sample" for row in queue))
        self.assertFalse(any(row["core_review_item_id"] == TARGET_ID for row in queue))

    def test_public_schemas_exist_and_pdf_sources_are_not_tracked(self) -> None:
        schema_root = Path(__file__).resolve().parents[1] / "schemas/phase8_ai_adjudication"
        required = {
            "layer1_output.schema.json",
            "layer2_output.schema.json",
            "layer3_output.schema.json",
            "final_ai_decision.schema.json",
            "layer1_v2_output.schema.json",
            "layer2_v2_output.schema.json",
        }
        self.assertEqual(required, {path.name for path in schema_root.glob("*.schema.json")})
        for path in schema_root.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("chain_of_thought", json.dumps(schema).lower())
        tracked = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parents[1]), "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertFalse(any(path.lower().endswith((".pdf", ".si", ".supp")) for path in tracked))

    def test_public_method_state_uses_spot_checked_ai_label(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        paths = [
            repo / "scripts/phase8/build_phase8_review_package.py",
            repo / "docs/phase8/README.md",
            repo / "docs/handoff/CURRENT.md",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn("HUMAN_SPOT_CHECKED_AI_ADJUDICATION", text, path)
            self.assertNotIn("AI-assisted pre-extraction followed by single-human verification", text, path)
        makefile = (repo / "Makefile").read_text(encoding="utf-8")
        self.assertIn("phase8-ai-adjudication-check:", makefile)
        implementation = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                repo / "review_writer/phase8/ai_adjudication.py",
                repo / "scripts/phase8/coordinate_ai_adjudication.py",
            ]
        ).lower()
        forbidden_invocation = "codex" + " exec"
        self.assertNotIn(forbidden_invocation, implementation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
