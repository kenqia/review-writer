#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.v2_semantic_inputs import (
    IDENTITY_PROFILES,
    build_v2_semantic_state,
    classify_identity_text,
    prepare_v2_workspaces,
    validate_v2_workspace,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Phase8V2SemanticInputTests(unittest.TestCase):
    def test_weighted_identity_accepts_si_without_doi_and_rejects_conflicting_doi(self) -> None:
        si_text = """
        Supporting Information
        Pd-Catalyzed Asymmetric Allenylation of Secondary Phosphine Oxides
        with Enyne-Type Propargylic Carbamates for Construction of Chiral Allenyl Phosphine Oxides
        Yujie Dong, Nianci Zhang, Fazhou Yang, Hongchao Guo
        """
        si = classify_identity_text(IDENTITY_PROFILES["P403_SI"], si_text)
        self.assertIn(si["status"], {"IDENTITY_VALIDATED_STRONG", "IDENTITY_VALIDATED_PROBABLE"})
        self.assertNotIn("doi_match", si["matched_evidence"])
        wrong = classify_identity_text(
            IDENTITY_PROFILES["P403_MAIN"],
            "DACH-ZYC-Phos/Pd-Catalyzed Enantioselective Allenylation via Ligand Relay DOI 10.1021/jacs.5c07465",
        )
        self.assertEqual(wrong["status"], "IDENTITY_CONFLICT")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.evidence = self.repo / "local/phase8_evidence"
        self.external = self.base / "external"
        (self.repo / ".git").mkdir(parents=True)
        self.core, self.human, self.pages, self.audits = self._fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> tuple[list[dict], list[dict], dict[str, list[str]], dict[str, dict]]:
        source_ids = ["F3I_MAIN", "F47A_MAIN", "F47A_SI", "P403_MAIN", "P403_SI"]
        pages = {source_id: ["Target Section Table 1 compound 2d reported 61% yield."] for source_id in source_ids}
        audits = {source_id: {"source_document_id": source_id, "status": "IDENTITY_VALIDATED_STRONG", "sha256": source_id.lower().ljust(64, "0")[:64]} for source_id in source_ids}
        core = []
        for index in range(53):
            source_id = source_ids[index % len(source_ids)]
            field = ["yield", "ee", "er", "dr", "mechanism claims"][index % 5]
            item_id = f"RU-CORE-{index:02d}"
            candidate = "HUMAN_REVIEW_REQUIRED"
            if index in {40, 41}:
                candidate = "SI_VALIDATED"
                field = "SI identity/status"
            elif index in {42, 43, 44, 45, 46, 47}:
                candidate = f"{field} candidate for fixture; requires human source check"
            core.append(
                {
                    "review_item_id": item_id,
                    "field_name": field,
                    "candidate_value": candidate,
                    "source_locator": {
                        "source_document_id": source_id,
                        "pdf_page_index": 0,
                        "printed_page_label": "1",
                        "section_heading": "Target Section",
                        "table_id": "Table 1",
                        "compound_label": "2d",
                        "short_quote": "Target Section Table 1 compound 2d reported 61% yield.",
                    },
                }
            )
        human = []
        for index in range(6):
            item = core[index]
            human.append(
                {
                    "decision_id": f"human-{index}",
                    "core_review_item_id": item["review_item_id"],
                    "review_item_id": item["review_item_id"],
                    "final_decision": "edit" if index == 5 else "cannot_verify",
                    "original_value": "HUMAN_REVIEW_REQUIRED",
                    "edited_value": "61% substrate preparation yield" if index == 5 else None,
                    "classification": "substrate_preparation_yield / substrate_synthesis" if index == 5 else None,
                    "target_catalytic_reaction_relevance": "low" if index == 5 else None,
                    "source_locator": {"source_document_id": "P403_SI", "pdf_page_index": 11, "printed_page_label": "S12", "compound_label": "2d"},
                }
            )
        for offset, index in enumerate(range(6, 11), start=6):
            core[index]["review_item_id"] = f"RU-PHASE7-C{offset:02d}"
            core[index]["field_name"] = "phase7_claim"
            core[index]["source_locator"] = {"source_document_id": "PHASE7_GENERATED_SECTION", "pdf_page_index": None}
        core[11]["review_item_id"] = "RU-F3I_SI-IDENTITY"
        core[11]["field_name"] = "SI identity/status"
        core[11]["source_locator"] = {"source_document_id": "F3I_SI", "pdf_page_index": None}
        core[11]["candidate_value"] = "NO_SI_PUBLISHED_ON_OFFICIAL_PAGE"
        return core, human, pages, audits

    def test_active_set_modes_locators_atomicity_and_hidden_calibration(self) -> None:
        state = build_v2_semantic_state(
            core_items=self.core,
            human_events=self.human,
            source_pages=self.pages,
            identity_audits=self.audits,
            random_seed=80422,
        )
        self.assertEqual(len(state["active_tasks"]), 41)
        self.assertEqual(state["exclusion_counts"], {"effective_human_decision": 6, "phase7_source_unavailable": 5, "f3i_no_si_status": 1})
        self.assertEqual(state["mode_counts"], {"CANDIDATE_VERIFICATION": 2, "BLIND_DUAL_EXTRACTION": 39})
        self.assertEqual(state["preflight"]["status"], "PASS")
        self.assertTrue(all(task["reaction_stage"] for task in state["active_tasks"]))
        self.assertTrue(all(task["atomic"] for task in state["active_tasks"]))
        self.assertTrue(all(task["locator_quality"] == "EXACT_VERIFIED" for task in state["active_tasks"]))
        self.assertEqual(state["hidden_calibration"]["review_item_id"], "RU-CORE-05")
        self.assertEqual(state["hidden_calibration"]["value"], "61%")
        active_serialized = json.dumps(state["active_tasks"], sort_keys=True)
        self.assertNotIn("61% substrate preparation yield", active_serialized)
        self.assertNotIn("HUMAN_REVIEW_REQUIRED", active_serialized)

    def test_nonexact_locator_removes_precise_labels(self) -> None:
        self.pages["P403_MAIN"] = ["Different page text without the old locator evidence."]
        state = build_v2_semantic_state(
            core_items=self.core,
            human_events=self.human,
            source_pages=self.pages,
            identity_audits=self.audits,
            random_seed=80422,
        )
        tasks = [task for task in state["active_tasks"] if task["source_document_id"] == "P403_MAIN"]
        self.assertTrue(tasks)
        self.assertTrue(all(task["locator_quality"] != "EXACT_VERIFIED" for task in tasks))
        for task in tasks:
            self.assertFalse({"compound_label", "table_id", "scheme_id", "figure_id"} & set(task["locator_hint"]))

    def test_prepare_v2_packages_pass_hard_gates_and_do_not_create_layer3(self) -> None:
        state = build_v2_semantic_state(
            core_items=self.core,
            human_events=self.human,
            source_pages=self.pages,
            identity_audits=self.audits,
            random_seed=80422,
        )
        for source_id in self.pages:
            paper_id = source_id.split("_")[0]
            path = self.evidence / "sources" / paper_id / f"{source_id}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"%PDF fixture {source_id}\n".encode())
            self.audits[source_id]["sha256"] = sha256(path)
        result = prepare_v2_workspaces(
            repo_root=self.repo,
            evidence_root=self.evidence,
            workspace_parent=self.external,
            run_id="phase8_three_layer_v2_20260712T130000Z",
            semantic_state=state,
            identity_audits=self.audits,
            repo_head="deadbeef",
            branch="feature",
            pr_number=3,
            random_seed=80422,
        )
        layer1 = Path(result["layer1_workspace"])
        layer2 = Path(result["layer2_workspace"])
        self.assertEqual(validate_v2_workspace(layer1, "layer1", repo_root=self.repo)["status"], "PASS")
        self.assertEqual(validate_v2_workspace(layer2, "layer2", repo_root=self.repo)["status"], "PASS")
        tasks1 = read_jsonl(layer1 / "input/tasks.jsonl")
        tasks2 = read_jsonl(layer2 / "input/tasks.jsonl")
        self.assertEqual(len(tasks1), 41)
        self.assertEqual([row["blind_task_id"] for row in tasks1], [row["blind_task_id"] for row in tasks2])
        self.assertFalse(any("candidate_claim" in row for row in tasks1))
        dual_rows = [row for row in tasks2 if row["task_mode"] == "BLIND_DUAL_EXTRACTION"]
        self.assertTrue(dual_rows)
        self.assertFalse(any("candidate_claim" in row for row in dual_rows))
        public_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for root in (layer1, layer2)
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() != ".pdf"
        )
        self.assertNotIn("HUMAN_REVIEW_REQUIRED", public_text)
        self.assertNotIn("61% substrate preparation yield", public_text)
        for workspace in (layer1, layer2):
            self.assertTrue(workspace.joinpath("output").stat().st_mode & stat.S_IWUSR)
            self.assertFalse(workspace.joinpath("input/tasks.jsonl").stat().st_mode & stat.S_IWUSR)
        layer1.joinpath("output").chmod(0o555)
        invalid = validate_v2_workspace(layer1, "layer1", repo_root=self.repo)
        self.assertEqual(invalid["status"], "FAIL")
        self.assertIn("output directory is not owner-writable", invalid["issues"])
        self.assertFalse((Path(result["run_root"]) / "layer3_adjudicator").exists())
        self.assertEqual(result["stage"], "PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2_V2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
