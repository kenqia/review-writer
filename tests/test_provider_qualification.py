#!/usr/bin/env python3
"""Offline regression tests for no-Schema provider qualification."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "provider-qualification"))
import qualification  # noqa: E402


CATALOG = json.dumps({"models": [{
    "slug": "gpt-5.6-terra", "context_window": 372000, "max_context_window": 372000,
    "default_reasoning_level": "medium", "apply_patch_tool_type": "freeform",
    "shell_type": "shell_command", "supports_parallel_tool_calls": True,
    "supports_reasoning_summaries": True, "input_modalities": ["text", "image"],
}]})


def completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return type("Completed", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


def turn_events(thread: str, *, thread_started: bool = True, started: bool = True, completed_turn: bool = True, failed: bool = False) -> str:
    events = []
    if thread_started: events.append(json.dumps({"type": "thread.started", "thread_id": thread}))
    if started: events.append(json.dumps({"type": "turn.started", "turn_id": f"{thread}-turn"}))
    if completed_turn: events.append(json.dumps({"type": "turn.completed", "turn_id": f"{thread}-turn"}))
    if failed: events.append(json.dumps({"type": "turn.failed", "turn_id": f"{thread}-turn", "error": {"code": "failed"}}))
    return "\n".join(events)


def last_message_path(command: list[str]) -> Path:
    return Path(command[command.index("--output-last-message") + 1])


class ProviderQualificationTests(unittest.TestCase):
    def test_live_commands_pin_route_and_never_use_schema(self) -> None:
        initial = qualification.build_initial_command("workspace-write", "prompt", Path("/tmp/last.txt"))
        resumed = qualification.build_resume_command("owner-thread", "workspace-write", "prompt", Path("/tmp/last.txt"))
        for command in (initial, resumed):
            self.assertIn("gpt-5.6-terra", command)
            self.assertIn('model_provider="custom"', command)
            self.assertIn("model_reasoning_effort=medium", command)
            self.assertIn("--output-last-message", command)
            self.assertNotIn("--output-schema", command)
        self.assertLess(resumed.index("--json"), resumed.index("owner-thread"))

    def test_preflight_uses_exact_cli_commands_and_structured_catalog(self) -> None:
        with mock.patch.object(qualification.subprocess, "run", side_effect=[completed(stdout="codex-cli 0.144.5\n"), completed(stdout=CATALOG)]) as run:
            result = qualification._preflight()
        self.assertTrue(result["qualified"])
        self.assertEqual(["codex", "--version"], run.call_args_list[0].args[0])
        self.assertEqual(["codex", "debug", "models", "--bundled"], run.call_args_list[1].args[0])

    def test_preflight_fails_closed_for_bad_returncode_or_missing_catalog_fact(self) -> None:
        self.assertFalse(qualification.preflight_result("codex-cli 0.144.5", CATALOG, version_returncode=1, catalog_returncode=0)["qualified"])
        broken = json.loads(CATALOG)
        broken["models"][0]["input_modalities"] = ["text"]
        self.assertFalse(qualification.preflight_result("codex-cli 0.144.5", json.dumps(broken), version_returncode=0, catalog_returncode=0)["qualified"])
        self.assertFalse(qualification.preflight_result("codex-cli 0.144.5", "not json", version_returncode=0, catalog_returncode=0)["qualified"])
        for invalid in ("codex-cli 0.144.5-dev", "codex-cli 0.144.5-alpha", "codex-cli 0.144.50", "codex-cli 0.144.4", "prefix codex-cli 0.144.5"):
            self.assertFalse(qualification.preflight_result(invalid, CATALOG)["qualified"], invalid)

    def test_fixture_requires_new_lexical_direct_child_of_tmp(self) -> None:
        direct = Path("/tmp/provider-qualification-direct-child")
        self.assertEqual(direct, qualification.validate_fixture(direct))
        for candidate in (Path("/tmp/provider-qualification-parent/nested"), Path("/tmp/a/../provider-qualification-traversal"), Path("/var/tmp/provider-qualification")):
            with self.assertRaises(ValueError):
                qualification.validate_fixture(candidate)
        with tempfile.TemporaryDirectory(dir="/tmp") as existing:
            with self.assertRaises(ValueError):
                qualification.validate_fixture(Path(existing))

    def test_lifecycle_structurally_separates_completed_turn_from_auxiliary_error(self) -> None:
        events = "\n".join((
            json.dumps({"type": "thread.started", "thread_id": "owner-thread"}),
            json.dumps({"type": "turn.started", "turn_id": "owner-turn"}),
            "malformed-json",
            json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
            json.dumps({"type": "turn.completed", "turn_id": "owner-turn"}),
            json.dumps({"type": "error", "error": {"code": "auxiliary_401"}}),
        ))
        facts = qualification.parse_lifecycle(events, "auxiliary auth 401")
        self.assertTrue(facts["turn_completed"])
        self.assertFalse(facts["main_failed"])
        self.assertEqual(1, facts["tool_events"])
        self.assertIn("auxiliary-401", facts["warnings"])
        failed = qualification.parse_lifecycle(json.dumps({"type": "turn.failed", "turn_id": "t", "error": {"code": "request_failed"}}), "")
        self.assertTrue(failed["main_failed"])
        self.assertEqual("request_failed", failed["failure_code"])

    def test_recursive_sanitization_removes_nested_private_values(self) -> None:
        secret = "private-thread-sentinel"
        aliases = ("replies", "response", "responses", "thread_reference", "thread_ref", "session_reference", "session_ref", "turn_reference", "turn_ref")
        payload = {"nested": [{"thread_id": secret, "safe": "ok"}, {"prompt": "private-prompt"}], "events": [secret], "aliases": [{alias: secret for alias in aliases}], "safe": {"items": ["ok"]}}
        sanitized = qualification.sanitize_report(payload)
        rendered = json.dumps(sanitized)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("private-prompt", rendered)
        self.assertEqual("ok", sanitized["nested"][0]["safe"])

    def test_q6_three_turn_mocked_evidence_requires_exact_owner_and_reviewer_safety(self) -> None:
        fixture = Path(tempfile.gettempdir()) / f"provider-qualification-q6-regression-{uuid.uuid4().hex}"
        owner_events, resume_events, reviewer_events = turn_events("owner-thread"), turn_events("owner-thread"), turn_events("reviewer-thread")
        def fake_run(command, **kwargs):
            if command[:3] == ["codex", "debug", "models"]:
                return completed(stdout=CATALOG)
            if command[:2] == ["codex", "--version"]:
                return completed(stdout="codex-cli 0.144.5")
            cwd = Path(kwargs["cwd"])
            last_message_path(command).write_text("natural-language report\n", encoding="utf-8")
            if "resume" in command:
                (cwd / qualification.QUALIFICATION_FILE).write_text(qualification.PHASE2_CONTENT, encoding="utf-8")
                return completed(stdout=resume_events)
            if not (cwd / qualification.QUALIFICATION_FILE).exists():
                (cwd / qualification.QUALIFICATION_FILE).write_text(qualification.PHASE1_CONTENT, encoding="utf-8")
                return completed(stdout=owner_events)
            return completed(stdout=reviewer_events)
        with mock.patch.object(qualification.subprocess, "run", side_effect=fake_run):
            self.assertEqual(0, qualification.main(["--execute", "--fixture", str(fixture), "--task-id", "Q6-CLOSURE"]))
        report = json.loads((fixture / ".runtime" / "qualification-report.json").read_text(encoding="utf-8"))
        self.assertEqual(3, report["turn_count"])
        self.assertTrue(report["evidence"]["owner_phase1"])
        self.assertTrue(report["evidence"]["owner_phase2"])
        self.assertTrue(report["evidence"]["reviewer_read_only"])
        self.assertTrue(report["evidence"]["owner_initial_last_message"])
        self.assertTrue(report["evidence"]["owner_resume_last_message"])
        self.assertTrue(report["evidence"]["reviewer_last_message"])
        self.assertNotIn("owner-thread", json.dumps(report))

    def test_q6_rejects_missing_write_wrong_resume_and_reviewer_write_or_collision(self) -> None:
        owner_events = turn_events("owner-thread")
        def execute_case(mode: str) -> int:
            fixture = Path(tempfile.gettempdir()) / f"provider-qualification-q6-negative-{mode}-{uuid.uuid4().hex}"
            def fake_run(command, **kwargs):
                if command[:2] == ["codex", "--version"]: return completed(stdout="codex-cli 0.144.5")
                if command[:3] == ["codex", "debug", "models"]: return completed(stdout=CATALOG)
                cwd = Path(kwargs["cwd"])
                last_message_path(command).write_text("natural-language report\n", encoding="utf-8")
                if "resume" in command:
                    if mode != "wrong-resume": (cwd / qualification.QUALIFICATION_FILE).write_text(qualification.PHASE2_CONTENT, encoding="utf-8")
                    thread = "other-thread" if mode == "wrong-resume" else "owner-thread"
                    return completed(stdout=turn_events(thread))
                if not (cwd / qualification.QUALIFICATION_FILE).exists():
                    if mode == "malformed-write": (cwd / qualification.QUALIFICATION_FILE).write_text("wrong\n", encoding="utf-8")
                    elif mode != "missing-write": (cwd / qualification.QUALIFICATION_FILE).write_text(qualification.PHASE1_CONTENT, encoding="utf-8")
                    return completed(returncode=1 if mode == "failed-turn" else 0, stdout=owner_events)
                if mode == "reviewer-write": (cwd / "unexpected.txt").write_text("write", encoding="utf-8")
                thread = "owner-thread" if mode == "reviewer-collision" else "reviewer-thread"
                return completed(stdout=turn_events(thread))
            with mock.patch.object(qualification.subprocess, "run", side_effect=fake_run):
                return qualification.main(["--execute", "--fixture", str(fixture), "--task-id", "Q6-CLOSURE"])
        for mode in ("missing-write", "malformed-write", "failed-turn", "wrong-resume", "reviewer-write", "reviewer-collision"):
            self.assertEqual(1, execute_case(mode), mode)

    def test_q6_rejects_missing_or_empty_last_messages_and_incomplete_lifecycle(self) -> None:
        def execute_case(mode: str) -> int:
            fixture = Path(tempfile.gettempdir()) / f"provider-qualification-q6-last-{mode}-{uuid.uuid4().hex}"
            def fake_run(command, **kwargs):
                if command[:2] == ["codex", "--version"]: return completed(stdout="codex-cli 0.144.5")
                if command[:3] == ["codex", "debug", "models"]: return completed(stdout=CATALOG)
                cwd = Path(kwargs["cwd"])
                phase = "resume" if "resume" in command else ("reviewer" if (cwd / qualification.QUALIFICATION_FILE).exists() else "owner")
                if phase == "owner": (cwd / qualification.QUALIFICATION_FILE).write_text(qualification.PHASE1_CONTENT, encoding="utf-8")
                elif phase == "resume": (cwd / qualification.QUALIFICATION_FILE).write_text(qualification.PHASE2_CONTENT, encoding="utf-8")
                if mode not in {f"missing-{phase}", f"empty-{phase}"}:
                    last_message_path(command).write_text("" if mode == f"empty-{phase}" else "natural report\n", encoding="utf-8")
                elif mode == f"empty-{phase}": last_message_path(command).write_text("   \n", encoding="utf-8")
                kwargs_for_events = {"thread_started": mode != f"no-thread-{phase}", "started": mode != f"no-start-{phase}", "completed_turn": mode != f"no-complete-{phase}", "failed": mode == f"failed-{phase}"}
                thread = "reviewer-thread" if phase == "reviewer" else "owner-thread"
                return completed(stdout=turn_events(thread, **kwargs_for_events))
            with mock.patch.object(qualification.subprocess, "run", side_effect=fake_run):
                return qualification.main(["--execute", "--fixture", str(fixture), "--task-id", "Q6-CLOSURE"])
        for role in ("owner", "resume", "reviewer"):
            for condition in ("missing", "empty", "no-thread", "no-start", "no-complete", "failed"):
                self.assertEqual(1, execute_case(f"{condition}-{role}"), f"{condition}-{role}")


if __name__ == "__main__":
    unittest.main()
