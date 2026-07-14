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

from review_writer.phase8.phase8b_grounded_revision_v2 import (  # noqa: E402
    build_generation_request,
    build_section_evidence_plan,
    generate_with_bounded_repair,
    prepare_vertical_slice_v2,
    validate_prose_payload,
)


def claim(
    claim_id: str,
    paper_id: str,
    *,
    claim_type: str = "scope_result",
    source_document_id: str | None = None,
    reaction_entry: str = "representative transformation",
    product_id: str | None = None,
    metric_type: str = "not_applicable",
    value: object = None,
    unit: str | None = None,
    conditions: str | None = None,
    evidence: str | None = None,
    disposition: str = "AI_SUPPORTED",
) -> dict:
    return {
        "claim_id": claim_id,
        "final_disposition": disposition,
        "final_claim": {
            "claim_id": claim_id,
            "paper_id": paper_id,
            "source_document_id": source_document_id or f"{paper_id}_MAIN",
            "source_role": "SI" if (source_document_id or "").endswith("_SI") else "MAIN",
            "claim_type": claim_type,
            "reaction_entry": reaction_entry,
            "reaction_stage": "target_catalytic_reaction",
            "substrate_ids": ["substrate A"],
            "reagent_or_partner_ids": ["Pd catalyst"],
            "product_id": product_id,
            "intermediate_id": None,
            "conditions_as_reported": conditions,
            "metric_type": metric_type,
            "value_as_reported": value,
            "unit_as_reported": unit,
            "short_evidence": evidence or f"The source reports {reaction_entry}.",
            "epistemic_class": "REVIEW_ARTICLE_SUMMARY" if paper_id == "F3I" else "PRIMARY_SOURCE",
            "source_conflict_detected": disposition == "SOURCE_CONFLICT_RETAINED",
            "source_conflict": (
                {"conflict_type": "SOURCE_INTERNAL", "alternatives": [{"value": "A"}, {"value": "B"}]}
                if disposition == "SOURCE_CONFLICT_RETAINED"
                else None
            ),
        },
    }


def build_final_rows() -> list[dict]:
    rows = [
        claim(
            "CL-F47A-YIELD",
            "F47A",
            claim_type="target_reaction_numeric_outcome",
            reaction_entry="Table 2 entry 3",
            product_id="allene 3am",
            metric_type="isolated_yield",
            value=75,
            unit="%",
            conditions="substrate A (0.50 mmol), Pd catalyst (10 mol %), 20 deg C, 24 h, CH2Cl2 (5.0 mL)",
            evidence="Table 2 entry 3 reports allene 3am in 75% isolated yield.",
        ),
        claim(
            "CL-F47A-EE",
            "F47A",
            claim_type="target_reaction_numeric_outcome",
            reaction_entry="Table 2 entry 3",
            product_id="allene 3am",
            metric_type="ee",
            value=89,
            unit="% ee",
            conditions="substrate A (0.50 mmol), Pd catalyst (10 mol %), 20 deg C, 24 h, CH2Cl2 (5.0 mL)",
            evidence="Table 2 entry 3 reports 89% ee for allene 3am.",
        ),
        claim(
            "CL-F47A-76",
            "F47A",
            claim_type="stoichiometric_result",
            reaction_entry="main-text stoichiometric experiment",
            product_id="allene 3an",
            metric_type="isolated_yield",
            value=76,
            unit="%",
            conditions="THF, 20 deg C",
            evidence="The main text reports 76% yield for conversion to 3an.",
            disposition="HUMAN_SPOT_CHECKED_CORRECTED_ACCEPT",
        ),
        claim(
            "CL-F47A-74",
            "F47A",
            source_document_id="F47A_SI",
            claim_type="stoichiometric_result",
            reaction_entry="SI stoichiometric experiment with DBA",
            product_id="allene 3an",
            metric_type="isolated_yield",
            value=74,
            unit="%",
            conditions="THF, 20 deg C, 12 h, DBA",
            evidence="The SI reports 74% isolated yield with DBA.",
        ),
        claim(
            "CL-F47A-62",
            "F47A",
            source_document_id="F47A_SI",
            claim_type="stoichiometric_result",
            reaction_entry="SI stoichiometric experiment without DBA",
            product_id="allene 3an",
            metric_type="isolated_yield",
            value=62,
            unit="%",
            conditions="THF, 20 deg C, 12 h, without DBA",
            evidence="The SI reports 62% isolated yield without DBA.",
        ),
        claim(
            "CL-P403-OPT-YIELD",
            "P403",
            claim_type="optimization_result",
            reaction_entry="Table 1 entry 23",
            product_id="3aa",
            metric_type="isolated_yield",
            value=90,
            unit="%",
            conditions="DMA/THF 1:1, 25 deg C, 24 h",
            evidence="Table 1 entry 23 reports 3aa in 90% isolated yield.",
        ),
        claim(
            "CL-P403-OPT-EE",
            "P403",
            claim_type="optimization_result",
            reaction_entry="Table 1 entry 23",
            product_id="3aa",
            metric_type="ee",
            value=90,
            unit="% ee",
            conditions="DMA/THF 1:1, 25 deg C, 24 h",
            evidence="Table 1 entry 23 reports 90% ee for 3aa.",
        ),
        claim(
            "CL-P403-CHAR-YIELD",
            "P403",
            source_document_id="P403_SI",
            claim_type="target_reaction_numeric_outcome",
            reaction_entry="characterization entry 3aa",
            product_id="3aa",
            metric_type="isolated_yield",
            value=90,
            unit="%",
            conditions="40 h",
            evidence="The characterization entry reports 3aa in 90% isolated yield.",
        ),
        claim(
            "CL-P403-PREP",
            "P403",
            source_document_id="P403_SI",
            claim_type="substrate_preparation_numeric_outcome",
            reaction_entry="substrate preparation",
            product_id="substrate 2a",
            metric_type="isolated_yield",
            value=63,
            unit="%",
            evidence="Substrate 2a was prepared in 63% isolated yield.",
        ),
    ]
    index = 1
    while len(rows) < 37:
        paper = ("F3I", "F47A", "P403")[index % 3]
        rows.append(
            claim(
                f"CL-{paper}-SYNTH-{index:02d}",
                paper,
                reaction_entry=f"synthetic strategy {index}",
                product_id=f"product {index}",
                evidence=(
                    f"The review summarizes synthetic strategy {index}."
                    if paper == "F3I"
                    else f"The primary source reports synthetic strategy {index}."
                ),
            )
        )
        index += 1
    for conflict_index in range(7):
        rows.append(
            claim(
                f"CL-CONFLICT-{conflict_index + 1}",
                "P403",
                claim_type="source_conflict",
                disposition="SOURCE_CONFLICT_RETAINED",
            )
        )
    return rows


def citation_metadata() -> dict:
    return {
        "F3I": {"title": "Review title", "authors": ["A. Reviewer"], "year": 2012, "journal": "Review Journal", "doi": "10.1/review"},
        "F47A": {"title": "Primary study A", "authors": ["B. Author"], "year": 2001, "journal": "Primary Journal", "doi": "10.1/a"},
        "P403": {"title": "Primary study B", "authors": [], "year": 2025, "journal": "Catalysis Journal", "doi": None},
    }


def valid_payload() -> dict:
    selected = {"CL-F47A-YIELD", "CL-F47A-EE"}
    omitted = [
        {
            "claim_id": row["claim_id"],
            "reason_code": "NOT_SELECTED_FOR_BOUNDED_SYNTHESIS",
        }
        for row in build_final_rows()
        if row["final_disposition"] != "SOURCE_CONFLICT_RETAINED" and row["claim_id"] not in selected
    ]
    return {
        "section_title": "Representative strategies for asymmetric allene synthesis",
        "section_outline": ["Review-level landscape", "Primary selectivity examples"],
        "selected_claim_ids": ["CL-F47A-YIELD", "CL-F47A-EE"],
        "paragraphs": [
            {"paragraph_id": "P1", "theme": "Primary selectivity examples", "sentence_ids": ["S1"]}
        ],
        "sentences": [
            {
                "sentence_id": "S1",
                "text": "A Pd-catalyzed transformation furnished allene 3am in 75% isolated yield and 89% ee [1].",
                "supporting_claim_ids": ["CL-F47A-YIELD", "CL-F47A-EE"],
                "source_paper_ids": ["F47A"],
                "numeric_citation_ids": [1],
                "factual_bindings": [
                    {"kind": "catalyst", "text": "Pd", "claim_ids": ["CL-F47A-YIELD"]},
                    {"kind": "product", "text": "allene 3am", "claim_ids": ["CL-F47A-YIELD", "CL-F47A-EE"]},
                    {"kind": "numeric_result", "text": "75%", "claim_ids": ["CL-F47A-YIELD"]},
                    {"kind": "numeric_result", "text": "89% ee", "claim_ids": ["CL-F47A-EE"]},
                ],
            }
        ],
        "citation_order": [{"citation_id": 1, "paper_id": "F47A"}],
        "omitted_claims_and_reasons": omitted,
    }


class FakeProvider:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    def generate(self, _request: dict) -> dict:
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return {
            "status": "ok",
            "content": json.dumps(payload),
            "metadata": {"model": "qwen3.7-max", "region": "cn-beijing", "usage": {"total_tokens": 100}},
        }


class Phase8BGroundedVerticalSliceV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = build_final_rows()
        self.plan = build_section_evidence_plan(self.rows)
        self.metadata = citation_metadata()

    def test_evidence_plan_accounts_for_37_and_excludes_conflicts_and_duplicates(self) -> None:
        self.assertEqual(self.plan["available_non_conflict_claim_count"], 37)
        self.assertEqual(self.plan["excluded_conflict_count"], 7)
        self.assertEqual(len(self.plan["claim_accounting"]), 44)
        self.assertEqual(
            next(cluster for cluster in self.plan["evidence_clusters"] if "CL-F47A-YIELD" in cluster["claim_ids"])["claim_ids"],
            ["CL-F47A-EE", "CL-F47A-YIELD"],
        )
        context_cluster = next(
            cluster for cluster in self.plan["evidence_clusters"] if "CL-F47A-74" in cluster["claim_ids"]
        )
        self.assertIn("CL-F47A-62", context_cluster["claim_ids"])
        self.assertNotIn("CL-F47A-76", self.plan["recommended_claim_ids"])
        self.assertNotIn("CL-P403-CHAR-YIELD", self.plan["recommended_claim_ids"])
        self.assertNotIn("CL-P403-PREP", self.plan["recommended_claim_ids"])
        self.assertTrue(all(not claim_id.startswith("CL-CONFLICT") for claim_id in self.plan["recommended_claim_ids"]))

    def test_generation_request_contains_only_37_non_conflict_claims(self) -> None:
        request = build_generation_request(
            before_section="# Before\n",
            final_rows=self.rows,
            evidence_plan=self.plan,
            citation_metadata=self.metadata,
        )
        serialized = json.dumps(request, sort_keys=True)
        self.assertEqual(len(request["final_non_conflict_claims"]), 37)
        self.assertNotIn("CL-CONFLICT-1", serialized)
        self.assertEqual(len(request["section_evidence_plan"]["claim_accounting"]), 37)

    def test_conflict_and_unsupported_number_or_entity_are_rejected(self) -> None:
        payload = valid_payload()
        payload["selected_claim_ids"].append("CL-CONFLICT-1")
        payload["sentences"][0]["supporting_claim_ids"].append("CL-CONFLICT-1")
        payload["sentences"][0]["text"] = "A RuCl3 catalyst gave allene 3am in 81% yield [1]."
        report = validate_prose_payload(payload, self.rows, self.plan, self.metadata)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("SOURCE_CONFLICT_IN_PROSE", codes)
        self.assertIn("UNSUPPORTED_NUMBER", codes)
        self.assertIn("UNSUPPORTED_ENTITY", codes)

    def test_numeric_citation_must_match_supporting_paper(self) -> None:
        payload = valid_payload()
        payload["citation_order"] = [{"citation_id": 1, "paper_id": "P403"}]
        report = validate_prose_payload(payload, self.rows, self.plan, self.metadata)
        self.assertIn("CITATION_PAPER_MISMATCH", {issue["code"] for issue in report["issues"]})

    def test_duplicate_numeric_claim_is_rejected(self) -> None:
        payload = valid_payload()
        duplicate = dict(payload["sentences"][0])
        duplicate["sentence_id"] = "S2"
        payload["sentences"].append(duplicate)
        payload["paragraphs"][0]["sentence_ids"].append("S2")
        report = validate_prose_payload(payload, self.rows, self.plan, self.metadata)
        self.assertIn("DUPLICATE_NUMERIC_RESULT", {issue["code"] for issue in report["issues"]})

    def test_plan_excluded_claim_cannot_be_selected(self) -> None:
        payload = valid_payload()
        payload["selected_claim_ids"].append("CL-P403-PREP")
        payload["omitted_claims_and_reasons"] = [
            row for row in payload["omitted_claims_and_reasons"] if row["claim_id"] != "CL-P403-PREP"
        ]
        report = validate_prose_payload(payload, self.rows, self.plan, self.metadata)
        self.assertIn("PLAN_EXCLUDED_CLAIM_SELECTED", {issue["code"] for issue in report["issues"]})

    def test_coreported_yield_and_ee_must_share_a_sentence(self) -> None:
        payload = valid_payload()
        yield_sentence = payload["sentences"][0]
        yield_sentence.update(
            {
                "text": "A Pd-catalyzed transformation furnished allene 3am in 75% isolated yield [1].",
                "supporting_claim_ids": ["CL-F47A-YIELD"],
                "factual_bindings": [
                    {"kind": "catalyst", "text": "Pd", "claim_ids": ["CL-F47A-YIELD"]},
                    {"kind": "product", "text": "allene 3am", "claim_ids": ["CL-F47A-YIELD"]},
                    {"kind": "numeric_result", "text": "75%", "claim_ids": ["CL-F47A-YIELD"]},
                ],
            }
        )
        ee_sentence = {
            "sentence_id": "S2",
            "text": "The same allene 3am was obtained in 89% ee [1].",
            "supporting_claim_ids": ["CL-F47A-EE"],
            "source_paper_ids": ["F47A"],
            "numeric_citation_ids": [1],
            "factual_bindings": [
                {"kind": "product", "text": "allene 3am", "claim_ids": ["CL-F47A-EE"]},
                {"kind": "numeric_result", "text": "89% ee", "claim_ids": ["CL-F47A-EE"]},
            ],
        }
        payload["sentences"].append(ee_sentence)
        payload["paragraphs"][0]["sentence_ids"].append("S2")
        report = validate_prose_payload(payload, self.rows, self.plan, self.metadata)
        self.assertIn("SPLIT_COREPORTED_METRICS", {issue["code"] for issue in report["issues"]})

    def test_condition_numbers_and_units_require_exact_support(self) -> None:
        payload = valid_payload()
        payload["sentences"][0]["text"] = (
            "A Pd-catalyzed transformation of 0.50 mmol substrate at 20 deg C for 24 h furnished "
            "allene 3am in 75% isolated yield and 89% ee [1]."
        )
        report = validate_prose_payload(payload, self.rows, self.plan, self.metadata)
        self.assertNotIn("UNSUPPORTED_NUMBER", {issue["code"] for issue in report["issues"]})
        payload["sentences"][0]["text"] = payload["sentences"][0]["text"].replace("0.50 mmol", "0.75 mmol")
        report = validate_prose_payload(payload, self.rows, self.plan, self.metadata)
        self.assertIn("UNSUPPORTED_NUMBER", {issue["code"] for issue in report["issues"]})

    def test_76_and_74_must_not_be_presented_without_source_context(self) -> None:
        payload = valid_payload()
        payload["selected_claim_ids"] = ["CL-F47A-76", "CL-F47A-74"]
        payload["sentences"][0].update(
            {
                "text": "The conversion gave 76% and 74% isolated yield [1].",
                "supporting_claim_ids": ["CL-F47A-76", "CL-F47A-74"],
                "factual_bindings": [
                    {"kind": "numeric_result", "text": "76%", "claim_ids": ["CL-F47A-76"]},
                    {"kind": "numeric_result", "text": "74%", "claim_ids": ["CL-F47A-74"]},
                ],
            }
        )
        report = validate_prose_payload(payload, self.rows, self.plan, self.metadata)
        self.assertIn("UNEXPLAINED_MAIN_SI_RESULT_DIFFERENCE", {issue["code"] for issue in report["issues"]})

    def test_generation_uses_at_most_one_repair(self) -> None:
        invalid = valid_payload()
        invalid["sentences"][0]["text"] = "An unsupported 81% result was obtained [1]."
        provider = FakeProvider([invalid, valid_payload(), valid_payload()])
        result = generate_with_bounded_repair(provider, {}, self.rows, self.plan, self.metadata)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["request_count"], 2)
        self.assertEqual(result["validation"]["status"], "PASS")

        provider = FakeProvider([invalid, invalid, valid_payload()])
        result = generate_with_bounded_repair(provider, {}, self.rows, self.plan, self.metadata)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["validation"]["status"], "FAIL")

    def test_external_run_separates_44_accounting_from_selected_sentence_mapping(self) -> None:
        payload = valid_payload()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            result = prepare_vertical_slice_v2(
                run_root=root,
                before_section="# Before\n",
                final_rows=self.rows,
                evidence_plan=self.plan,
                citation_metadata=self.metadata,
                generation={
                    "payload": payload,
                    "request_count": 1,
                    "attempts": [{"metadata": {"model": "qwen3.7-max", "region": "cn-beijing"}}],
                    "validation": validate_prose_payload(payload, self.rows, self.plan, self.metadata),
                },
                run_manifest={"run_id": "phase8b_grounded_vertical_slice_v2_20260714T010203Z"},
            )
            accounting = (root / "mapping/claim_accounting_v2.jsonl").read_text(encoding="utf-8").splitlines()
            sentence_map = (root / "mapping/sentence_claim_map_v2.jsonl").read_text(encoding="utf-8").splitlines()
            summary = json.loads((root / "reports/vertical_slice_summary_v2.json").read_text(encoding="utf-8"))
            self.assertEqual(len(accounting), 44)
            self.assertEqual(len(sentence_map), 1)
            self.assertEqual(summary["final_claim_accounting_count"], 44)
            self.assertEqual(summary["selected_claim_count"], 2)
            self.assertEqual(result["stage"], "PHASE8B_VERTICAL_SLICE_V2_READY_FOR_HUMAN_REVIEW")


if __name__ == "__main__":
    unittest.main(verbosity=2)
