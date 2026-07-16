#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.delivery.finished_review import (
    CONTINUOUS_MODE,
    DEFAULT_MODE,
    QODERWORK_PROMPT,
    REQUIRED_OUTPUTS,
    STAGE_READY,
    build_qwen_generation_request,
    build_finished_review_plan,
    delivery_stops_at_checkpoint,
    export_qoderwork_flat_package,
    generate_finished_review_with_bounded_repair,
    validate_finished_review_payload,
    verify_frozen_inputs,
    write_failed_generation_diagnostic,
    write_finished_review_package,
)
from scripts.delivery.run_finished_mini_review import _validate_curated_editorial_shape


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
            "source_conflict_detected": disposition == "SOURCE_CONFLICT_RETAINED",
            "source_conflict": (
                {"conflict_type": "SOURCE_INTERNAL_LABEL_CONFLICT", "alternatives": [{"reported_value": "A"}, {"reported_value": "B"}]}
                if disposition == "SOURCE_CONFLICT_RETAINED"
                else None
            ),
        },
    }


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
        "F3I": {"authors": ["S. Yu", "S. Ma"], "title": "Review", "journal": "Angew. Chem. Int. Ed.", "year": 2012, "volume": "51", "issue": "13", "pages": "3074-3112", "doi": "10.1002/anie.201101460"},
        "F47A": {"authors": ["M. Ogasawara", "H. Ikeda"], "title": "Study A", "journal": "J. Am. Chem. Soc.", "year": 2001, "volume": "123", "issue": "9", "pages": "2089-2090", "doi": "10.1021/ja005921o"},
        "P403": {"authors": ["Y. Dong", "N. Zhang"], "title": "Study B", "journal": "ACS Catal.", "year": 2025, "volume": "15", "issue": "20", "pages": "17215-17224", "doi": "10.1021/acscatal.5c05571"},
    }


def valid_payload() -> dict:
    fact = {
        "sentence_id": "S1",
        "sentence_role": "fact",
        "text": "A review-level synthesis places representative catalytic allene strategies in a bounded context.",
        "supporting_claim_ids": ["F3I-CONTEXT"],
        "source_paper_ids": ["F3I"],
        "evidence_role": "REVIEW_LEVEL_SUMMARY_EVIDENCE",
    }
    sections = []
    for index, heading in enumerate(
        [
            "1. Scope and Source Selection",
            "2. Catalyst and Ligand Control of Selectivity",
            "3. Substrate Architecture and Reaction Boundaries",
            "4. Mechanistic Evidence: Dynamic Intermediates, Coordination, and Competing Models",
            "5. Transferable Design Principles and Limitations",
            "6. Conclusions",
        ],
        start=1,
    ):
        sentence = dict(fact, sentence_id=f"S{index}")
        sections.append({"heading": heading, "paragraphs": [{"paragraph_id": f"P{index}", "purpose": "bounded synthesis", "sentences": [sentence]}]})
    abstract_sentence = dict(fact, sentence_id="A1")
    return {
        "title": "Palladium-Centered Strategies for Asymmetric Allene Synthesis: Selectivity Control, Substrate Constraints, and Mechanistic Evidence",
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
    def _writer_kwargs(self, root: Path, *, generation_manifest: dict | None = None, baseline_markdown: Path | None = None) -> dict:
        docx = root.parent / "source.docx"
        docx.write_bytes(b"PK\x03\x04dummy")
        return {
            "output_root": root,
            "payload": valid_payload(),
            "final_rows": final_rows(),
            "bibliography_metadata": bibliography(),
            "evidence_plan": build_finished_review_plan(final_rows()),
            "generation_manifest": generation_manifest
            or {
                "current_run_model_requests": 0,
                "authoring_mode": "codex_exec_curated_revision",
                "authoring_agent_model": "gpt-5.6-terra",
                "final_text_origin": "CURATED_FROM_FROZEN_FINAL_CLAIMS_NO_EXTERNAL_PROVIDER_CALL",
                "reused_upstream_generation_payload": False,
            },
            "docx_source": docx,
            "docx_integrity": {"status": "PASS", "bookmark_count": 3, "internal_hyperlink_count": 9, "doi_hyperlink_count": 3},
            "baseline_markdown": baseline_markdown,
            "repository_root": REPO_ROOT,
            "min_words": 1,
        }

    def test_curated_writer_rejects_each_wrong_provenance_value(self) -> None:
        expected = {
            "current_run_model_requests": 0,
            "authoring_mode": "codex_exec_curated_revision",
            "authoring_agent_model": "gpt-5.6-terra",
            "final_text_origin": "CURATED_FROM_FROZEN_FINAL_CLAIMS_NO_EXTERNAL_PROVIDER_CALL",
            "reused_upstream_generation_payload": False,
        }
        wrong_values = {
            "current_run_model_requests": 1,
            "authoring_mode": "provider_generation",
            "authoring_agent_model": "other-model",
            "final_text_origin": "PROVIDER_GENERATED_FROM_FROZEN_FINAL_CLAIMS",
            "reused_upstream_generation_payload": True,
        }
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp_dir:
            baseline = Path(temp_dir) / "baseline.md"
            baseline.write_text("# baseline\n", encoding="utf-8")
            for field, wrong_value in wrong_values.items():
                with self.subTest(field=field):
                    manifest = {**expected, field: wrong_value}
                    kwargs = self._writer_kwargs(Path(temp_dir) / field, generation_manifest=manifest, baseline_markdown=baseline)
                    with self.assertRaisesRegex(ValueError, "curated provenance"):
                        write_finished_review_package(**kwargs)

    def test_finished_writer_requires_baseline_before_creating_output_tree(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp_dir:
            root = Path(temp_dir) / "missing-baseline"
            kwargs = self._writer_kwargs(root)
            with self.assertRaisesRegex(ValueError, "baseline Markdown is required"):
                write_finished_review_package(**kwargs)
            self.assertFalse(root.exists())

    def test_finished_writer_records_repo_relative_baseline_outside_repo_cwd(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp_dir, tempfile.TemporaryDirectory(dir="/tmp") as outside_cwd:
            root = Path(temp_dir) / "outside-cwd-package"
            baseline = Path(temp_dir) / "baseline.md"
            baseline.write_text("# baseline\n", encoding="utf-8")
            previous_cwd = Path.cwd()
            try:
                os.chdir(outside_cwd)
                result = write_finished_review_package(**self._writer_kwargs(root, baseline_markdown=baseline))
            finally:
                os.chdir(previous_cwd)
            provenance = json.loads((Path(result["output_root"]) / "baseline_provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["baseline_source_repo_relative_path"], baseline.relative_to(REPO_ROOT).as_posix())
            self.assertEqual(provenance["baseline_sha256"], hashlib.sha256(baseline.read_bytes()).hexdigest())

    def test_finished_writer_rejects_baseline_outside_explicit_repository_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp_dir, tempfile.TemporaryDirectory(dir="/tmp") as outside_dir:
            baseline = Path(outside_dir) / "baseline.md"
            baseline.write_text("# outside\n", encoding="utf-8")
            kwargs = self._writer_kwargs(Path(temp_dir) / "outside-baseline", baseline_markdown=baseline)
            with self.assertRaisesRegex(ValueError, "repository root"):
                write_finished_review_package(**kwargs)

    @staticmethod
    def _curated_payload_with_conclusion(paragraph_word_counts: list[int]) -> dict:
        return {
            "sections": [
                {
                    "heading": "6. Conclusions",
                    "paragraphs": [
                        {"sentences": [{"text": " ".join(["evidence"] * word_count)}]}
                        for word_count in paragraph_word_counts
                    ],
                }
            ]
        }

    def test_curated_editorial_shape_accepts_three_paragraph_conclusion_in_word_band(self) -> None:
        metrics = _validate_curated_editorial_shape(self._curated_payload_with_conclusion([100, 100, 100]))
        self.assertEqual(metrics, {"conclusion_section_count": 1, "conclusion_paragraph_count": 3, "conclusion_word_count": 300})

    def test_curated_editorial_shape_rejects_wrong_conclusion_paragraph_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 3 conclusion paragraphs; found 2"):
            _validate_curated_editorial_shape(self._curated_payload_with_conclusion([150, 150]))

    def test_curated_editorial_shape_rejects_out_of_band_conclusion_word_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "280-340 English prose words.*found 270"):
            _validate_curated_editorial_shape(self._curated_payload_with_conclusion([90, 90, 90]))

    def test_curated_runner_uses_local_revision_mode_without_payload_input(self) -> None:
        source = (REPO_ROOT / "scripts/delivery/run_finished_mini_review.py").read_text(encoding="utf-8")
        self.assertIn("--curated-revision", source)
        self.assertNotIn("--curated-payload", source)
        self.assertNotIn("_build_product_quality_revision", source)
        self.assertNotIn("base_payload", source)
        self.assertNotIn("curated_payload", source)
        self.assertNotIn("copy.deepcopy", source)
        main_source = source[source.index("def main()") :]
        self.assertNotIn("model_payload.json", main_source)
        self.assertNotIn("read_text(encoding=\"utf-8\")", main_source[main_source.index("if args.curated_revision") : main_source.index("elif args.mock_response")])
        self.assertIn("payload = _build_codex_curated_revision(final_rows)", main_source)

    def test_finished_stage_requires_full_text_human_review(self) -> None:
        self.assertEqual(STAGE_READY, "HUMAN_FULL_TEXT_REVIEW_REQUIRED")

    def test_validator_requires_exact_ordered_section_list(self) -> None:
        payload = valid_payload()
        payload["sections"].append(payload["sections"][0])
        report = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
        self.assertIn("REQUIRED_SECTIONS_MISMATCH", {item["code"] for item in report["blockers"]})

    def test_continuous_delivery_is_explicit_opt_in(self) -> None:
        self.assertTrue(delivery_stops_at_checkpoint(DEFAULT_MODE, blockers=[]))
        self.assertFalse(delivery_stops_at_checkpoint(CONTINUOUS_MODE, blockers=[]))
        self.assertTrue(delivery_stops_at_checkpoint(CONTINUOUS_MODE, blockers=[{"code": "UNSUPPORTED_NUMBER"}]))

    def test_evidence_plan_exposes_all_non_conflicts_as_candidates(self) -> None:
        plan = build_finished_review_plan(final_rows())
        self.assertEqual(plan["available_non_conflict_claim_count"], 37)
        self.assertEqual(plan["retained_conflict_count"], 7)
        self.assertEqual(len(plan["candidate_claim_ids"]), 37)
        self.assertIn("F47A-76", plan["candidate_claim_ids"])
        self.assertTrue(all(not value.startswith("CONFLICT-") for value in plan["candidate_claim_ids"]))
        self.assertEqual(len(plan["claim_accounting"]), 44)
        self.assertTrue(all(row["plan_status"] == "CANDIDATE" for row in plan["claim_accounting"][:37]))

    def test_qwen_request_contains_only_selected_final_claim_fields(self) -> None:
        rows = final_rows()
        plan = build_finished_review_plan(rows)
        request = build_qwen_generation_request(rows, plan, bibliography())
        self.assertEqual(request["delivery_mode"], CONTINUOUS_MODE)
        self.assertEqual(len(request["claims"]), 37)
        self.assertFalse(any(row["claim_id"].startswith("CONFLICT-") for row in request["claims"]))
        self.assertFalse(any("final_disposition" in row for row in request["claims"]))
        self.assertNotIn("CONFLICT-", json.dumps(request))
        self.assertNotIn("claim_accounting", request["evidence_plan"])
        self.assertIn("连续生成第一份完整英文迷你综述成品", QODERWORK_PROMPT)

    def test_reviewer_synthesis_requires_two_claims_and_two_sources(self) -> None:
        payload = valid_payload()
        payload["abstract_sentences"][0] = {
            "sentence_id": "A1",
            "sentence_role": "reviewer_synthesis",
            "text": "Together, the sources frame palladium control as a coupled ligand and substrate problem.",
            "supporting_claim_ids": ["F3I-CONTEXT", "F47A-YIELD"],
            "source_paper_ids": ["F3I", "F47A"],
            "material_supporting_claim_ids_by_paper": {"F3I": ["F3I-CONTEXT"], "F47A": ["F47A-YIELD"]},
            "evidence_role": "CROSS_STUDY_INTERPRETATION",
        }
        payload["selected_claim_ids"] = ["F3I-CONTEXT", "F47A-YIELD"]
        payload["intentionally_omitted_claim_ids"] = sorted(
            row["claim_id"] for row in final_rows()
            if row["final_disposition"] != "SOURCE_CONFLICT_RETAINED" and row["claim_id"] not in payload["selected_claim_ids"]
        )
        report = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
        self.assertEqual(report["blocker_count"], 0, report["blockers"])

        payload["abstract_sentences"][0]["supporting_claim_ids"] = ["F47A-YIELD"]
        payload["abstract_sentences"][0]["source_paper_ids"] = ["F47A"]
        report = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
        self.assertIn("INVALID_REVIEWER_SYNTHESIS", {item["code"] for item in report["blockers"]})

    def test_reviewer_synthesis_requires_material_support_from_each_cited_paper(self) -> None:
        payload = valid_payload()
        sentence = payload["sections"][0]["paragraphs"][0]["sentences"][0]
        sentence.update(
            {
                "sentence_role": "reviewer_synthesis",
                "supporting_claim_ids": ["F47A-YIELD", "P403-YIELD"],
                "source_paper_ids": ["F47A", "P403"],
                "material_supporting_claim_ids_by_paper": {"F47A": ["F47A-YIELD"], "P403": []},
            }
        )
        report = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
        self.assertIn("IMMATERIAL_REVIEWER_SYNTHESIS_SOURCE", {item["code"] for item in report["blockers"]})

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

    def test_valid_payload_supports_transition_sentences_without_claims(self) -> None:
        payload = valid_payload()
        payload["sections"][0]["paragraphs"][0]["sentences"].append(
            {"sentence_id": "T1", "sentence_role": "transition", "text": "The comparison therefore turns from scope to evidence boundaries.", "supporting_claim_ids": [], "source_paper_ids": [], "evidence_role": "TRANSITION"}
        )
        report = validate_finished_review_payload(payload, final_rows(), bibliography(), min_words=1)
        self.assertEqual(report["blocker_count"], 0, report["blockers"])

    def test_frozen_input_hash_mismatch_stops_delivery(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp_dir:
            root = Path(temp_dir)
            claims = root / "claims.jsonl"
            manifest = root / "HASH_MANIFEST.sha256"
            claims.write_text("changed\n", encoding="utf-8")
            manifest.write_text("manifest\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final claims hash mismatch"):
                verify_frozen_inputs(claims, manifest, "0" * 64, "1" * 64)

    def test_writer_creates_complete_closed_package(self) -> None:
        payload = valid_payload()
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temp_dir:
            root = Path(temp_dir) / "case-01-allene-mini-review"
            docx = Path(temp_dir) / "source.docx"
            baseline = Path(temp_dir) / "continuous.md"
            docx.write_bytes(b"PK\x03\x04dummy")
            baseline.write_text("# Earlier title\n\nEarlier prose.\n", encoding="utf-8")
            result = write_finished_review_package(
                output_root=root,
                repository_root=REPO_ROOT,
                payload=payload,
                final_rows=final_rows(),
                bibliography_metadata=bibliography(),
                evidence_plan=build_finished_review_plan(final_rows()),
                generation_manifest={
                    "current_run_model_requests": 0,
                    "authoring_mode": "codex_exec_curated_revision",
                    "authoring_agent_model": "gpt-5.6-terra",
                    "final_text_origin": "CURATED_FROM_FROZEN_FINAL_CLAIMS_NO_EXTERNAL_PROVIDER_CALL",
                    "reused_upstream_generation_payload": False,
                },
                docx_source=docx,
                docx_integrity={"status": "PASS", "bookmark_count": 3, "internal_hyperlink_count": 9, "doi_hyperlink_count": 3},
                baseline_markdown=baseline,
                min_words=1,
            )
            self.assertEqual(result["stage"], "HUMAN_FULL_TEXT_REVIEW_REQUIRED")
            self.assertTrue(all((root / name).is_file() for name in REQUIRED_OUTPUTS))
            accounting = json.loads((root / "evidence/final_claim_accounting.json").read_text())
            self.assertEqual(
                {row["accounting_status"] for row in accounting},
                {"used", "intentionally_omitted", "retained_conflict"},
            )
            self.assertIn("No source-paper figures", (root / "03_figure_redraw/skip_reason.md").read_text(encoding="utf-8"))
            self.assertEqual(len((root / "sentence_claim_map.jsonl").read_text(encoding="utf-8").splitlines()), 7)
            self.assertIn(QODERWORK_PROMPT, (root / "qoderwork_run_record.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((root / "quality_report.json").read_text())["docx_integrity"]["status"], "PASS")
            self.assertTrue((root / "design_principles_table.csv").is_file())
            self.assertTrue((root / "full_evidence_claim_table.xlsx").is_file())
            baseline_provenance = json.loads((root / "baseline_provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(baseline_provenance["baseline_source_repo_relative_path"], baseline.relative_to(REPO_ROOT).as_posix())
            self.assertEqual(baseline_provenance["baseline_sha256"], hashlib.sha256(baseline.read_bytes()).hexdigest())
            manifest_entries = [line.split("  ", 1)[1] for line in (root / "HASH_MANIFEST.sha256").read_text().splitlines()]
            self.assertTrue(all((root / item).is_file() for item in manifest_entries))
            subprocess.run(["sha256sum", "-c", "HASH_MANIFEST.sha256"], cwd=root, check=True, capture_output=True, text=True)
            flat_root = Path(temp_dir) / "flat-export"
            export_result = export_qoderwork_flat_package(root, flat_root)
            self.assertEqual(export_result["copied_file_count"], len(manifest_entries))
            flat_manifest = json.loads((flat_root / "flat_export_manifest.json").read_text())
            self.assertEqual(flat_manifest["copied_file_count"], len(flat_manifest["copied_files"]))
            self.assertTrue(all((flat_root / item["flat_relative_path"]).is_file() for item in flat_manifest["copied_files"]))
            subprocess.run(["sha256sum", "-c", "HASH_MANIFEST.sha256"], cwd=flat_root, check=True, capture_output=True, text=True)
            with zipfile.ZipFile(root / "full_evidence_claim_table.xlsx") as archive:
                sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
                styles = ET.fromstring(archive.read("xl/styles.xml"))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            self.assertIsNotNone(sheet.find("x:cols", ns))
            self.assertIsNotNone(sheet.find("x:sheetViews/x:sheetView/x:pane[@state='frozen']", ns))
            self.assertIsNotNone(sheet.find("x:autoFilter", ns))
            self.assertGreater(len(styles.findall("x:cellXfs/x:xf", ns)), 1)

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
