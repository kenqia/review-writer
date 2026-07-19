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
    adapt_legacy_case_package,
    validate_snapshot_package,
    seal_snapshot_package,
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
            self.assertEqual(status.returncode, 2)
            self.assertIn("CONFIG_SNAPSHOT_PACKAGE_REQUIRED", status.stderr)

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

    def test_snapshot_package_validates_bound_records_and_detects_each_tamper(self) -> None:
        package = seal_snapshot_package(json.loads((FIXTURE.parent / "case01-adapter/fixture.json").read_text(encoding="utf-8")))
        view = validate_snapshot_package(package)
        self.assertTrue(view["closed"])
        self.assertEqual(view["summary"], {"project": "CLOSED", "corpus": "CLOSED", "claims": "CLOSED", "checkpoint": "CLOSED", "run": "CLOSED", "release": "CLOSED"})
        for path in (("run", "resolved_config_sha256"), ("release", "artifact_ref", "content_sha256"), ("checkpoint", "approved_artifact_sha256"), ("decisions", 0, "event_type")):
            broken = json.loads(json.dumps(package))
            target = broken
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = "BAD" if path[-1] != "event_type" else "UNKNOWN"
            with self.assertRaises(ContractError):
                validate_snapshot_package(broken)

    def test_claim_validation_rejects_zero_evidence_ai_inference_and_stale_dependencies(self) -> None:
        package = seal_snapshot_package(json.loads((FIXTURE.parent / "case01-adapter/fixture.json").read_text(encoding="utf-8")))
        zero = json.loads(json.dumps(package))
        zero["claims"][0]["evidence_refs"] = []
        with self.assertRaises(ContractError):
            validate_snapshot_package(zero)
        ai = json.loads(json.dumps(package))
        ai["decisions"][1]["event_type"] = "AI_INFERENCE"
        with self.assertRaises(ContractError):
            validate_snapshot_package(ai)
        stale = json.loads(json.dumps(package))
        stale["claims"].append({"project_id": stale["project_id"], "claim_id": "synthesis", "claim_version": 1, "claim_version_id": "synthesis@1", "claim_text": "Synthesis", "claim_text_sha256": hashlib.sha256(b"Synthesis").hexdigest(), "epistemic_class": "REVIEWER_SYNTHESIS", "evidence_refs": [], "supporting_claim_refs": ["missing@1"], "conflict_refs": []})
        stale["decisions"].extend([{"event_id": "d3", "claim_version_id": "synthesis@1", "event_type": "EVIDENCE_SUPPORT", "evidence_support_status": "SUPPORTED"}, {"event_id": "d4", "claim_version_id": "synthesis@1", "event_type": "REGISTER"}])
        with self.assertRaises(ContractError):
            validate_snapshot_package(stale)

    def test_broad_portability_failure_is_exactly_the_preexisting_orch_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "portability.json"
            run = subprocess.run(["python3", "scripts/check_portability.py", "--output-json", str(output), "--output-md", str(Path(tmp) / "portability.md"), "--strict"], cwd=ROOT, text=True, capture_output=True, check=False, env={**__import__("os").environ, "TMPDIR": tmp})
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(report["errors"], [{"path": "docs/agent-tasks/ORCH-001/owner_replacement_2.json", "line": 9, "pattern": "kenqia_home", "severity": "error", "context": "\"/home/kenqia/templates/kenqia-ai-project-template orchestration paths\""}])

    def test_source_path_rejects_internal_and_external_symlink_and_hash_tamper(self) -> None:
        from review_writer.project.contract import validate_source_path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"; root.mkdir(); good = root / "good.txt"; good.write_text("one")
            self.assertEqual(validate_source_path(root, "good.txt").read_text(), "one")
            good.write_text("two")
            self.assertNotEqual(hashlib.sha256(b"one").hexdigest(), hashlib.sha256(validate_source_path(root, "good.txt").read_bytes()).hexdigest())
            (root / "internal.txt").symlink_to(good)
            with self.assertRaises(ContractError): validate_source_path(root, "internal.txt")
            outside = Path(tmp) / "outside.txt"; outside.write_text("outside")
            (root / "external.txt").symlink_to(outside)
            with self.assertRaises(ContractError): validate_source_path(root, "external.txt")

    def test_production_multi_input_validator_rejects_case_collision_and_generic_core_has_no_case_id(self) -> None:
        from review_writer.project.path_safety import PathSafetyError, validate_source_inputs
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "a").mkdir(); (root / "a/x.txt").write_text("x")
            with self.assertRaises(PathSafetyError): validate_source_inputs(root, ["a/x.txt", "a/X.txt"])
        for path in (ROOT / "review_writer/project/contract.py", ROOT / "schemas/project/project_manifest.schema.json", ROOT / "scripts/project.py"):
            self.assertNotIn("case-01", path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
