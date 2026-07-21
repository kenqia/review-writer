#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.delivery.finished_review import (
    CONTINUOUS_MODE,
    DEFAULT_MODE,
    QODERWORK_PROMPT,
    REQUIRED_OUTPUTS,
    build_qwen_generation_request,
    build_finished_review_plan,
    delivery_stops_at_checkpoint,
    generate_finished_review_with_bounded_repair,
    load_hash_bound_bibliography,
    authorize_finished_review_model,
    write_generation_failure_package,
    validate_finished_review_payload,
    verify_frozen_inputs,
    write_failed_generation_diagnostic,
    write_finished_review_package,
)


def _row(
    claim_id: str,
    paper_id: str,
    *,
    claim_type: str = "scope_result",
    metric: str = "not_applicable",
    value: object = None,
    unit: str | None = None,
    conditions: str | None = None,
    evidence: str = "The source reports a representative transformation.",
    disposition: str = "AI_SUPPORTED",
) -> dict:
    return {
        "claim_id": claim_id,
        "final_disposition": disposition,
        "final_claim": {
            "claim_id": claim_id,
            "paper_id": paper_id,
            "source_document_id": f"{paper_id}_MAIN",
            "source_role": "MAIN",
            "claim_type": claim_type,
            "reaction_stage": "target_catalytic_reaction",
            "reaction_entry": "representative transformation",
            "substrate_ids": ["substrate"],
            "reagent_or_partner_ids": ["Pd catalyst"],
            "product_id": "allene product",
            "conditions_as_reported": conditions,
            "metric_type": metric,
            "value_as_reported": value,
            "unit_as_reported": unit,
            "short_evidence": evidence,
            "epistemic_class": "REVIEW_ARTICLE_SUMMARY" if paper_id == "F3I" else "DIRECT_REPORTED_RESULT",
            "pathway_status": "NOT_APPLICABLE",
            "evidence_locator": {"source_document_id": f"{paper_id}_MAIN", "page": 1, "entry_id": f"{claim_id}-E1"},
            "source_conflict_detected": disposition == "SOURCE_CONFLICT_RETAINED",
            "source_conflict": (
                {"conflict_type": "SOURCE_INTERNAL_LABEL_CONFLICT", "alternatives": [{"reported_value": "A"}, {"reported_value": "B"}]}
                if disposition == "SOURCE_CONFLICT_RETAINED"
                else None
            ),
        },
    }


def locator_ref(claim_id: str) -> str:
    row = next(row for row in final_rows() if row["claim_id"] == claim_id)
    return hashlib.sha256(json.dumps(row["final_claim"]["evidence_locator"], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def final_rows() -> list[dict]:
    rows = [
        _row("F3I-CONTEXT", "F3I", evidence="The review summarizes representative catalytic allene strategies."),
        _row(
            "F47A-YIELD",
            "F47A",
            claim_type="target_reaction_numeric_outcome",
            metric="isolated_yield",
            value=75,
            unit="%",
            conditions="20 deg C, 24 h",
            evidence="The study reports allene product in 75% isolated yield.",
        ),
        _row(
            "F47A-EE",
            "F47A",
            claim_type="target_reaction_numeric_outcome",
            metric="ee",
            value=89,
            unit="% ee",
            conditions="20 deg C, 24 h",
            evidence="The study reports allene product in 89% ee.",
        ),
        _row(
            "F47A-76",
            "F47A",
            claim_type="stoichiometric_result",
            metric="isolated_yield",
            value=76,
            unit="%",
            conditions="THF, 20 deg C",
            disposition="HUMAN_SPOT_CHECKED_CORRECTED_ACCEPT",
            evidence="The main text reports 76% yield without a supported DBA binding.",
        ),
        _row(
            "F47A-74",
            "F47A",
            claim_type="stoichiometric_result",
            metric="isolated_yield",
            value=74,
            unit="%",
            conditions="THF, 20 deg C, 12 h, DBA",
            evidence="The SI reports 74% isolated yield with DBA.",
        ),
        _row(
            "F47A-62",
            "F47A",
            claim_type="stoichiometric_result",
            metric="isolated_yield",
            value=62,
            unit="%",
            conditions="THF, 20 deg C, 12 h, without DBA",
            evidence="The SI reports 62% isolated yield without DBA.",
        ),
        _row(
            "P403-YIELD",
            "P403",
            claim_type="optimization_result",
            metric="isolated_yield",
            value=90,
            unit="%",
            conditions="25 deg C, 24 h",
            evidence="Optimization reports 90% isolated yield.",
        ),
        _row(
            "P403-EE",
            "P403",
            claim_type="optimization_result",
            metric="ee",
            value=90,
            unit="% ee",
            conditions="25 deg C, 24 h",
            evidence="Optimization reports 90% ee.",
        ),
    ]
    paper_cycle = ("F3I", "F47A", "P403")
    while len(rows) < 37:
        index = len(rows) + 1
        rows.append(_row(f"CLAIM-{index:02d}", paper_cycle[index % 3]))
    for index in range(7):
        rows.append(_row(f"CONFLICT-{index + 1}", "P403", claim_type="source_conflict", disposition="SOURCE_CONFLICT_RETAINED"))
    return rows


def bibliography() -> dict:
    return {
        "F3I": {"authors": ["Synthetic Author A"], "title": "Synthetic Review", "journal": "Synthetic Journal", "year": 2000, "volume": "1", "issue": "1", "pages": "1-2", "doi": "10.0000/synthetic-f3i"},
        "F47A": {"authors": ["Synthetic Author B"], "title": "Synthetic Study A", "journal": "Synthetic Journal", "year": 2001, "volume": "2", "issue": "1", "pages": "3-4", "doi": "10.0000/synthetic-f47a"},
        "P403": {"authors": ["Synthetic Author C"], "title": "Synthetic Study B", "journal": "Synthetic Journal", "year": 2002, "volume": "3", "issue": "1", "pages": "5-6", "doi": "10.0000/synthetic-p403"},
    }


def valid_payload() -> dict:
    text = "A review-level synthesis places representative catalytic allene strategies in a bounded context."
    fact = {
        "sentence_id": "S1",
        "sentence_role": "fact",
        "text": text,
        "supporting_claim_ids": ["F3I-CONTEXT"],
        "source_paper_ids": ["F3I"],
        "evidence_role": "REVIEW_LEVEL_SUMMARY_EVIDENCE",
        "factual_span_bindings": [{"binding_id": "S1-B1", "span_class": "material_factual", "start": 0, "end": len(text), "text": text, "claim_id": "F3I-CONTEXT", "locator_ref": locator_ref("F3I-CONTEXT")}],
    }
    sections = []
    for index, heading in enumerate(
        [
            "1. Introduction and Scope",
            "2. Catalytic Strategies and Selectivity Control",
            "2.1 Review-Level Context",
            "2.2 Palladium-Catalyzed Construction of Axially Chiral Allenes",
            "2.3 Asymmetric Allenylation with Phosphine Oxides",
            "3. Mechanistic Evidence and Evidence Boundaries",
            "4. Cross-Study Comparison and Limitations",
            "5. Conclusions",
        ],
        start=1,
    ):
        sentence = dict(fact, sentence_id=f"S{index}", factual_span_bindings=[dict(fact["factual_span_bindings"][0], binding_id=f"S{index}-B1")])
        sections.append({"heading": heading, "paragraphs": [{"paragraph_id": f"P{index}", "purpose": "bounded synthesis", "sentences": [sentence]}]})
    abstract_sentence = dict(fact, sentence_id="A1", factual_span_bindings=[dict(fact["factual_span_bindings"][0], binding_id="A1-B1")])
    return {
        "title": "Representative Strategies in Asymmetric Allene Chemistry: Catalysis, Reactivity, and Mechanistic Evidence",
        "abstract_sentences": [abstract_sentence],
        "keywords": ["allene chemistry", "asymmetric catalysis", "evidence synthesis"],
        "sections": sections,
        "comparison_table": [
            {
                "source_study": "Review context",
                "evidence_role": "Review-level synthesis",
                "catalytic_or_reaction_strategy": "Representative catalytic allene strategies",
                "representative_transformation": "Bounded contextual comparison",
                "key_supported_outcome": "Representative strategies are summarized",
                "mechanistic_or_control_evidence": "Not asserted",
                "evidence_limitation_warning": "Review-level evidence",
                "supporting_claim_ids": ["F3I-CONTEXT"],
            }
        ],
        "selected_claim_ids": ["F3I-CONTEXT"],
        "intentionally_omitted_claim_ids": [row["claim_id"] for row in final_rows() if row["final_disposition"] != "SOURCE_CONFLICT_RETAINED" and row["claim_id"] != "F3I-CONTEXT"],
    }


class FinishedReviewDeliveryTests(unittest.TestCase):
    def test_continuous_delivery_is_explicit_opt_in(self) -> None:
        self.assertTrue(delivery_stops_at_checkpoint(DEFAULT_MODE, blockers=[]))
        self.assertFalse(delivery_stops_at_checkpoint(CONTINUOUS_MODE, blockers=[]))
        self.assertTrue(delivery_stops_at_checkpoint(CONTINUOUS_MODE, blockers=[{"code": "UNSUPPORTED_NUMBER"}]))

    def test_evidence_plan_excludes_conflicts_and_unsupported_dba_76_binding(self) -> None:
        plan = build_finished_review_plan(final_rows())
        self.assertEqual(plan["available_non_conflict_claim_count"], 37)
        self.assertEqual(plan["retained_conflict_count"], 7)
        self.assertNotIn("F47A-76", plan["selected_claim_ids"])
        selected = set(plan["selected_claim_ids"])
        self.assertTrue({"F47A-YIELD", "F47A-EE", "F47A-74", "F47A-62"}.issubset(selected))
        self.assertTrue(all(not value.startswith("CONFLICT-") for value in selected))
        self.assertEqual(len(plan["claim_accounting"]), 44)

    def test_qwen_request_contains_only_selected_final_claim_fields(self) -> None:
        rows = final_rows()
        plan = build_finished_review_plan(rows)
        request = build_qwen_generation_request(rows, plan, bibliography())
        self.assertEqual(request["delivery_mode"], CONTINUOUS_MODE)
        self.assertNotIn("F47A-76", {row["claim_id"] for row in request["claims"]})
        self.assertFalse(any(row["claim_id"].startswith("CONFLICT-") for row in request["claims"]))
        self.assertTrue(all("evidence_locator" in row for row in request["claims"]))
        self.assertFalse(any("final_disposition" in row for row in request["claims"]))
        self.assertNotIn("CONFLICT-", json.dumps(request))
        self.assertNotIn("claim_accounting", request["evidence_plan"])
        self.assertIn("连续生成第一份完整英文迷你综述成品", QODERWORK_PROMPT)

    def test_generation_repairs_true_blockers_once_at_most(self) -> None:
        broken = valid_payload()
        broken["sections"][0]["paragraphs"][0]["sentences"][0]["text"] = "An unsupported result gave 55% ee."

        class Provider:
            def __init__(self) -> None:
                self.responses = [broken, valid_payload(), valid_payload()]
                self.calls = 0

            def generate(self, _request: dict) -> dict:
                response = self.responses[self.calls]
                self.calls += 1
                return {
                    "status": "ok",
                    "content": json.dumps(response),
                    "metadata": {"model": "offline-test", "stream_telemetry": {"total_tokens": 10, "finish_reason": "stop"}},
                    "warnings": [],
                }

        provider = Provider()
        result = generate_finished_review_with_bounded_repair(
            provider,
            final_rows(),
            build_finished_review_plan(final_rows()),
            bibliography(),
            min_words=1,
        )
        self.assertEqual(result["request_count"], 2)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["validation"]["blocker_count"], 0)
        self.assertTrue(result["repair_used"])

    def test_scientific_blockers_reject_conflicts_unknown_numbers_and_dba_76(self) -> None:
        payload = valid_payload()
        sentence = payload["sections"][0]["paragraphs"][0]["sentences"][0]
        sentence["text"] = "The DBA-present experiment gave 76% yield and 55% ee."
        sentence["supporting_claim_ids"] = ["F47A-76", "CONFLICT-1"]
        sentence["source_paper_ids"] = ["F47A", "P403"]
        report = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
        codes = {item["code"] for item in report["blockers"]}
        self.assertIn("SOURCE_CONFLICT_LEAKAGE", codes)
        self.assertIn("UNSUPPORTED_NUMERIC_CLAIM", codes)
        self.assertIn("UNSUPPORTED_DBA_BINDING", codes)

    def test_rejects_unbound_nonnumeric_scientific_conclusion(self) -> None:
        payload = valid_payload()
        payload["abstract_sentences"][0]["text"] = "A review-level synthesis establishes a universal catalytic mechanism."
        report = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
        self.assertIn("UNBOUND_FACTUAL_SPAN", {item["code"] for item in report["blockers"]})

    def test_factual_span_bindings_reject_partial_stale_and_invalid_locator_references(self) -> None:
        cases = {
            "partial": ("UNBOUND_FACTUAL_SPAN", lambda binding: binding.update({"end": binding["end"] - 1, "text": binding["text"][:-1]})),
            "stale": ("INVALID_FACTUAL_SPAN_CLAIM", lambda binding: binding.update({"claim_id": "STALE-CLAIM"})),
            "locator": ("INVALID_FACTUAL_SPAN_LOCATOR", lambda binding: binding.update({"locator_ref": "unknown:locator"})),
        }
        for _name, (expected, mutate) in cases.items():
            payload = valid_payload()
            binding = payload["abstract_sentences"][0]["factual_span_bindings"][0]
            mutate(binding)
            report = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
            self.assertIn(expected, {item["code"] for item in report["blockers"]})

    def test_failure_packages_are_sanitized_hash_closed_and_immutable(self) -> None:
        cases = {
            "PROVIDER_EXCEPTION": RuntimeError("credential=secret prompt must not persist"),
            "PROVIDER_ERROR": {"status": "error", "content": "provider detail must not persist", "metadata": {"model": "qwen3.7-max"}},
            "EMPTY_RESPONSE": {"status": "ok", "content": "", "metadata": {"model": "qwen3.7-max"}},
            "MALFORMED_JSON": {"status": "ok", "content": "{not-json", "metadata": {"model": "qwen3.7-max"}},
        }
        with tempfile.TemporaryDirectory() as temporary:
            for category, failure in cases.items():
                output_root = Path(temporary) / category.lower()
                package = write_generation_failure_package(
                    output_root=output_root,
                    attempt_metadata={"attempt": 1, "model": "qwen3.7-max"},
                    failure_category=category,
                    failed_stage="generation_response",
                    model_authorization={"model": "qwen3.7-max", "authorization_id": "finished-review-qwen-v1"},
                    input_hashes={"request_sha256": "a" * 64, "bibliography_sha256": "b" * 64},
                    diagnostic=str(failure),
                )
                manifest = (package / "failure_package.json").read_text(encoding="utf-8")
                self.assertTrue((package / "HASH_MANIFEST.sha256").is_file())
                self.assertNotIn("secret", manifest)
                self.assertNotIn("prompt", manifest)
                with self.assertRaises(ValueError):
                    write_generation_failure_package(
                        output_root=output_root,
                        attempt_metadata={}, failure_category=category, failed_stage="generation_response",
                        model_authorization={}, input_hashes={}, diagnostic="overwrite",
                    )

    def test_generator_persists_failure_packages_for_exception_empty_and_malformed_response(self) -> None:
        cases = {
            "PROVIDER_EXCEPTION": lambda: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
            "PROVIDER_ERROR": lambda: {"status": "error", "content": "provider detail", "metadata": {"model": "qwen3.7-max"}},
            "EMPTY_RESPONSE": lambda: {"status": "ok", "content": "", "metadata": {"model": "qwen3.7-max"}},
            "MALFORMED_JSON": lambda: {"status": "ok", "content": "{broken", "metadata": {"model": "qwen3.7-max"}},
        }
        with tempfile.TemporaryDirectory() as temporary:
            for category, produce in cases.items():
                class Provider:
                    def generate(self, _request: dict) -> dict:
                        return produce()

                root = Path(temporary) / category.lower()
                with self.assertRaises(RuntimeError):
                    generate_finished_review_with_bounded_repair(
                        Provider(), final_rows(), build_finished_review_plan(final_rows()), bibliography(),
                        failure_package_root=root,
                        model_authorization={"model": "qwen3.7-max", "authorization_id": "finished-review-qwen-v1"},
                        input_hashes={"request_sha256": "a" * 64},
                    )
                self.assertEqual(json.loads((root / "failure_package.json").read_text(encoding="utf-8"))["failure_category"], category)

    def test_bibliography_input_is_external_hash_bound_and_fails_closed(self) -> None:
        document = {"schema_version": "finished-review-bibliography-1.0", "entries": bibliography()}
        encoded = json.dumps(document, sort_keys=True).encode("utf-8")
        expected = hashlib.sha256(encoded).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bibliography.synthetic.json"
            path.write_bytes(encoded)
            self.assertEqual(load_hash_bound_bibliography(path, expected), bibliography())
            with self.assertRaises(ValueError):
                load_hash_bound_bibliography(path, "0" * 64)
            with self.assertRaises(ValueError):
                load_hash_bound_bibliography(Path(temporary) / "missing.json", expected)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_hash_bound_bibliography(path, hashlib.sha256(b"[]").hexdigest())

    def test_model_authorization_rejects_arbitrary_qwen_names(self) -> None:
        receipt = authorize_finished_review_model("qwen3.7-max", {"qwen3.7-max"})
        self.assertEqual(receipt["model"], "qwen3.7-max")
        self.assertEqual(receipt["authorization_id"], "finished-review-qwen-v1")
        for model in ("qwen-anything", "qwen3.7-max-preview", "qwen3.7-plus"):
            with self.assertRaises(ValueError):
                authorize_finished_review_model(model, {model})

    def test_valid_payload_supports_transition_sentences_without_claims(self) -> None:
        payload = valid_payload()
        payload["sections"][0]["paragraphs"][0]["sentences"].append(
            {"sentence_id": "T1", "sentence_role": "transition", "text": "The comparison therefore turns from scope to evidence boundaries.", "supporting_claim_ids": [], "source_paper_ids": [], "evidence_role": "TRANSITION"}
        )
        report = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
        self.assertEqual(report["blocker_count"], 0, report["blockers"])

    def test_frozen_input_hash_mismatch_stops_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            claims = root / "claims.jsonl"
            manifest = root / "HASH_MANIFEST.sha256"
            claims.write_text("changed\n", encoding="utf-8")
            manifest.write_text("manifest\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final claims hash mismatch"):
                verify_frozen_inputs(claims, manifest, "0" * 64, "1" * 64)

    def test_writer_creates_complete_closed_package(self) -> None:
        payload = valid_payload()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "case-01-allene-mini-review"
            docx = Path(temp_dir) / "source.docx"
            docx.write_bytes(b"PK\x03\x04dummy")
            result = write_finished_review_package(
                output_root=root,
                payload=payload,
                final_rows=final_rows(),
                bibliography_metadata=bibliography(),
                evidence_plan=build_finished_review_plan(final_rows()),
                generation_manifest={"model": "offline-test", "request_count": 0},
                qoderwork_status="MANUAL_QODERWORK_EXECUTION_REQUIRED",
                docx_source=docx,
                docx_integrity={"status": "PASS", "bookmark_count": 3, "internal_hyperlink_count": 9, "doi_hyperlink_count": 3},
                min_words=1,
            )
            self.assertEqual(result["stage"], "FIRST_FINISHED_QODERWORK_REVIEW_READY_FOR_HUMAN_QUALITY_REVIEW")
            self.assertTrue(all((root / name).is_file() for name in REQUIRED_OUTPUTS))
            self.assertEqual((root / "03_figure_redraw/skip_reason.md").read_text(encoding="utf-8").strip(), "No source-paper figures are included in this bounded working draft.\nThe manuscript uses one original evidence comparison table generated\nfrom the verified Phase 8A claim ledger.")
            self.assertEqual(len((root / "sentence_claim_map.jsonl").read_text(encoding="utf-8").splitlines()), 9)
            self.assertIn(QODERWORK_PROMPT, (root / "qoderwork_run_record.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((root / "quality_report.json").read_text())["docx_integrity"]["status"], "PASS")

    def test_failed_bounded_generation_persists_candidate_before_exit(self) -> None:
        payload = valid_payload()
        payload["sections"][0]["paragraphs"][0]["sentences"][0]["text"] = "An unsupported result gave 55% ee."
        validation = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "failed-candidate"
            write_failed_generation_diagnostic(
                output_root=root,
                payload=payload,
                final_rows=final_rows(),
                bibliography_metadata=bibliography(),
                validation=validation,
                generation_manifest={"request_count": 2},
            )
            self.assertTrue((root / "candidate_review.md").is_file())
            self.assertTrue((root / "model_payload.json").is_file())
            self.assertTrue((root / "validation.json").is_file())
            self.assertTrue((root / "HASH_MANIFEST.sha256").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
