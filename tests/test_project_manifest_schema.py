#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/project/project_manifest.schema.json"


def valid_manifest() -> dict:
    return {
        "manifest_schema_version": "project-manifest-1.0",
        "project_id": "synthetic-non-allene",
        "project_title": "Synthetic Nickel Coupling Review",
        "initial_user_intent": {
            "goal": "Compare bounded evidence for two nickel coupling methods.",
            "scope": "Use only the supplied main articles and supporting information.",
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
            },
            {
                "source_id": "SYN001_SI_01",
                "paper_id": "SYN001",
                "relative_path": "syn001/si-01.pdf",
                "document_role": "SI",
                "usage_role": "EVIDENCE",
            },
        ],
        "network_policy": "OFFLINE_ONLY",
    }


class ProjectManifestSchemaTests(unittest.TestCase):
    def load_schema(self) -> dict:
        self.assertTrue(SCHEMA_PATH.is_file(), f"missing ProjectManifest schema: {SCHEMA_PATH}")
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return schema

    def assert_valid(self, manifest: dict) -> None:
        Draft202012Validator(self.load_schema()).validate(manifest)

    def assert_invalid(self, manifest: dict) -> None:
        errors = list(Draft202012Validator(self.load_schema()).iter_errors(manifest))
        self.assertTrue(errors, f"manifest unexpectedly valid: {manifest}")

    def test_accepts_locked_minimum_manifest_and_closed_adapter_id(self) -> None:
        manifest = valid_manifest()
        manifest["adapter_ref"] = "case-01-frozen-v1"
        self.assert_valid(manifest)

    def test_rejects_removed_provider_and_unknown_fields(self) -> None:
        manifest = valid_manifest()
        manifest["provider_profile_ref"] = "do-not-admit"
        self.assert_invalid(manifest)

        source_extra = valid_manifest()
        source_extra["initial_source_inputs"][0]["doi"] = "10.example/not-admitted"
        self.assert_invalid(source_extra)

    def test_locks_m0_policy_values_and_source_enums(self) -> None:
        for field, value in (
            ("discovery_policy", "MODEL_ASSISTED"),
            ("network_policy", "EXPLICIT_NETWORK"),
        ):
            manifest = valid_manifest()
            manifest[field] = value
            self.assert_invalid(manifest)

        for field, value in (
            ("document_role", "UNKNOWN"),
            ("usage_role", "PENDING_FULL_TEXT"),
        ):
            manifest = valid_manifest()
            manifest["initial_source_inputs"][0][field] = value
            self.assert_invalid(manifest)

        for field, value in (("output_language", "zh"), ("citation_style", "bracketed-numeric")):
            manifest = valid_manifest()
            manifest[field] = value
            self.assert_invalid(manifest)

    def test_rejects_noncanonical_and_escaping_paths_at_schema_boundary(self) -> None:
        bad_paths = (
            "/absolute/path",
            "C:/windows/path",
            "C:\\windows\\path",
            "\\\\server\\share\\paper.pdf",
            "../escape.pdf",
            "paper/../../escape.pdf",
            "paper\\main.pdf",
            "paper//main.pdf",
        )
        for bad_path in bad_paths:
            manifest = valid_manifest()
            manifest["initial_source_inputs"][0]["relative_path"] = bad_path
            self.assert_invalid(manifest)

    def test_schema_declares_runtime_invariants_that_require_filesystem_checks(self) -> None:
        schema = self.load_schema()
        self.assertEqual(
            set(schema["x-runtime-invariants"]),
            {
                "PROJECT_ID_LOCKED_AFTER_PROJECT_RECORDS",
                "SOURCE_ID_UNIQUE",
                "NORMALIZED_SOURCE_PATH_UNIQUE_CROSS_PLATFORM",
                "EXACTLY_ONE_MAIN_PER_PAPER",
                "SI_REQUIRES_MAIN",
                "SOURCE_PATH_MUST_BE_REGULAR_FILE",
                "SOURCE_PATH_MUST_RESOLVE_WITHIN_SEED_ROOT",
                "SOURCE_CONTENT_HASH_CAPTURED_IN_SNAPSHOT",
                "SOURCE_CONTENT_HASH_REVERIFIED_ON_CONSUME",
                "ADAPTER_REF_CLOSED_ALLOWLIST",
            },
        )

    def test_requires_exact_locked_top_level_and_source_item_fields(self) -> None:
        schema = self.load_schema()
        self.assertEqual(
            set(schema["required"]),
            {
                "manifest_schema_version",
                "project_id",
                "project_title",
                "initial_user_intent",
                "discovery_policy",
                "output_language",
                "citation_style",
                "paths",
                "initial_source_inputs",
                "network_policy",
            },
        )
        self.assertEqual(
            set(schema["$defs"]["sourceInput"]["required"]),
            {"source_id", "paper_id", "relative_path", "document_role", "usage_role"},
        )

        for field in ("manifest_version", "manifest_version_id", "contract_refs", "provider_profile_ref"):
            manifest = valid_manifest()
            manifest[field] = "not-admitted"
            self.assert_invalid(manifest)


if __name__ == "__main__":
    unittest.main()
