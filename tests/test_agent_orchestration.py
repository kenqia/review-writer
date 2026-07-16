#!/usr/bin/env python3
"""Focused offline checks for the Owner-Review orchestration layer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "agent-orchestration"
sys.path.insert(0, str(SCRIPTS_DIR))

import orchestration_lib  # noqa: E402
import run_dry_run  # noqa: E402


class AgentOrchestrationTests(unittest.TestCase):
    def test_required_roles_and_descriptors_enforce_read_only_fresh_reviews(self) -> None:
        expected_roles = {
            "leader",
            "implementation-owner",
            "scientific-reviewer",
            "artifact-reviewer",
            "final-verifier",
            "explorer",
            "integration-owner",
        }
        role_dir = REPO_ROOT / "docs" / "agent-roles"
        descriptor_dir = REPO_ROOT / ".codex" / "agents"
        self.assertTrue(expected_roles.issubset({path.stem for path in role_dir.glob("*.md")}))
        self.assertTrue(expected_roles.issubset({path.stem for path in descriptor_dir.glob("*.toml")}))
        policy = orchestration_lib.validate_role_policy(REPO_ROOT)
        self.assertEqual([], policy.errors)

    def test_required_role_descriptors_are_not_ignored(self) -> None:
        for role in orchestration_lib.ROLES:
            descriptor = f".codex/agents/{role}.toml"
            result = subprocess.run(
                ["git", "check-ignore", "-q", "--", descriptor],
                cwd=REPO_ROOT,
                check=False,
            )
            self.assertNotEqual(0, result.returncode, descriptor)
        config = subprocess.run(
            ["git", "check-ignore", "-q", "--", ".codex/config.toml"],
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(0, config.returncode)

    def test_contract_examples_validate_and_unsafe_paths_are_rejected(self) -> None:
        package_result = orchestration_lib.validate_task_package(
            REPO_ROOT / "docs" / "agent-tasks" / "ORCH-001"
        )
        self.assertEqual([], package_result.errors)
        examples = REPO_ROOT / "docs" / "agent-contracts" / "examples"
        for kind in ("findings", "worker_result"):
            payload = json.loads((examples / f"{kind}.example.json").read_text(encoding="utf-8"))
            self.assertEqual([], orchestration_lib.validate_contract(kind, payload))
            payload["artifact_paths"] = ["../unsafe"]
            self.assertTrue(orchestration_lib.validate_contract(kind, payload))

    def test_full_contracts_reject_missing_fields_and_invalid_nested_values(self) -> None:
        task = orchestration_lib.load_json(REPO_ROOT / "docs/agent-tasks/ORCH-001/task_spec.json")
        matrix = orchestration_lib.load_json(REPO_ROOT / "docs/agent-tasks/ORCH-001/acceptance_matrix.json")
        findings = orchestration_lib.load_json(REPO_ROOT / "docs/agent-contracts/examples/findings.example.json")
        worker_result = orchestration_lib.load_json(REPO_ROOT / "docs/agent-contracts/examples/worker_result.example.json")
        self.assertEqual([], orchestration_lib.validate_task_spec(task))
        self.assertEqual([], orchestration_lib.validate_acceptance_matrix(matrix, task["task_id"]))
        self.assertEqual([], orchestration_lib.validate_contract("findings", findings))
        self.assertEqual([], orchestration_lib.validate_contract("worker_result", worker_result))
        for payload, validator in (
            (task, orchestration_lib.validate_task_spec),
            (matrix, lambda value: orchestration_lib.validate_acceptance_matrix(value, task["task_id"])),
            (findings, lambda value: orchestration_lib.validate_contract("findings", value)),
            (worker_result, lambda value: orchestration_lib.validate_contract("worker_result", value)),
        ):
            missing = deepcopy(payload)
            del missing[next(iter(missing))]
            self.assertTrue(validator(missing))
        invalid_matrix = deepcopy(matrix)
        invalid_matrix["items"][0]["severity"] = "urgent"
        invalid_matrix["items"][0]["status"] = "unknown"
        self.assertTrue(orchestration_lib.validate_acceptance_matrix(invalid_matrix, task["task_id"]))
        invalid_findings = deepcopy(findings)
        invalid_findings["findings"][0]["affected_paths"] = ["../unsafe"]
        self.assertTrue(orchestration_lib.validate_contract("findings", invalid_findings))
        invalid_worker = deepcopy(worker_result)
        invalid_worker["changed_files"] = ["/unsafe"]
        self.assertTrue(orchestration_lib.validate_contract("worker_result", invalid_worker))

    def test_assignment_registry_enforces_single_writer_and_fresh_reviews(self) -> None:
        assignments = orchestration_lib.load_json(
            REPO_ROOT / "docs/agent-tasks/ORCH-001/agent_assignments.json"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def validate(name: str, payload: dict[str, object]) -> list[str]:
                path = root / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                return orchestration_lib.validate_assignments(orchestration_lib.load_json(path))

            self.assertEqual([], validate("valid", assignments))
            two_writers = deepcopy(assignments)
            two_writers["assignments"].append(
                {"role": "implementation-owner", "worktree": "review-writer", "session_policy": "persistent", "sandbox_mode": "workspace-write", "status": "active"}
            )
            self.assertTrue(validate("two-writers", two_writers))
            resumed_reviewer = deepcopy(assignments)
            resumed_reviewer["assignments"][1]["session_policy"] = "persistent"
            self.assertTrue(validate("resumed-reviewer", resumed_reviewer))
            writable_verifier = deepcopy(assignments)
            writable_verifier["assignments"][3]["sandbox_mode"] = "workspace-write"
            self.assertTrue(validate("writable-verifier", writable_verifier))
            integration = deepcopy(assignments)
            integration["assignments"].append(
                {"role": "integration-owner", "worktree": "review-writer", "session_policy": "persistent", "sandbox_mode": "workspace-write", "status": "active"}
            )
            self.assertTrue(validate("unapproved-integration", integration))

    def test_dry_run_uses_supported_commands_and_strict_event_parsing(self) -> None:
        result = {
            "task_id": "DRY-RUN",
            "role": "final-verifier",
            "session_id_reference": "captured-by-orchestrator",
            "status": "PASS",
            "changed_files": [],
            "created_artifacts": [],
            "checks": [{"requirement_id": "DRY-RUN-A01", "command": "read README.md", "status": "passed", "evidence": "offline"}],
            "unresolved_findings": [],
            "risk_notes": [],
            "recommended_next_action": "Return control to the Leader."
        }
        events = "\n".join((
            json.dumps({"type": "thread.started", "thread_id": "offline-thread-placeholder"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}}),
        ))
        self.assertEqual("offline-thread-placeholder", run_dry_run.extract_thread_id(events))
        self.assertEqual(result, run_dry_run.extract_worker_result(events))
        self.assertEqual(result, run_dry_run.extract_worker_result(events.replace(json.dumps(result), f"```\n{json.dumps(result)}\n```")))
        self.assertEqual([], orchestration_lib.validate_contract("worker_result", run_dry_run.extract_worker_result(events)))
        exec_command = run_dry_run.build_exec_command("prompt")
        resume_command = run_dry_run.build_resume_command("offline-thread-placeholder", "prompt")
        self.assertIn("--sandbox", exec_command)
        self.assertNotIn("--sandbox", resume_command)
        self.assertIn('sandbox_mode="read-only"', resume_command)
        self.assertLess(resume_command.index("--json"), resume_command.index("offline-thread-placeholder"))
        self.assertEqual("offline-thread-placeholder", run_dry_run.extract_thread_id(events))
        self.assertEqual([], run_dry_run.event_scope_errors(events, run_dry_run.FIXTURE))
        bad_events = json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": f"cat {REPO_ROOT}/README.md"}})
        self.assertTrue(run_dry_run.event_scope_errors(bad_events, run_dry_run.FIXTURE))
        self.assertTrue(run_dry_run.model_unavailable("requested model unavailable"))

    def test_dry_run_preview_does_not_create_fixture_or_call_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture"
            with mock.patch.object(run_dry_run, "FIXTURE", fixture), mock.patch.object(
                run_dry_run.subprocess, "run"
            ) as run:
                self.assertEqual(0, run_dry_run.main([]))
                run.assert_not_called()
                self.assertFalse(fixture.exists())

    def test_dynamic_preview_and_fixture_validation_are_offline(self) -> None:
        fixture = Path(tempfile.gettempdir()) / f"kenqia-agent-orchestration-dry-run-preview-{uuid.uuid4().hex}"
        with mock.patch.object(run_dry_run.subprocess, "run") as run:
            self.assertEqual(0, run_dry_run.main(["--fixture", str(fixture), "--task-id", "DRYRUN-002"]))
            run.assert_not_called()
        self.assertFalse(fixture.exists())
        for candidate in (
            run_dry_run.FIXED_FIXTURE,
            Path("/tmp") / "wrong-prefix",
            Path("/var/tmp/kenqia-agent-orchestration-dry-run-outside"),
            Path("/tmp/kenqia-agent-orchestration-dry-run-parent/../kenqia-agent-orchestration-dry-run-traversal"),
        ):
            with self.assertRaises(ValueError):
                run_dry_run.validate_live_fixture(candidate)
        fixture.mkdir()
        try:
            with self.assertRaises(ValueError):
                run_dry_run.validate_live_fixture(fixture)
        finally:
            fixture.rmdir()

    def test_mocked_health_and_full_modes_validate_fresh_task_fixture(self) -> None:
        fixture = Path(tempfile.gettempdir()) / f"kenqia-agent-orchestration-dry-run-health-{uuid.uuid4().hex}"
        task_id = "DRYRUN-002"
        result = {
            "task_id": task_id,
            "role": "final-verifier",
            "session_id_reference": "captured-by-orchestrator",
            "status": "PASS",
            "changed_files": [],
            "created_artifacts": [],
            "checks": [{"requirement_id": f"{task_id}-A01", "command": "read README.md", "status": "passed", "evidence": "mocked"}],
            "unresolved_findings": [],
            "risk_notes": [],
            "recommended_next_action": "Return control to the Leader.",
        }
        events = "\n".join((
            json.dumps({"type": "thread.started", "thread_id": "mocked-dry-run-thread"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}}),
        ))
        completed = type("Completed", (), {"returncode": 0, "stdout": events, "stderr": ""})()
        try:
            with mock.patch.object(run_dry_run.subprocess, "run", side_effect=[completed]):
                self.assertEqual(0, run_dry_run.main(["--health-check", "--fixture", str(fixture), "--task-id", task_id]))
            health_report = json.loads((fixture / ".runtime" / "sanitized-report.json").read_text(encoding="utf-8"))
            self.assertEqual("health-check", health_report["mode"])
            self.assertEqual(task_id, health_report["task_id"])
            self.assertTrue(health_report["exec_succeeded"])
            self.assertFalse(health_report["resume_attempted"])
            self.assertNotIn("mocked-dry-run-thread", json.dumps(health_report))
            self.assertNotIn("actual_model", health_report)
            self.assertNotIn("provider", health_report)
        finally:
            shutil.rmtree(fixture, ignore_errors=True)

        fixture = Path(tempfile.gettempdir()) / f"kenqia-agent-orchestration-dry-run-full-{uuid.uuid4().hex}"
        try:
            with mock.patch.object(run_dry_run.subprocess, "run", side_effect=[completed, completed]) as run:
                self.assertEqual(0, run_dry_run.main(["--execute", "--fixture", str(fixture), "--task-id", task_id]))
                self.assertEqual(2, run.call_count)
                self.assertEqual(["codex", "exec"], run.call_args_list[0].args[0][:2])
                self.assertIn("--output-schema", run.call_args_list[0].args[0])
                self.assertIn("--model", run.call_args_list[0].args[0])
                self.assertIn("gpt-5.6-terra", run.call_args_list[0].args[0])
                self.assertEqual(["codex", "exec", "resume"], run.call_args_list[1].args[0][:3])
            full_report = json.loads((fixture / ".runtime" / "sanitized-report.json").read_text(encoding="utf-8"))
            self.assertEqual("full", full_report["mode"])
            self.assertTrue(full_report["resume_succeeded"])
            self.assertTrue(full_report["same_thread"])
        finally:
            shutil.rmtree(fixture, ignore_errors=True)

    def test_mocked_health_transient_failure_is_partial_without_resume(self) -> None:
        fixture = Path(tempfile.gettempdir()) / f"kenqia-agent-orchestration-dry-run-transient-{uuid.uuid4().hex}"
        events = json.dumps({"type": "error", "error": {"message": "upstream provider returned 503"}})
        completed = type("Completed", (), {"returncode": 1, "stdout": events, "stderr": "provider unavailable"})()
        try:
            with mock.patch.object(run_dry_run.subprocess, "run", side_effect=[completed]) as run:
                self.assertEqual(0, run_dry_run.main(["--health-check", "--fixture", str(fixture), "--task-id", "DRYRUN-002"]))
                self.assertEqual(1, run.call_count)
            report = json.loads((fixture / ".runtime" / "sanitized-report.json").read_text(encoding="utf-8"))
            self.assertEqual("PARTIAL", report["final_status"])
            self.assertFalse(report["resume_attempted"])
        finally:
            shutil.rmtree(fixture, ignore_errors=True)

    def test_dry_run_fixture_and_sanitized_report_keep_thread_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture"
            with mock.patch.object(run_dry_run, "FIXTURE", fixture):
                run_dry_run.write_fixture()
                self.assertEqual(
                    {"AGENTS.md", "ACCEPTANCE_MATRIX.json", "README.md", "TASK_SPEC.json", "WORKER_RESULT.schema.json"},
                    {path.name for path in fixture.iterdir() if path.name != ".runtime"},
                )
                args = type("Args", (), {"static_result": "not-run"})()
                run_dry_run.report(
                    "PASS", args, first_events=json.dumps({"type": "thread.started", "thread_id": "offline-thread-placeholder"}),
                    first_contract="PASS", thread_captured=True,
                )
                report = json.loads((fixture / ".runtime" / "sanitized-report.json").read_text(encoding="utf-8"))
                self.assertNotIn("offline-thread-placeholder", json.dumps(report))
                self.assertFalse(report["fallback_model"])
                self.assertFalse(report["agent_write"])
        self.assertTrue(os.access(SCRIPTS_DIR / "run_dry_run.sh", os.X_OK))

    def test_dry_run_classifies_upstream_failure_without_model_retry(self) -> None:
        stderr = "upstream 502 unknown model metadata fallback; skills context budget truncation"
        classification = run_dry_run.classify_first_turn("", stderr, first_returncode=1)
        self.assertEqual("PARTIAL", classification["status"])
        self.assertEqual("MODEL_UNAVAILABLE", classification["model_status"])
        self.assertFalse(classification["fallback_model"])
        self.assertTrue(classification["fallback_metadata"])
        self.assertEqual(
            {"unknown-model-metadata", "metadata-fallback", "skills-context-budget-truncation", "upstream-5xx"},
            set(classification["warning_flags"]),
        )

    def test_dry_run_classifies_event_only_upstream_502_as_partial(self) -> None:
        events = json.dumps({"type": "error", "error": {"message": "upstream provider returned 502"}})
        classification = run_dry_run.classify_first_turn(events, "generic execution failure", first_returncode=1)
        self.assertEqual("PARTIAL", classification["status"])
        self.assertEqual("MODEL_UNAVAILABLE", classification["model_status"])
        self.assertEqual("FAIL", run_dry_run.classify_first_turn("", "unknown argument --bad", first_returncode=2)["status"])

    def test_dry_run_classifies_only_explicit_unknown_model_as_unavailable(self) -> None:
        classification = run_dry_run.classify_first_turn("", "requested unknown model", first_returncode=1)
        self.assertEqual("PARTIAL", classification["status"])
        self.assertEqual("MODEL_UNAVAILABLE", classification["model_status"])
        for stderr in ("generic model warning", "unknown argument --model", "output schema validation failed"):
            self.assertEqual("FAIL", run_dry_run.classify_first_turn("", stderr, first_returncode=1)["status"])

    def test_classify_existing_is_offline_and_never_calls_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture"
            runtime = fixture / ".runtime"
            runtime.mkdir(parents=True)
            (runtime / "first.events.jsonl").write_text(
                "\n".join((
                    json.dumps({"type": "thread.started", "thread_id": "offline-thread-placeholder"}),
                    json.dumps({"type": "error", "error": {"message": "upstream provider returned 502"}}),
                )) + "\n",
                encoding="utf-8",
            )
            (runtime / "first.stderr.log").write_text("generic execution failure", encoding="utf-8")
            with mock.patch.object(run_dry_run, "FIXTURE", fixture), mock.patch.object(
                run_dry_run, "FIXED_FIXTURE", fixture
            ), mock.patch.object(run_dry_run.subprocess, "run") as run:
                self.assertEqual(0, run_dry_run.main(["--classify-existing", "--static-result", "PASS"]))
                run.assert_not_called()
            report = json.loads((runtime / "sanitized-report.json").read_text(encoding="utf-8"))
            self.assertEqual("PARTIAL", report["final_status"])
            self.assertNotIn("offline-thread-placeholder", json.dumps(report))

    def test_review_contracts_and_context_require_complete_evidence(self) -> None:
        empty = {"task_id": "ORCH-001", "reviewer_role": "artifact-reviewer", "findings": []}
        self.assertEqual([], orchestration_lib.validate_contract("findings", empty))
        self.assertEqual([], orchestration_lib.validate_contract("findings", orchestration_lib.merge_findings([empty])))
        task = orchestration_lib.load_json(REPO_ROOT / "docs/agent-tasks/ORCH-001/task_spec.json")
        matrix = orchestration_lib.load_json(REPO_ROOT / "docs/agent-tasks/ORCH-001/acceptance_matrix.json")
        result = orchestration_lib.load_json(REPO_ROOT / "docs/agent-contracts/examples/worker_result.example.json")
        result.update({"task_id": task["task_id"], "role": "final-verifier", "status": "PASS", "checks": [{"requirement_id": item["id"], "command": "offline", "status": "passed", "evidence": "covered"} for item in matrix["items"]], "unresolved_findings": []})
        self.assertEqual([], orchestration_lib.validate_worker_result_context(result, task, matrix))
        result["checks"] = []
        self.assertTrue(orchestration_lib.validate_worker_result_context(result, task, matrix))

    def test_launch_commands_and_summaries_do_not_expose_private_markers(self) -> None:
        task_dir = REPO_ROOT / "docs/agent-tasks/ORCH-001"
        initial = orchestration_lib.build_owner_command(task_dir, execute=True, workspace_write=True, allow_workspace_write=True)
        with self.assertRaises(ValueError):
            orchestration_lib.build_resume_command(task_dir, "opaque-session-marker", execute=True)
        resumed = orchestration_lib.build_resume_command(task_dir, "opaque-session-marker", execute=True, allow_workspace_write=True)
        self.assertIn("--json", initial.command)
        self.assertIn("--output-schema", initial.command)
        self.assertNotIn("--sandbox", resumed.command)
        self.assertIn('sandbox_mode="workspace-write"', resumed.command)
        preview = orchestration_lib.build_owner_command(task_dir, execute=False, workspace_write=False)
        with mock.patch.object(orchestration_lib.subprocess, "run") as run, mock.patch("sys.stdout") as stdout:
            self.assertEqual(0, orchestration_lib.run_plan(preview, Path(tempfile.mkdtemp())))
            rendered = "".join(str(call) for call in stdout.write.call_args_list)
            self.assertNotIn(initial.prompt, rendered)
            self.assertNotIn("opaque-session-marker", rendered)
            run.assert_not_called()

    def test_assignment_modes_and_scope_classification_are_strict(self) -> None:
        assignments = orchestration_lib.load_json(REPO_ROOT / "docs/agent-tasks/ORCH-001/agent_assignments.json")
        two_owners = deepcopy(assignments)
        two_owners["assignments"].append({"role": "implementation-owner", "worktree": "other", "session_policy": "persistent", "sandbox_mode": "workspace-write", "status": "active"})
        self.assertTrue(orchestration_lib.validate_assignments(two_owners))
        parallel = deepcopy(two_owners)
        parallel["parallel_worktrees"] = True
        parallel["human_approval"]["status"] = "approved"
        parallel["assignments"].append({"role": "integration-owner", "worktree": "integration", "session_policy": "persistent", "sandbox_mode": "workspace-write", "status": "active"})
        self.assertEqual([], orchestration_lib.validate_assignments(parallel))
        self.assertTrue(run_dry_run.path_within_fixture(Path("/tmp/kenqia-agent-orchestration-dry-run-sibling/file"), run_dry_run.FIXTURE) is False)
        self.assertEqual("FAIL", run_dry_run.classify_first_turn("", "unknown argument --bad", first_returncode=2)["status"])

    def test_preview_commands_do_not_execute_and_write_needs_two_opt_ins(self) -> None:
        task_path = REPO_ROOT / "docs" / "agent-tasks" / "ORCH-001"
        preview = orchestration_lib.build_owner_command(task_path, execute=False, workspace_write=False)
        self.assertIn("codex", preview.command)
        self.assertIn("exec", preview.command)
        self.assertEqual("read-only", preview.sandbox)
        self.assertFalse(preview.execute)
        overridden = orchestration_lib.build_owner_command(
            task_path,
            execute=False,
            workspace_write=False,
            model="gpt-5.6-terra",
            reasoning_effort="high",
        )
        self.assertIn("model_reasoning_effort=high", overridden.command)
        self.assertNotIn("fallback", " ".join(overridden.command).lower())
        with self.assertRaises(ValueError):
            orchestration_lib.build_owner_command(task_path, execute=True, workspace_write=True)
        execute_write = orchestration_lib.build_owner_command(
            task_path,
            execute=True,
            workspace_write=True,
            allow_workspace_write=True,
        )
        self.assertEqual("workspace-write", execute_write.sandbox)
        self.assertTrue(execute_write.execute)
        self.assertNotIn("shell", " ".join(execute_write.command).lower())

    def test_resume_and_reviewer_commands_preserve_session_rules(self) -> None:
        task_path = REPO_ROOT / "docs" / "agent-tasks" / "ORCH-001"
        resume = orchestration_lib.build_resume_command(task_path, "recorded-session", execute=False)
        self.assertEqual(["codex", "exec", "resume"], resume.command[:3])
        reviewer = orchestration_lib.build_reviewer_command(
            task_path, "scientific-reviewer", execute=False
        )
        self.assertEqual("read-only", reviewer.sandbox)
        self.assertIn("fresh", reviewer.prompt.lower())

    def test_role_output_contract_routing_rejects_wrong_result_kind(self) -> None:
        task_path = REPO_ROOT / "docs" / "agent-tasks" / "ORCH-001"
        findings = orchestration_lib.load_json(REPO_ROOT / "docs" / "agent-contracts/examples/findings.example.json")
        worker_result = orchestration_lib.load_json(REPO_ROOT / "docs" / "agent-contracts/examples/worker_result.example.json")
        for role in ("scientific-reviewer", "artifact-reviewer", "explorer"):
            plan = orchestration_lib.build_reviewer_command(task_path, role, execute=False)
            self.assertEqual("findings", plan.result_kind)
            self.assertIn("findings.schema.json", " ".join(plan.command))
            matching = deepcopy(findings)
            matching["reviewer_role"] = role
            self.assertEqual([], orchestration_lib.validate_role_result(role, matching))
            self.assertTrue(orchestration_lib.validate_role_result(role, worker_result))
        verifier = orchestration_lib.build_reviewer_command(task_path, "final-verifier", execute=False)
        self.assertEqual("worker_result", verifier.result_kind)
        self.assertIn("worker_result.schema.json", " ".join(verifier.command))
        verifier_result = deepcopy(worker_result)
        verifier_result["role"] = "final-verifier"
        self.assertEqual([], orchestration_lib.validate_role_result("final-verifier", verifier_result))
        self.assertTrue(orchestration_lib.validate_role_result("final-verifier", findings))

    def test_merge_sanitize_and_offline_runtime_rules(self) -> None:
        left = {
            "task_id": "ORCH-001",
            "role": "scientific-reviewer",
            "artifact_paths": ["docs/agent-orchestration/README.md"],
            "findings": [{"id": "F-1", "severity": "major", "summary": "Missing check"}],
        }
        right = {
            "task_id": "ORCH-001",
            "role": "artifact-reviewer",
            "artifact_paths": ["docs/agent-orchestration/README.md"],
            "findings": [{"id": "F-2", "severity": "major", "summary": "Missing check"}],
        }
        merged = orchestration_lib.merge_findings([left, right])
        self.assertEqual(1, len(merged["findings"]))
        report = orchestration_lib.sanitize_summary(
            {"status": "PASS", "session_id": "secret", "raw_log": "private", "checks": ["ok"]}
        )
        self.assertNotIn("secret", json.dumps(report))
        self.assertNotIn("raw_log", report)
        ignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/.agent-orchestration-runs/", ignore_text)

    def test_cli_preview_and_contract_validation_are_offline(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "owner_launch.py"), "docs/agent-tasks/ORCH-001"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("PREVIEW", result.stdout)
        self.assertNotIn("executing", result.stdout.lower())
        validation = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "validate_task_package.py"), "docs/agent-tasks/ORCH-001"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, validation.returncode, validation.stderr)
        assignments = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "verify_single_writer.py"), "docs/agent-tasks/ORCH-001/agent_assignments.json"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, assignments.returncode, assignments.stderr)
        self.assertIn("VALID assignments", assignments.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
