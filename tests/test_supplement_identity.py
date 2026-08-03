from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from review_writer.acquisition.supplement_identity import (
    audit_source_coverage,
    audit_supplement_reports,
    normalize_doi,
    supplement_parent_relation,
)


class SupplementIdentityTests(unittest.TestCase):
    def test_main_is_always_required(self):
        result = audit_source_coverage(
            study_id="S1",
            available_roles=["SI"],
            si_policy="NOT_REQUIRED",
        )

        self.assertEqual("BLOCKED", result["study_status"])
        self.assertEqual("00_sources/source_coverage.json", result["canonical_artifact"])
        self.assertEqual("source-coverage.v1", result["schema_version"])
        self.assertEqual(["MAIN_REQUIRED"], result["blocking_reasons"])

    def test_required_si_blocks_only_declared_dependent_claims(self):
        result = audit_source_coverage(
            study_id="S2",
            available_roles=["MAIN"],
            si_policy="REQUIRED",
            si_dependent_claim_ids=["scope-1", "mechanism-1"],
        )

        self.assertEqual("PARTIAL", result["study_status"])
        self.assertEqual(["scope-1", "mechanism-1"], result["blocked_claim_ids"])
        self.assertEqual(["SI_REQUIRED_FOR_DECLARED_CLAIMS"], result["blocking_reasons"])

    def test_recommended_and_not_required_si_do_not_block_available_main(self):
        recommended = audit_source_coverage(
            study_id="S3", available_roles=["MAIN"], si_policy="RECOMMENDED"
        )
        not_required = audit_source_coverage(
            study_id="S4", available_roles=["MAIN"], si_policy="NOT_REQUIRED"
        )

        self.assertEqual("READY_WITH_LIMITATION", recommended["study_status"])
        self.assertEqual("READY", not_required["study_status"])
        self.assertEqual([], recommended["blocked_claim_ids"])
        self.assertEqual([], not_required["blocking_reasons"])

    def test_source_coverage_rejects_invalid_policy_and_roles(self):
        for kwargs in (
            {"available_roles": ["MAIN"], "si_policy": "OPTIONAL"},
            {"available_roles": ["MAIN", "OTHER"], "si_policy": "REQUIRED"},
            {"available_roles": ["MAIN"], "si_policy": "REQUIRED", "si_dependent_claim_ids": [""]},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                audit_source_coverage(study_id="S5", **kwargs)

    def test_terminal_suffix_candidates_are_not_confirmed_by_string(self):
        for doi, parent in [
            ("10.1021/acs.joc.9b02398.s001", "10.1021/acs.joc.9b02398"),
            ("10.1002/anie.202012345.s1", "10.1002/anie.202012345"),
            ("10.1039/d0cc00001a.supp", "10.1039/d0cc00001a"),
        ]:
            relation = supplement_parent_relation(doi)
            self.assertEqual(relation["candidate_parent_doi"], parent)
            self.assertIsNone(relation["confirmed_parent_doi"])
            self.assertEqual(relation["relation_status"], "PARENT_CANDIDATE_STRING_DERIVED")
        confirmed = supplement_parent_relation("10.1002/anie.202012345.s1", publisher_confirmed_parent_doi="10.1002/anie.202012345")
        self.assertEqual(confirmed["relation_status"], "PUBLISHER_CONFIRMED_PARENT")

    def test_negative_and_unsafe_values_are_not_suffix_reports(self):
        for value in [
            "10.1007/s00123-123-4567", "10.1234/abc.s1.extra", "10.1234/abc.s", "10.1234/s001",
            "https://doi.org/10.1234/abc.s1?x=1", "https://user@doi.org/10.1234/abc.s1", "10.1234/abc.s1#frag",
            "not-a-doi.s1",
        ]:
            self.assertIsNone(supplement_parent_relation(value)["candidate_parent_doi"], value)
        self.assertEqual(normalize_doi("https://doi.org/10.1234/ABC.s1."), "10.1234/abc.s1")

    def test_audit_preserves_all_matching_stable_identities(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pool = root / "pool.jsonl"; manifest = root / "manifest.json"
            pool.write_text("\n".join(json.dumps(x) for x in [
                {"candidate_id": "C1", "doi": "10.1000/a.s1"}, {"candidate_id": "C2", "doi": "10.1000/plain"},
            ]) + "\n")
            manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": [
                {"download_id": "C1_MAIN", "study_id": "C1", "doi": "10.1000/a.s1", "document_role": "MAIN", "url": "https://example.com/C1.pdf", "target_path": "sources/C1/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
                {"download_id": "C2_MAIN", "study_id": "C2", "doi": "10.1000/plain", "document_role": "MAIN", "url": "https://example.com/C2.pdf", "target_path": "sources/C2/MAIN.pdf", "source_class": "PUBLIC_DIRECT"},
            ]}))
            audit = audit_supplement_reports(pool, manifest)
            self.assertEqual(audit["counts"], {"candidate_pool_suffix_reports": 1, "acquisition_manifest_suffix_reports": 1})
            self.assertEqual({x["stable_identity"] for x in audit["records"]}, {"C1", "C1_MAIN"})
            self.assertTrue(all(x["study_count_role"] == "REQUIRES_REVIEW" for x in audit["records"]))

    def test_audit_rejects_invalid_candidate_stable_id_and_doi_records(self):
        invalid_records = [
            {"doi": "10.1000/plain"},
            {"candidate_id": "", "doi": "10.1000/a.s1"},
            {"candidate_id": "C1", "doi": 123},
        ]
        for record in invalid_records:
            with self.subTest(record=record), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                pool = root / "pool.jsonl"
                manifest = root / "manifest.json"
                pool.write_text(json.dumps(record) + "\n")
                manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": []}))

                with self.assertRaises(ValueError):
                    audit_supplement_reports(pool, manifest)

    def test_audit_rejects_malformed_publisher_confirmation_from_all_sources(self):
        valid_download = {
            "download_id": "D1",
            "study_id": "C1",
            "doi": "10.1000/a.s1",
            "document_role": "SI",
            "url": "https://example.com/supplement.pdf",
            "target_path": "sources/C1/SI/supplement.pdf",
            "source_class": "PUBLIC_DIRECT",
        }
        cases = [
            (
                {"candidate_id": "C1", "doi": "10.1000/a.s1", "publisher_confirmed_parent_doi": "malformed-confirmation"},
                [],
            ),
            (
                {"candidate_id": "C1", "doi": "10.1000/a.s1"},
                [{**valid_download, "publisher_confirmed_parent_doi": "malformed-confirmation"}],
            ),
        ]
        for candidate, downloads in cases:
            with self.subTest(source="candidate" if not downloads else "acquisition"), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                pool = root / "pool.jsonl"
                manifest = root / "manifest.json"
                pool.write_text(json.dumps(candidate) + "\n")
                manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": downloads}))

                with self.assertRaises(ValueError):
                    audit_supplement_reports(pool, manifest)

    def test_audit_rejects_invalid_manifest_schema_download_list_and_stable_ids(self):
        invalid_manifests = [
            {},
            {"downloads": []},
            {"schema_version": "wrong", "downloads": []},
            {"schema_version": "public-corpus-acquisition.v1", "downloads": {}},
            {"schema_version": "public-corpus-acquisition.v1", "downloads": [{"doi": "10.1000/plain"}]},
            {"schema_version": "public-corpus-acquisition.v1", "downloads": [{"download_id": "", "doi": "10.1000/a.s1"}]},
        ]
        for manifest_data in invalid_manifests:
            with self.subTest(manifest=manifest_data), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                pool = root / "pool.jsonl"
                manifest = root / "manifest.json"
                pool.write_text(json.dumps({"candidate_id": "C1", "doi": "10.1000/plain"}) + "\n")
                manifest.write_text(json.dumps(manifest_data))

                with self.assertRaises(ValueError):
                    audit_supplement_reports(pool, manifest)

    def test_only_explicit_publisher_confirmation_changes_study_count_role(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pool = root / "pool.jsonl"
            manifest = root / "manifest.json"
            pool.write_text("\n".join(json.dumps(record) for record in [
                {"candidate_id": "C1", "doi": "10.1000/a.s1"},
                {"candidate_id": "C2", "doi": "10.1000/b.s1", "publisher_confirmed_parent_doi": "10.1000/b"},
            ]) + "\n")
            manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": []}))

            audit = audit_supplement_reports(pool, manifest)

            roles = {record["stable_identity"]: record["study_count_role"] for record in audit["records"]}
            self.assertEqual(roles, {"C1": "REQUIRES_REVIEW", "C2": "NOT_AN_INDEPENDENT_STUDY"})
            statuses = {record["stable_identity"]: record["relation_status"] for record in audit["records"]}
            self.assertEqual(statuses["C1"], "PARENT_CANDIDATE_STRING_DERIVED")
            self.assertEqual(statuses["C2"], "PUBLISHER_CONFIRMED_PARENT")

    def test_audit_hashes_inputs_without_reading_complete_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pool = root / "pool.jsonl"
            manifest = root / "manifest.json"
            pool.write_text(json.dumps({"candidate_id": "C1", "doi": "10.1000/a.s1"}) + "\n")
            manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": []}))
            original_read_bytes = Path.read_bytes

            def guarded_read_bytes(path):
                if path in {pool, manifest}:
                    raise AssertionError("input hashing must stream")
                return original_read_bytes(path)

            with mock.patch.object(Path, "read_bytes", guarded_read_bytes):
                audit = audit_supplement_reports(pool, manifest)

            self.assertEqual(audit["counts"]["candidate_pool_suffix_reports"], 1)

    def test_audit_persists_only_safe_input_basenames_and_hashes(self):
        with tempfile.TemporaryDirectory(prefix="supplement-sensitive-root-") as temp:
            root = Path(temp)
            pool = root / "candidate-pool.jsonl"
            manifest = root / "acquisition-manifest.json"
            pool.write_text(
                json.dumps({"candidate_id": "C1", "doi": "10.1000/a.s1"}) + "\n",
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {"schema_version": "public-corpus-acquisition.v1", "downloads": []}
                ),
                encoding="utf-8",
            )

            audit = audit_supplement_reports(pool, manifest)

            self.assertEqual("candidate-pool.jsonl", audit["inputs"]["candidate_pool"]["path"])
            self.assertEqual(
                "acquisition-manifest.json",
                audit["inputs"]["acquisition_manifest"]["path"],
            )
            self.assertEqual(
                hashlib.sha256(pool.read_bytes()).hexdigest(),
                audit["inputs"]["candidate_pool"]["sha256"],
            )
            self.assertNotIn(str(root), json.dumps(audit))

    def test_records_without_optional_doi_are_valid_but_not_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pool = root / "pool.jsonl"
            manifest = root / "manifest.json"
            pool.write_text(json.dumps({"candidate_id": "C0"}) + "\n")
            manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": [{
                "download_id": "D0",
                "study_id": "C0",
                "document_role": "MAIN",
                "url": "https://example.com/paper.pdf",
                "target_path": "sources/C0/MAIN.pdf",
                "source_class": "PUBLIC_DIRECT",
            }]}))

            audit = audit_supplement_reports(pool, manifest)

            self.assertEqual(audit["records"], [])
            self.assertEqual(audit["counts"], {"candidate_pool_suffix_reports": 0, "acquisition_manifest_suffix_reports": 0})

    def test_acquisition_rows_require_all_six_preflight_fields(self):
        required_fields = ["download_id", "study_id", "document_role", "url", "target_path", "source_class"]
        complete = {
            "download_id": "D1",
            "study_id": "C1",
            "document_role": "MAIN",
            "url": "https://example.com/paper.pdf",
            "target_path": "sources/C1/MAIN.pdf",
            "source_class": "PUBLIC_DIRECT",
        }
        for missing in required_fields:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                pool = root / "pool.jsonl"
                manifest = root / "manifest.json"
                pool.write_text(json.dumps({"candidate_id": "C1"}) + "\n")
                row = dict(complete)
                row.pop(missing)
                manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": [row]}))

                with self.assertRaises(ValueError):
                    audit_supplement_reports(pool, manifest)

    def test_acquisition_rows_reject_unsupported_role_and_invalid_field_shapes(self):
        complete = {
            "download_id": "D1",
            "study_id": "C1",
            "document_role": "MAIN",
            "url": "https://example.com/paper.pdf",
            "target_path": "sources/C1/MAIN.pdf",
            "source_class": "PUBLIC_DIRECT",
        }
        invalid_updates = [
            {"download_id": ""},
            {"study_id": ""},
            {"document_role": "SUPPLEMENT"},
            {"document_role": ["MAIN"]},
            {"url": None},
            {"target_path": 123},
            {"source_class": []},
        ]
        for update in invalid_updates:
            with self.subTest(update=update), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                pool = root / "pool.jsonl"
                manifest = root / "manifest.json"
                pool.write_text(json.dumps({"candidate_id": "C1"}) + "\n")
                row = {**complete, **update}
                manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": [row]}))

                with self.assertRaises(ValueError):
                    audit_supplement_reports(pool, manifest)

    def test_acquisition_audit_normalizes_shared_manifest_identities(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pool = root / "pool.jsonl"
            manifest = root / "manifest.json"
            pool.write_text(json.dumps({"candidate_id": "C0"}) + "\n")
            manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": [{
                "download_id": "  SHARED_MAIN  ",
                "study_id": "  SHARED_STUDY  ",
                "doi": "https://doi.org/10.1000/SHARED.S1.",
                "document_role": "SI",
                "url": "https://example.com/supplement.pdf",
                "target_path": "sources/SHARED_STUDY/SI/supplement.pdf",
                "source_class": "PUBLIC_DIRECT",
            }]}))

            audit = audit_supplement_reports(pool, manifest)

            record = audit["records"][0]
            self.assertEqual(record["stable_identity"], "SHARED_MAIN")
            self.assertEqual(record["candidate_id"], "SHARED_STUDY")
            self.assertEqual(record["doi"], "10.1000/shared.s1")

    def test_acquisition_audit_rejects_invalid_shared_manifest_fields(self):
        invalid_updates = [
            {"download_id": "D／1"},
            {"expected_format": "TXT"},
            {"expected_format": ["PDF"]},
            {"doi": "https://doi.org/10.1000/shared.s1?credential=hidden"},
            {"doi": 123},
        ]
        for update in invalid_updates:
            with self.subTest(update=update), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                pool = root / "pool.jsonl"
                manifest = root / "manifest.json"
                pool.write_text(json.dumps({"candidate_id": "C0"}) + "\n")
                row = {
                    "download_id": "SHARED_INVALID",
                    "study_id": "SHARED_INVALID",
                    "document_role": "MAIN",
                    "url": "https://example.com/paper.pdf",
                    "target_path": "sources/SHARED_INVALID/MAIN.pdf",
                    "source_class": "PUBLIC_DIRECT",
                    **update,
                }
                manifest.write_text(json.dumps({"schema_version": "public-corpus-acquisition.v1", "downloads": [row]}))

                with self.assertRaises(ValueError):
                    audit_supplement_reports(pool, manifest)


if __name__ == "__main__":
    unittest.main()
