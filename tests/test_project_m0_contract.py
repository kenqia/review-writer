#!/usr/bin/env python3
"""Offline acceptance tests for the M0-PR-A contract slice."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_writer.project.contract import (
    ContractError,
    claim_registry_view,
    conflict_compatibility_matrix,
    create_immutable_json,
    snapshot_view,
    source_is_claim_eligible,
    validate_manifest_inputs,
    verify_closure,
    adapt_legacy_case_sources,
    project_id_is_locked,
)


FIXTURE = ROOT / "tests/fixtures/m0/synthetic"
CLI = ROOT / "scripts/project.py"


class M0ContractTests(unittest.TestCase):
    def load_manifest(self) -> dict:
        return json.loads((FIXTURE / "project.manifest.json").read_text(encoding="utf-8"))

    def test_synthetic_manifest_validates_files_pairing_hashes_and_portable_collisions(self) -> None:
        manifest = self.load_manifest()
        resolved = validate_manifest_inputs(manifest, FIXTURE)
        self.assertEqual(set(resolved["source_hashes"]), {"SYN100_MAIN", "SYN100_SI"})
        bad = json.loads(json.dumps(manifest))
        bad["initial_source_inputs"][1]["relative_path"] = "syn100/MAIN.txt"
        with self.assertRaisesRegex(ContractError, "NORMALIZED_SOURCE_PATH_DUPLICATE"):
            validate_manifest_inputs(bad, FIXTURE)

    def test_cli_validate_and_status_report_source_hashes_and_closure(self) -> None:
        validate = subprocess.run(["python3", str(CLI), "validate", "--manifest", str(FIXTURE / "project.manifest.json")], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(validate.returncode, 0, validate.stderr)
        report = json.loads(validate.stdout)
        self.assertEqual(set(report["source_hashes"]), {"SYN100_MAIN", "SYN100_SI"})
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.json"
            snapshot.write_text(json.dumps({"resolved_config_sha256": report["resolved_config_sha256"], "closure": {"artifact": {"artifact_id": "draft", "artifact_sha256": "c" * 64}, "checkpoint": {"approved_artifact_sha256": "c" * 64}, "run": {"snapshot_artifact_sha256": "c" * 64}, "release": {"release_artifact_sha256": "c" * 64}}}), encoding="utf-8")
            status = subprocess.run(["python3", str(CLI), "status", "--manifest", str(FIXTURE / "project.manifest.json"), "--snapshot", str(snapshot)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertTrue(json.loads(status.stdout)["closure"]["closed"])

    def test_claim_registry_requires_registered_supported_current_eligible_evidence(self) -> None:
        good_hash = hashlib.sha256((FIXTURE / "inputs/papers/syn100/main.txt").read_bytes()).hexdigest()
        sources = [{"source_id": "SYN100_MAIN", "source_version": "v1", "content_sha256": good_hash,
                    "governance_status": "INCLUDED", "usage_role": "EVIDENCE",
                    "availability_status": "PARSED", "integrity_status": "VALIDATED",
                    "active_parse_artifact_id": "parse-1"}]
        claim = {"claim_version_id": "claim-1@1", "claim_id": "claim-1", "claim_version": 1,
                 "claim_text": "Synthetic observation.", "epistemic_class": "SOURCE_OBSERVATION",
                 "evidence_refs": [{"source_id": "SYN100_MAIN", "source_version": "v1",
                                    "parse_artifact_id": "parse-1", "source_content_sha256": good_hash,
                                    "locator": "p. 1", "excerpt_sha256": "a" * 64}]}
        decisions = [{"event_id": "evidence-1", "claim_version_id": "claim-1@1", "event_type": "EVIDENCE_SUPPORT",
                      "evidence_support_status": "SUPPORTED"},
                     {"event_id": "register-1", "claim_version_id": "claim-1@1", "event_type": "REGISTER"},
                     {"event_id": "checkpoint-1", "claim_version_id": "claim-1@1", "event_type": "CHECKPOINT_APPROVE"}]
        view = claim_registry_view([claim], decisions, sources, active_scope_claim_ids={"claim-1"})
        self.assertTrue(view["claim-1@1"]["writing_eligible"])
        self.assertTrue(source_is_claim_eligible(sources[0], claim["evidence_refs"][0]))
        excluded = dict(sources[0], governance_status="EXCLUDED")
        self.assertFalse(claim_registry_view([claim], decisions, [excluded], active_scope_claim_ids={"claim-1"})["claim-1@1"]["writing_eligible"])
        checkpoint_only = claim_registry_view([claim], decisions[2:], sources, active_scope_claim_ids={"claim-1"})
        self.assertEqual(checkpoint_only["claim-1@1"]["governance_status"], "CANDIDATE")

    def test_conflict_matrix_and_immutable_closure_reject_tamper_and_overwrite(self) -> None:
        matrix = conflict_compatibility_matrix({"comparability": "EXPLICITLY_INCOMPARABLE", "classification": "SOURCE_INTERNAL_CONFLICT", "status": "EXCLUDED"})
        self.assertFalse(matrix["permits_manuscript_treatment"])
        with self.assertRaisesRegex(ContractError, "CONFLICT_COMBINATION_INVALID"):
            conflict_compatibility_matrix({"comparability": "EXPLICITLY_INCOMPARABLE", "classification": "ACADEMIC_CONTROVERSY", "status": "ACTIVE"})
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "snapshot.json"
            record = {"artifact_ref": {"artifact_id": "snapshot-1", "artifact_sha256": ""}, "payload": {"ok": True}}
            written = create_immutable_json(destination, record)
            self.assertTrue(verify_closure(written))
            with self.assertRaisesRegex(ContractError, "IMMUTABLE_OUTPUT_EXISTS"):
                create_immutable_json(destination, record)
            tampered = json.loads(destination.read_text(encoding="utf-8"))
            tampered["payload"]["ok"] = False
            destination.write_text(json.dumps(tampered), encoding="utf-8")
            self.assertFalse(verify_closure(destination))

    def test_snapshot_view_binds_checkpoint_run_release_to_exact_hashes(self) -> None:
        view = snapshot_view({"artifact_id": "draft", "artifact_sha256": "b" * 64},
                             {"approved_artifact_sha256": "b" * 64},
                             {"snapshot_artifact_sha256": "b" * 64},
                             {"release_artifact_sha256": "b" * 64})
        self.assertTrue(view["closed"])
        self.assertFalse(snapshot_view({"artifact_id": "draft", "artifact_sha256": "b" * 64},
                                       {"approved_artifact_sha256": "a" * 64},
                                       {"snapshot_artifact_sha256": "b" * 64},
                                       {"release_artifact_sha256": "b" * 64})["closed"])

    def test_frozen_adapter_maps_legacy_role_without_mutating_input_and_project_id_lock_is_explicit(self) -> None:
        legacy = json.loads((FIXTURE.parent / "case01-adapter/legacy_sources.json").read_text(encoding="utf-8"))
        adapted = adapt_legacy_case_sources(legacy)
        self.assertEqual(legacy[0]["source_role"], "MAIN")
        self.assertEqual(adapted[0]["document_role"], "MAIN")
        self.assertEqual(adapted[1]["document_role"], "SI")
        self.assertTrue(project_id_is_locked([{"record_type": "RunManifest"}]))
        self.assertFalse(project_id_is_locked([]))


if __name__ == "__main__":
    unittest.main()
