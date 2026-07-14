#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase8.phase8b_salvage import (  # noqa: E402
    build_issue_reclassification,
    prepare_salvage_run,
    salvage_attempt2,
    validate_salvaged_payload,
)


def final_row(
    claim_id: str,
    paper_id: str,
    *,
    evidence: str,
    metric: str = "not_applicable",
    value: object = None,
    unit: str | None = None,
    product: str | None = None,
    disposition: str = "AI_SUPPORTED",
) -> dict:
    return {
        "claim_id": claim_id,
        "final_disposition": disposition,
        "final_claim": {
            "claim_id": claim_id,
            "paper_id": paper_id,
            "source_document_id": f"{paper_id}_MAIN",
            "claim_type": "source_conflict" if disposition == "SOURCE_CONFLICT_RETAINED" else "scope_result",
            "reaction_stage": "target_catalytic_reaction",
            "reaction_entry": "representative entry",
            "substrate_ids": ["substrate A"],
            "reagent_or_partner_ids": ["Pd catalyst"],
            "product_id": product,
            "intermediate_id": None,
            "conditions_as_reported": None,
            "metric_type": metric,
            "value_as_reported": value,
            "unit_as_reported": unit,
            "short_evidence": evidence,
            "source_conflict_detected": disposition == "SOURCE_CONFLICT_RETAINED",
            "source_conflict": (
                {"alternatives": [{"value": "A"}, {"value": "B"}]}
                if disposition == "SOURCE_CONFLICT_RETAINED"
                else None
            ),
        },
    }


def final_rows() -> list[dict]:
    rows = [
        final_row("C-REVIEW", "F3I", evidence="The review identifies selectivity as a persistent limitation."),
        final_row("C-YIELD", "F47A", evidence="Allene 3am was isolated in 75% yield.", metric="isolated_yield", value=75, unit="%", product="allene 3am"),
        final_row("C-EE", "F47A", evidence="Allene 3am was obtained in 89% ee.", metric="ee", value=89, unit="% ee", product="allene 3am"),
        final_row("C-84", "F47A", evidence="Complex 5 was isolated in 84% yield.", metric="isolated_yield", value=84, unit="%", product="complex 5"),
        final_row("C-74", "F47A", evidence="The SI reports 3an in 74% isolated yield with DBA.", metric="isolated_yield", value=74, unit="%", product="3an"),
        final_row("C-62", "F47A", evidence="The SI reports 3an in 62% isolated yield without DBA.", metric="isolated_yield", value=62, unit="%", product="3an"),
        final_row("C-CO2", "P403", evidence="The authors propose carbon-dioxide extrusion from the intermediate."),
        final_row("C-L19", "P403", evidence="Ligand L19 gave 3aa in 80% isolated yield.", metric="isolated_yield", value=80, unit="%", product="3aa"),
        final_row("C-L6-Y", "P403", evidence="Ligand L6 gave 3aa in 90% isolated yield.", metric="isolated_yield", value=90, unit="%", product="3aa"),
        final_row("C-L6-EE", "P403", evidence="Ligand L6 gave 3aa in 90% ee.", metric="ee", value=90, unit="% ee", product="3aa"),
    ]
    index = 1
    while len(rows) < 37:
        paper = ("F3I", "F47A", "P403")[index % 3]
        rows.append(final_row(f"C-FILL-{index:02d}", paper, evidence=f"Supported statement {index}."))
        index += 1
    for conflict_index in range(7):
        rows.append(
            final_row(
                f"C-CONFLICT-{conflict_index + 1}",
                "P403",
                evidence="Conflicting source labels.",
                disposition="SOURCE_CONFLICT_RETAINED",
            )
        )
    return rows


def raw_attempt() -> dict:
    sentences = [
        {
            "sentence_id": "S1",
            "text": "Selectivity remains challenging.",
            "supporting_claim_ids": ["C-REVIEW"],
            "source_paper_ids": ["F3I"],
            "numeric_citation_ids": [1],
            "factual_bindings": [],
        },
        {
            "sentence_id": "S2",
            "text": "A review-level synthesis identifies selectivity as a persistent limitation [8].",
            "supporting_claim_ids": ["C-REVIEW"],
            "source_paper_ids": ["F3I"],
            "numeric_citation_ids": [8],
            "factual_bindings": [],
        },
        {
            "sentence_id": "S11",
            "text": "Allene 3am was isolated in 75% yield [12].",
            "supporting_claim_ids": ["C-YIELD"],
            "source_paper_ids": ["F47A"],
            "numeric_citation_ids": [12],
            "factual_bindings": [],
        },
        {
            "sentence_id": "S12",
            "text": "Allene 3am was isolated in 75% yield and 89% ee [12,13].",
            "supporting_claim_ids": ["C-YIELD", "C-EE"],
            "source_paper_ids": ["F47A"],
            "numeric_citation_ids": [12, 13],
            "factual_bindings": [],
        },
        {
            "sentence_id": "S13",
            "text": "Complex 5 was isolated in 84% yield and converted in 74-76% yield depending on DBA [14,15,16].",
            "supporting_claim_ids": ["C-84", "C-74", "C-62"],
            "source_paper_ids": ["F47A"],
            "numeric_citation_ids": [14, 15, 16],
            "factual_bindings": [],
        },
        {
            "sentence_id": "S15",
            "text": "Ligand L6 gave 3aa in 90% yield and 90% ee [18,19].",
            "supporting_claim_ids": ["C-L6-Y", "C-L6-EE"],
            "source_paper_ids": ["P403"],
            "numeric_citation_ids": [18, 19],
            "factual_bindings": [],
        },
        {
            "sentence_id": "S16",
            "text": "Ligand L19 gave 3aa in 80% yield [20].",
            "supporting_claim_ids": ["C-L19"],
            "source_paper_ids": ["P403"],
            "numeric_citation_ids": [20],
            "factual_bindings": [],
        },
        {
            "sentence_id": "S19",
            "text": "The authors propose CO2 extrusion from the intermediate [25].",
            "supporting_claim_ids": ["C-CO2"],
            "source_paper_ids": ["P403"],
            "numeric_citation_ids": [25],
            "factual_bindings": [],
        },
    ]
    paragraphs = [
        {"paragraph_id": "P1", "text": " ".join(row["text"] for row in sentences[:2])},
        {"paragraph_id": "P2", "text": " ".join(row["text"] for row in sentences[2:5])},
        {"paragraph_id": "P3", "text": " ".join(row["text"] for row in sentences[5:])},
    ]
    return {
        "section_title": "Representative strategies for asymmetric allene synthesis",
        "section_outline": ["Review synthesis", "Primary results", "Mechanistic interpretation"],
        "selected_claim_ids": [row["claim_id"] for row in final_rows() if row["final_disposition"] != "SOURCE_CONFLICT_RETAINED"],
        "paragraphs": paragraphs,
        "sentences": sentences,
        "citation_order": list(range(1, 26)),
        "omitted_claims_and_reasons": [],
    }


class Phase8BSalvageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = final_rows()
        self.raw = raw_attempt()
        self.salvage = salvage_attempt2(self.raw, self.rows)

    def test_deterministic_salvage_fixes_citations_selected_union_duplicates_and_s13(self) -> None:
        payload = self.salvage["payload"]
        sentence_by_id = {row["sentence_id"]: row for row in payload["sentences"]}
        self.assertNotIn("S1", sentence_by_id)
        self.assertNotIn("S11", sentence_by_id)
        self.assertNotIn("76%", sentence_by_id["S13"]["text"])
        self.assertNotIn("74-76", sentence_by_id["S13"]["text"])
        self.assertIn("84%", sentence_by_id["S13"]["text"])
        self.assertIn("74%", sentence_by_id["S13"]["text"])
        self.assertIn("62%", sentence_by_id["S13"]["text"])
        self.assertEqual(sentence_by_id["S13"]["numeric_citation_ids"], [2])
        self.assertTrue(sentence_by_id["S13"]["text"].endswith("[2]."))
        self.assertNotEqual(sentence_by_id["S15"]["supporting_claim_ids"], sentence_by_id["S16"]["supporting_claim_ids"])
        support_union = sorted({claim_id for row in payload["sentences"] for claim_id in row["supporting_claim_ids"]})
        self.assertEqual(payload["selected_claim_ids"], support_union)
        self.assertEqual(payload["citation_order"], [
            {"citation_id": 1, "paper_id": "F3I"},
            {"citation_id": 2, "paper_id": "F47A"},
            {"citation_id": 3, "paper_id": "P403"},
        ])

    def test_all_legacy_numeric_citations_are_rewritten_but_reaction_notation_is_preserved(self) -> None:
        raw = raw_attempt()
        sentence = next(row for row in raw["sentences"] if row["sentence_id"] == "S2")
        sentence["text"] = "A review discusses [2+2] chemistry [7] and a persistent limitation [8]."
        raw["paragraphs"][0]["text"] = " ".join(row["text"] for row in raw["sentences"][:2])
        salvage = salvage_attempt2(raw, self.rows)
        text = next(row["text"] for row in salvage["payload"]["sentences"] if row["sentence_id"] == "S2")
        self.assertIn("[2+2]", text)
        self.assertNotIn("[7]", text)
        self.assertNotIn("[8]", text)
        self.assertEqual(text.count("[1]"), 1)

    def test_alias_normalization_and_warnings_do_not_block(self) -> None:
        report = validate_salvaged_payload(self.salvage["payload"], self.rows)
        self.assertEqual(report["status"], "PASS", report["blockers"])
        self.assertEqual(report["blocker_count"], 0)
        self.assertIn("CO2_EQUIVALENT_TO_CARBON_DIOXIDE", report["aliases_applied"])
        self.assertIsInstance(report["warnings"], list)

    def test_unsupported_number_entity_conflict_and_wrong_paper_are_blockers(self) -> None:
        payload = json.loads(json.dumps(self.salvage["payload"]))
        sentence = next(row for row in payload["sentences"] if row["sentence_id"] == "S12")
        sentence["text"] = sentence["text"].replace("75%", "55%") + " RuCl3"
        sentence["supporting_claim_ids"].append("C-CONFLICT-1")
        sentence["source_paper_ids"] = ["P403"]
        report = validate_salvaged_payload(payload, self.rows)
        codes = {row["code"] for row in report["blockers"]}
        self.assertIn("UNSUPPORTED_SCIENTIFIC_NUMBER", codes)
        self.assertIn("UNSUPPORTED_CHEMICAL_ENTITY", codes)
        self.assertIn("SOURCE_CONFLICT_CLAIM_IN_PROSE", codes)
        self.assertIn("CITATION_WRONG_PAPER", codes)

    def test_old_validator_issues_are_reclassified(self) -> None:
        old_report = {
            "issues": [
                {"code": "INVALID_FACTUAL_BINDING", "sentence_id": "S2"},
                {"code": "REVIEW_EPISTEMIC_FRAME_MISSING", "sentence_id": "S2"},
                {"code": "UNSUPPORTED_NUMBER", "sentence_id": "S13"},
                {"code": "UNSUPPORTED_ENTITY", "sentence_id": "S19", "message": "CO2"},
                {"code": "CITATION_PAPER_MISMATCH", "sentence_id": "S12"},
            ]
        }
        report = build_issue_reclassification(old_report, self.raw, self.rows)
        categories = {row["original_code"]: row["category"] for row in report["items"]}
        self.assertEqual(categories["INVALID_FACTUAL_BINDING"], "AUTO_FIX")
        self.assertEqual(categories["REVIEW_EPISTEMIC_FRAME_MISSING"], "WARNING")
        self.assertEqual(categories["UNSUPPORTED_NUMBER"], "BLOCKER")
        self.assertEqual(categories["UNSUPPORTED_ENTITY"], "AUTO_FIX")
        self.assertEqual(categories["CITATION_PAPER_MISMATCH"], "AUTO_FIX")

    def test_writer_creates_closed_salvage_package(self) -> None:
        validation = validate_salvaged_payload(self.salvage["payload"], self.rows)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "phase8b_grounded_vertical_slice_v2_salvaged_20260714T010203Z"
            result = prepare_salvage_run(
                run_root=root,
                original_payload=self.raw,
                salvage=self.salvage,
                validation=validation,
                issue_reclassification={"items": [], "counts": {}},
                citation_metadata={
                    "F3I": {"title": "Review", "authors": ["A"], "year": 2012, "journal": "J1", "doi": "d1"},
                    "F47A": {"title": "Study A", "authors": ["B"], "year": 2001, "journal": "J2", "doi": "d2"},
                    "P403": {"title": "Study B", "authors": [], "year": 2025, "journal": "J3", "doi": None},
                },
                run_manifest={"run_id": root.name, "model_requests": 0},
            )
            required = {
                "revision/grounded_revision_salvaged.md",
                "revision/salvage.diff",
                "mapping/sentence_claim_map_salvaged.jsonl",
                "citations/citation_map.json",
                "reports/salvage_validation.json",
                "reports/validator_issue_reclassification.json",
                "reports/human_review_packet.md",
                "HASH_MANIFEST.sha256",
            }
            self.assertTrue(all((root / path).is_file() for path in required))
            self.assertEqual(result["stage"], "PHASE8B_SALVAGED_CANDIDATE_READY_FOR_HUMAN_REVIEW")
            self.assertEqual(result["model_requests"], 0)
            for line in (root / "HASH_MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
                digest, relative = line.split("  ", maxsplit=1)
                import hashlib

                self.assertEqual(hashlib.sha256((root / relative).read_bytes()).hexdigest(), digest)

    def test_entrypoint_has_no_model_or_network_path(self) -> None:
        script = REPO_ROOT / "scripts/phase8/salvage_phase8b_grounded_vertical_slice_v2.py"
        text = script.read_text(encoding="utf-8")
        for forbidden in (
            "--allow-network",
            "--use-qwen",
            "OpenAICompatibleProvider",
            "generate_text(",
            "chat.completions",
            "requests.",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
