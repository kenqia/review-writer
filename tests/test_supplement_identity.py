from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from review_writer.acquisition.supplement_identity import audit_supplement_reports, normalize_doi, supplement_parent_relation


class SupplementIdentityTests(unittest.TestCase):
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
            manifest.write_text(json.dumps({"downloads": [
                {"download_id": "C1_MAIN", "study_id": "C1", "doi": "10.1000/a.s1", "document_role": "MAIN"},
                {"download_id": "C2_MAIN", "study_id": "C2", "doi": "10.1000/plain", "document_role": "MAIN"},
            ]}))
            audit = audit_supplement_reports(pool, manifest)
            self.assertEqual(audit["counts"], {"candidate_pool_suffix_reports": 1, "acquisition_manifest_suffix_reports": 1})
            self.assertEqual({x["stable_identity"] for x in audit["records"]}, {"C1", "C1_MAIN"})
            self.assertTrue(all(x["study_count_role"] == "NOT_AN_INDEPENDENT_STUDY" for x in audit["records"]))


if __name__ == "__main__":
    unittest.main()
