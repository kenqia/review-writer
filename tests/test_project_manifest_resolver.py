#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "review_writer/project/manifest.py"
CLI_PATH = ROOT / "scripts/project.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def manifest() -> dict:
    return {
        "manifest_schema_version": "project-manifest-1.0",
        "project_id": "synthetic-non-allene",
        "project_title": "Synthetic Nickel Coupling Review",
        "initial_user_intent": {
            "goal": "Compare evidence for Café catalyst behavior.",
            "scope": "Line one\nLine two",
        },
        "discovery_policy": "CLOSED_CORPUS",
        "output_language": "en",
        "citation_style": "BRACKETED_NUMERIC",
        "paths": {
            "seed_source_root": "inputs/papers",
            "project_data_root": "outputs/project-state",
            "export_root": "exports",
        },
        "initial_source_inputs": [
            {
                "source_id": "SYN001_MAIN",
                "paper_id": "SYN001",
                "relative_path": "syn001/main.pdf",
                "document_role": "MAIN",
                "usage_role": "EVIDENCE",
            }
        ],
        "network_policy": "OFFLINE_ONLY",
    }


class ProjectManifestResolverTests(unittest.TestCase):
    def api(self):
        self.assertTrue(MODULE_PATH.is_file(), f"missing shared manifest resolver: {MODULE_PATH}")
        return importlib.import_module("review_writer.project.manifest")

    def resolve(self, value: dict) -> tuple[dict, str]:
        api = self.api()
        resolved = api.resolve_project_manifest(value)
        return resolved, api.resolved_config_sha256(resolved)

    def test_nfc_nfd_line_endings_and_outer_whitespace_are_hash_equivalent(self) -> None:
        nfc = manifest()
        nfc["initial_user_intent"] = {
            "goal": "\u2003Café goal\u2002",
            "scope": " first\r\nsecond ",
        }
        nfd = manifest()
        nfd["initial_user_intent"] = {
            "goal": "Cafe\u0301 goal",
            "scope": "first\rsecond",
        }
        lf = manifest()
        lf["initial_user_intent"] = {
            "goal": "Café goal",
            "scope": "first\nsecond",
        }

        resolved_nfc, hash_nfc = self.resolve(nfc)
        resolved_nfd, hash_nfd = self.resolve(nfd)
        resolved_lf, hash_lf = self.resolve(lf)

        self.assertEqual(hash_nfc, hash_nfd)
        self.assertEqual(hash_nfd, hash_lf)
        self.assertEqual(resolved_nfc["initial_user_intent"]["goal"], "Café goal")
        self.assertEqual(resolved_nfc["initial_user_intent"]["scope"], "first\nsecond")

    def test_resolver_does_not_mutate_input_and_internal_changes_change_hash(self) -> None:
        original = manifest()
        original["initial_user_intent"]["goal"] = "  Stable goal  "
        before = copy.deepcopy(original)
        _resolved, original_hash = self.resolve(original)
        self.assertEqual(original, before)

        changed = copy.deepcopy(original)
        changed["initial_user_intent"]["goal"] = "Stable  goal"
        _changed_resolved, changed_hash = self.resolve(changed)
        self.assertNotEqual(original_hash, changed_hash)

        changed_line = copy.deepcopy(original)
        changed_line["initial_user_intent"]["goal"] = "Stable\ngoal"
        _line_resolved, line_hash = self.resolve(changed_line)
        self.assertNotEqual(original_hash, line_hash)

    def test_blank_control_and_post_normalization_lengths_are_enforced(self) -> None:
        api = self.api()

        for blank in ("", " \t\n\u2003 "):
            value = manifest()
            value["initial_user_intent"]["goal"] = blank
            with self.assertRaises(api.ManifestResolutionError):
                api.resolve_project_manifest(value)

        for control in ("bad\x00value", "bad\x1fvalue"):
            value = manifest()
            value["initial_user_intent"]["scope"] = control
            with self.assertRaises(api.ManifestResolutionError):
                api.resolve_project_manifest(value)

        allowed = manifest()
        allowed["initial_user_intent"]["scope"] = "tab\tkept\nline"
        api.resolve_project_manifest(allowed)

        nfd_at_limit = manifest()
        nfd_at_limit["initial_user_intent"]["goal"] = "e\u0301" * 4000
        resolved = api.resolve_project_manifest(nfd_at_limit)
        self.assertEqual(len(resolved["initial_user_intent"]["goal"]), 4000)

        too_long = manifest()
        too_long["initial_user_intent"]["goal"] = "e\u0301" * 4001
        with self.assertRaises(api.ManifestResolutionError):
            api.resolve_project_manifest(too_long)

        scope_too_long = manifest()
        scope_too_long["initial_user_intent"]["scope"] = "界" * 8001
        with self.assertRaises(api.ManifestResolutionError):
            api.resolve_project_manifest(scope_too_long)

    def test_validate_and_status_cli_share_normalized_hash_behavior(self) -> None:
        self.assertTrue(CLI_PATH.is_file(), f"missing project CLI: {CLI_PATH}")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "project.manifest.json"
            equivalent_path = root / "equivalent.manifest.json"
            changed_path = root / "changed.manifest.json"
            snapshot_path = root / "run_manifest.json"

            base = manifest()
            base["initial_user_intent"]["goal"] = "Café goal\r\ncontinued"
            source_path = root / "inputs/papers/syn001/main.pdf"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"synthetic existing resolver input")
            manifest_path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
            original_bytes = manifest_path.read_bytes()

            validate = subprocess.run(
                [sys.executable, str(CLI_PATH), "validate", "--manifest", str(manifest_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr)
            validate_report = json.loads(validate.stdout)
            self.assertEqual(validate_report["status"], "VALID")
            self.assertEqual(manifest_path.read_bytes(), original_bytes)

            snapshot_path.write_text(
                json.dumps({"resolved_config_sha256": validate_report["resolved_config_sha256"], "snapshot_package": (lambda p: __import__("review_writer.project.contract", fromlist=["seal_snapshot_package"]).seal_snapshot_package(p))({"project_id": "fixture", "resolved_config_sha256": validate_report["resolved_config_sha256"], "artifact": {"artifact_id": "a", "content": {"x": 1}, "artifact_ref": {"artifact_id": "a", "content_sha256": ""}}, "sources": [{"project_id": "fixture", "source_id": "s", "source_version": "v", "content_sha256": "b" * 64, "governance_status": "INCLUDED", "usage_role": "EVIDENCE", "availability_status": "PARSED", "integrity_status": "VALIDATED", "active_parse_artifact_id": "p"}], "parses": [{"project_id": "fixture", "parse_artifact_id": "p", "source_id": "s", "source_content_sha256": "b" * 64, "validation_status": "VALIDATED"}], "claims": [{"project_id": "fixture", "claim_id": "c", "claim_version": 1, "claim_version_id": "c@1", "claim_text": "x", "claim_text_sha256": __import__("hashlib").sha256(b"x").hexdigest(), "epistemic_class": "SOURCE_OBSERVATION", "evidence_refs": [{"source_id": "s", "source_version": "v", "parse_artifact_id": "p", "source_content_sha256": "b" * 64, "locator": "p", "excerpt_sha256": "c" * 64}], "supporting_claim_refs": [], "conflict_refs": []}], "decisions": [{"event_id": "e", "claim_version_id": "c@1", "event_type": "EVIDENCE_SUPPORT", "evidence_support_status": "SUPPORTED"}, {"event_id": "r", "claim_version_id": "c@1", "event_type": "REGISTER"}], "conflicts": [], "checkpoint": {"project_id": "fixture", "resolved_config_sha256": validate_report["resolved_config_sha256"], "approved_artifact_sha256": ""}, "run": {"project_id": "fixture", "resolved_config_sha256": validate_report["resolved_config_sha256"], "snapshot_artifact_sha256": ""}, "release": {"project_id": "fixture", "resolved_config_sha256": validate_report["resolved_config_sha256"], "artifact_ref": {"artifact_id": "a", "content_sha256": ""}}})}),
                encoding="utf-8",
            )

            snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            def unseal(value):
                if isinstance(value, dict):
                    value.pop("record_sha256", None)
                    for nested in value.values(): unseal(nested)
                elif isinstance(value, list):
                    for nested in value: unseal(nested)
            unseal(snapshot_payload["snapshot_package"])
            fixture_source = snapshot_payload["snapshot_package"]["sources"][0]
            fixture_source.update({"project_id": base["project_id"], "source_id": "SYN001_MAIN", "document_role": "MAIN", "relative_path": "syn001/main.pdf", "content_sha256": __import__("hashlib").sha256(source_path.read_bytes()).hexdigest()})
            snapshot_payload["snapshot_package"]["project_id"] = base["project_id"]
            snapshot_payload["snapshot_package"]["parses"][0].update({"project_id": base["project_id"], "source_id": "SYN001_MAIN", "source_content_sha256": fixture_source["content_sha256"]})
            snapshot_payload["snapshot_package"]["claims"][0]["project_id"] = base["project_id"]
            snapshot_payload["snapshot_package"]["claims"][0]["evidence_refs"][0].update({"source_id": "SYN001_MAIN", "source_content_sha256": fixture_source["content_sha256"]})
            for key in ("checkpoint", "run", "release"): snapshot_payload["snapshot_package"][key]["project_id"] = base["project_id"]
            snapshot_payload["snapshot_package"] = __import__("review_writer.project.contract", fromlist=["seal_snapshot_package"]).seal_snapshot_package({key: value for key, value in snapshot_payload["snapshot_package"].items() if key != "record_sha256"})
            snapshot_path.write_text(json.dumps(snapshot_payload), encoding="utf-8")
            project_mismatch = copy.deepcopy(snapshot_payload)
            unseal(project_mismatch["snapshot_package"])
            for record in [project_mismatch["snapshot_package"], *project_mismatch["snapshot_package"]["sources"], *project_mismatch["snapshot_package"]["parses"], *project_mismatch["snapshot_package"]["claims"], project_mismatch["snapshot_package"]["checkpoint"], project_mismatch["snapshot_package"]["run"], project_mismatch["snapshot_package"]["release"]]: record["project_id"] = "other-project"
            project_mismatch["snapshot_package"] = __import__("review_writer.project.contract", fromlist=["seal_snapshot_package"]).seal_snapshot_package(project_mismatch["snapshot_package"])
            mismatch_path = root / "project-mismatch.json"; mismatch_path.write_text(json.dumps(project_mismatch), encoding="utf-8")
            mismatch = subprocess.run([sys.executable, str(CLI_PATH), "status", "--manifest", str(manifest_path), "--snapshot", str(mismatch_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(mismatch.returncode, 2); self.assertIn("CONFIG_SNAPSHOT_PROJECT_DRIFT", mismatch.stderr)
            corpus_mismatch = copy.deepcopy(snapshot_payload)
            unseal(corpus_mismatch["snapshot_package"]); changed_hash = "d" * 64
            corpus_mismatch["snapshot_package"]["sources"][0]["content_sha256"] = changed_hash; corpus_mismatch["snapshot_package"]["parses"][0]["source_content_sha256"] = changed_hash; corpus_mismatch["snapshot_package"]["claims"][0]["evidence_refs"][0]["source_content_sha256"] = changed_hash
            corpus_mismatch["snapshot_package"] = __import__("review_writer.project.contract", fromlist=["seal_snapshot_package"]).seal_snapshot_package(corpus_mismatch["snapshot_package"])
            mismatch_path.write_text(json.dumps(corpus_mismatch), encoding="utf-8")
            mismatch = subprocess.run([sys.executable, str(CLI_PATH), "status", "--manifest", str(manifest_path), "--snapshot", str(mismatch_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(mismatch.returncode, 2); self.assertIn("CONFIG_SNAPSHOT_CORPUS_DRIFT", mismatch.stderr)
            equivalent = copy.deepcopy(base)
            equivalent["initial_user_intent"]["goal"] = "  Cafe\u0301 goal\ncontinued\u2003"
            equivalent_path.write_text(json.dumps(equivalent, ensure_ascii=False), encoding="utf-8")
            status = subprocess.run(
                [
                    sys.executable,
                    str(CLI_PATH),
                    "status",
                    "--manifest",
                    str(equivalent_path),
                    "--snapshot",
                    str(snapshot_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)["status"], "CONFIG_CURRENT")

            changed = copy.deepcopy(base)
            changed["initial_user_intent"]["scope"] += "\nA material internal change."
            changed_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            changed_status = subprocess.run(
                [
                    sys.executable,
                    str(CLI_PATH),
                    "status",
                    "--manifest",
                    str(changed_path),
                    "--snapshot",
                    str(snapshot_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(changed_status.returncode, 0, changed_status.stderr)
            changed_report = json.loads(changed_status.stdout)
            self.assertEqual(changed_report["status"], "CONFIG_CHANGED")
            self.assertEqual(
                changed_report["affected_stages"],
                ["CORPUS", "CLAIMS", "CHECKPOINT", "DRAFT", "RUN", "RELEASE"],
            )


if __name__ == "__main__":
    unittest.main()
