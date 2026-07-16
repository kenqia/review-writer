#!/usr/bin/env python3
"""Explicit isolated Codex dry-run with preview, health-check, and full modes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from orchestration_lib import REPO_ROOT, validate_contract


FIXED_FIXTURE = Path("/tmp/kenqia-agent-orchestration-dry-run")
FIXTURE = FIXED_FIXTURE
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "medium"
SANDBOX = "read-only"
TASK_ID_PATTERN = re.compile(r"[A-Z][A-Z0-9]*-\d{3}")


def runtime_path(name: str) -> Path:
    return FIXTURE / ".runtime" / name


def cleanup_command(fixture: Path) -> str:
    return f"rm -rf {fixture}"


def configure_fixture(fixture: Path) -> None:
    global FIXTURE
    FIXTURE = fixture


def validate_live_fixture(value: Path) -> Path:
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError("fixture must be an absolute non-traversing path")
    resolved = value.resolve(strict=False)
    tmp_root = Path("/tmp").resolve()
    fixed = FIXED_FIXTURE.resolve(strict=False)
    if resolved == fixed:
        raise ValueError("new live modes cannot use the legacy fixed fixture")
    if tmp_root not in resolved.parents:
        raise ValueError("fixture must remain under /tmp")
    if not resolved.name.startswith("kenqia-agent-orchestration-dry-run-"):
        raise ValueError("fixture basename must use the kenqia-agent-orchestration-dry-run- prefix")
    if resolved.exists():
        raise ValueError("fixture must not exist before a live mode begins")
    return resolved


def validate_live_task_id(value: str) -> str:
    if not TASK_ID_PATTERN.fullmatch(value):
        raise ValueError("task_id must use an uppercase DRYRUN-002-style identifier")
    return value


def inventory(root: Path) -> dict[str, str]:
    runtime = root / ".runtime"
    entries: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or runtime in path.parents:
            continue
        entries[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def write_fixture(task_id: str = "DRY-RUN") -> None:
    FIXTURE.mkdir(parents=True, exist_ok=False)
    runtime_path("").mkdir()
    (FIXTURE / "AGENTS.md").write_text("# Dry-run fixture\nRead only this fixture.\n", encoding="utf-8")
    (FIXTURE / "README.md").write_text("# Fictional read-only fixture\n", encoding="utf-8")
    task_spec = {
        "task_id": task_id, "objective": "Return one valid WORKER_RESULT.", "background": "Fictional fixture.",
        "frozen_decisions": ["Read-only."], "allowed_paths": ["README.md"], "forbidden_paths": ["outside-fixture"],
        "inputs": ["README.md"], "required_outputs": ["WORKER_RESULT"], "acceptance_criteria": ["No writes."],
        "verification_commands": ["read README.md"], "safety_boundaries": ["No nested codex exec."],
        "network_policy": "No network assumptions.", "model_policy": "gpt-5.6-terra medium with no fallback.",
        "stop_conditions": ["Any write request."], "human_checkpoint": "Return control to the Leader.",
    }
    matrix = {"task_id": task_id, "items": [{
        "id": f"{task_id}-A01", "requirement": "Return a valid result.", "evidence_required": "Agent message JSON.",
        "verification_command": "read README.md", "expected_result": "valid JSON", "owner": "Final Verifier",
        "severity": "blocker", "status": "pending",
    }]}
    (FIXTURE / "TASK_SPEC.json").write_text(json.dumps(task_spec, indent=2) + "\n", encoding="utf-8")
    (FIXTURE / "ACCEPTANCE_MATRIX.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(REPO_ROOT / "docs" / "agent-contracts" / "schemas" / "worker_result.schema.json", FIXTURE / "WORKER_RESULT.schema.json")


def prompt_for(phase: str, task_id: str = "DRY-RUN") -> str:
    return (
        f"This is the {phase} read-only confirmation for {task_id}. Read only AGENTS.md, README.md, TASK_SPEC.json, "
        "ACCEPTANCE_MATRIX.json, and WORKER_RESULT.schema.json in this fixture. Do not write files, do not "
        "invoke nested codex exec, and do not access paths outside the fixture. Return exactly one valid JSON "
        f"WORKER_RESULT with task_id {task_id}, role final-verifier, status PASS, and session_id_reference captured-by-orchestrator."
    )


def build_exec_command(prompt: str) -> list[str]:
    return [
        "codex", "exec", "--skip-git-repo-check", "--json", "--output-schema", str(FIXTURE / "WORKER_RESULT.schema.json"),
        "--output-last-message", str(runtime_path("first.output.txt")), "--model", MODEL, "--sandbox", SANDBOX,
        "-c", f"model_reasoning_effort={REASONING_EFFORT}", prompt,
    ]


def build_resume_command(thread_id: str, prompt: str) -> list[str]:
    return [
        "codex", "exec", "resume", "--skip-git-repo-check", "--json", "--output-schema", str(FIXTURE / "WORKER_RESULT.schema.json"),
        "--output-last-message", str(runtime_path("resume.output.txt")), "--model", MODEL,
        "-c", f'sandbox_mode="{SANDBOX}"', "-c", f"model_reasoning_effort={REASONING_EFFORT}", thread_id, prompt,
    ]


def event_objects(events: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line in events.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def extract_thread_id(events: str) -> str | None:
    for event in event_objects(events):
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            return event["thread_id"]
    return None


def _decode_agent_message(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def extract_worker_result(events: str) -> dict[str, Any] | None:
    result: dict[str, Any] | None = None
    for event in event_objects(events):
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            candidate = _decode_agent_message(item["text"])
            if candidate is not None:
                result = candidate
    return result


def _metadata_values(value: Any, key: str | None = None) -> Iterable[str]:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _metadata_values(child_value, child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _metadata_values(child, key)
    elif key in {"command", "cmd", "cwd", "path", "arguments"} and isinstance(value, str):
        yield value


def event_scope_errors(events: str, fixture: Path) -> list[str]:
    errors: list[str] = []
    for event in event_objects(events):
        item = event.get("item")
        metadata = item if isinstance(item, dict) and item.get("type") in {"command_execution", "command"} else None
        if metadata is None:
            continue
        for value in _metadata_values(metadata):
            if str(REPO_ROOT) in value:
                errors.append("event metadata references review-writer root")
            for path in re.findall(r"(?<![A-Za-z0-9_])(/[A-Za-z0-9._/+:-]+)", value):
                if not path_within_fixture(Path(path), fixture):
                    errors.append("event metadata references a path outside the fixture")
    return errors


def path_within_fixture(path: Path, fixture: Path) -> bool:
    try:
        resolved_path = path.resolve(strict=False)
        resolved_fixture = fixture.resolve(strict=False)
    except OSError:
        return False
    return resolved_path == resolved_fixture or resolved_fixture in resolved_path.parents


def run(command: list[str], output_name: str) -> tuple[int, str, str]:
    completed = subprocess.run(command, cwd=FIXTURE, capture_output=True, text=True, check=False)
    runtime_path(f"{output_name}.events.jsonl").write_text(completed.stdout, encoding="utf-8")
    runtime_path(f"{output_name}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    return completed.returncode, completed.stdout, completed.stderr


def _reported_value(events: str, key: str, default: str) -> str:
    def visit(value: Any) -> str | None:
        if isinstance(value, dict):
            if isinstance(value.get(key), str):
                return value[key]
            for child in value.values():
                found = visit(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found:
                    return found
        return None
    return visit(event_objects(events)) or default


def warning_flags(*streams: str) -> list[str]:
    content = "\n".join(streams).lower()
    flags: list[str] = []
    if "unknown model" in content:
        flags.append("unknown-model-metadata")
    if "fallback" in content and ("metadata" in content or "unknown model" in content):
        flags.append("metadata-fallback")
    if "skills" in content and "context" in content and ("budget" in content or "truncat" in content):
        flags.append("skills-context-budget-truncation")
    if re.search(r"\b5\d\d\b", content) and ("upstream" in content or "provider" in content):
        flags.append("upstream-5xx")
    if "warning" in content:
        flags.append("warning-reported")
    return flags


def sanitized_report(**report: Any) -> None:
    runtime_path("sanitized-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def report(status: str, args: argparse.Namespace, *, mode: str = "legacy", task_id: str = "DRY-RUN", first_events: str = "", resume_events: str = "", first_stderr: str = "", resume_stderr: str = "", first_contract: str = "not-run", resume_contract: str = "not-run", model_status: str = "not-run", thread_captured: bool = False, resume_status: str = "not-run", same_thread: bool = False, agent_write: bool = False, exec_succeeded: bool = False, resume_attempted: bool = False, resume_succeeded: bool = False, limitations: list[str] | None = None) -> None:
    flags = warning_flags(first_events, resume_events, first_stderr, resume_stderr)
    sanitized_report(
        mode=mode, requested_model=MODEL, reasoning_effort=REASONING_EFFORT, sandbox=SANDBOX, task_id=task_id,
        exec_status=model_status, exec_succeeded=exec_succeeded, resume_status=resume_status,
        resume_attempted=resume_attempted, resume_succeeded=resume_succeeded, same_thread=same_thread,
        first_contract=first_contract, first_contract_valid=first_contract == "PASS",
        resume_contract=resume_contract, resume_contract_valid=resume_contract == "PASS",
        thread_captured=thread_captured, session_captured=thread_captured,
        fallback_model=False, fallback_metadata="metadata-fallback" in flags,
        write_count=1 if agent_write else 0, agent_write=agent_write,
        static_result=getattr(args, "static_result", "not-run"), warning_flags=flags,
        warning_count=len(flags), final_status=status,
        limitations=(limitations or []) + ["Provider evidence is not available when Codex CLI does not expose it."],
        fixture_path=str(FIXTURE), cleanup_command=cleanup_command(FIXTURE),
    )


def model_unavailable(stderr: str) -> bool:
    lowered = stderr.lower()
    return bool(re.search(r"\bunknown\s+model\b", lowered)) or ("model" in lowered and any(token in lowered for token in ("unavailable", "not found", "unsupported"))) or bool(re.search(r"\b5\d\d\b", lowered) and ("upstream" in lowered or "provider" in lowered)) or "provider transport" in lowered


def classify_first_turn(events: str, stderr: str, *, first_returncode: int) -> dict[str, Any]:
    flags = warning_flags(events, stderr)
    thread_id = extract_thread_id(events)
    scope_errors = event_scope_errors(events, FIXTURE)
    result = extract_worker_result(events)
    if scope_errors:
        return {"status": "FAIL", "model_status": "SCOPE_VIOLATION", "thread_captured": thread_id is not None, "first_contract": "FAIL", "warning_flags": flags, "fallback_model": False, "fallback_metadata": "metadata-fallback" in flags, "limitations": scope_errors}
    if result is not None and validate_contract("worker_result", result):
        return {"status": "FAIL", "model_status": "MALFORMED_RESULT", "thread_captured": thread_id is not None, "first_contract": "FAIL", "warning_flags": flags, "fallback_model": False, "fallback_metadata": "metadata-fallback" in flags, "limitations": ["A successful turn emitted a malformed WORKER_RESULT."]}
    if result is None and model_unavailable(events + "\n" + stderr):
        return {"status": "PARTIAL", "model_status": "MODEL_UNAVAILABLE", "thread_captured": thread_id is not None, "first_contract": "not-validated", "warning_flags": flags, "fallback_model": False, "fallback_metadata": "metadata-fallback" in flags, "limitations": ["The requested model turn ended before producing a WORKER_RESULT; no retry or fallback model was used."]}
    if result is None and first_returncode != 0:
        return {"status": "FAIL", "model_status": "EXEC_FAILURE", "thread_captured": thread_id is not None, "first_contract": "not-validated", "warning_flags": flags, "fallback_model": False, "fallback_metadata": "metadata-fallback" in flags, "limitations": ["The first turn failed without an explicit model/provider unavailability signal."]}
    if result is None:
        return {"status": "FAIL", "model_status": "NO_RESULT", "thread_captured": thread_id is not None, "first_contract": "not-validated", "warning_flags": flags, "fallback_model": False, "fallback_metadata": "metadata-fallback" in flags, "limitations": ["A successful first turn produced no WORKER_RESULT."]}
    return {"status": "PASS", "model_status": "MODEL_AVAILABLE", "thread_captured": thread_id is not None, "first_contract": "PASS", "warning_flags": flags, "fallback_model": False, "fallback_metadata": "metadata-fallback" in flags, "limitations": []}


def validate_dry_run_result(result: dict[str, Any] | None, task_id: str) -> list[str]:
    if result is None:
        return ["missing WORKER_RESULT"]
    errors = validate_contract("worker_result", result)
    if result.get("task_id") != task_id:
        errors.append("result task_id does not match requested task_id")
    if result.get("role") != "final-verifier":
        errors.append("result role must be final-verifier")
    if result.get("status") != "PASS":
        errors.append("result status must be PASS")
    if result.get("changed_files") != [] or result.get("created_artifacts") != []:
        errors.append("result must report no changed files or created artifacts")
    checks = result.get("checks")
    if not isinstance(checks, list) or not checks or any(not isinstance(check, dict) or check.get("status") != "passed" for check in checks):
        errors.append("result must contain non-empty passed checks")
    elif f"{task_id}-A01" not in {check.get("requirement_id") for check in checks}:
        errors.append("result checks do not cover the requested acceptance requirement")
    if result.get("unresolved_findings") != []:
        errors.append("result must contain no unresolved findings")
    return errors


def classify_existing(args: argparse.Namespace) -> int:
    if FIXTURE != FIXED_FIXTURE:
        print("REFUSED: --classify-existing only permits the fixed fixture path")
        return 2
    events_path = runtime_path("first.events.jsonl")
    stderr_path = runtime_path("first.stderr.log")
    if not events_path.is_file() or not stderr_path.is_file():
        print("REFUSED: fixed fixture does not contain first-turn runtime artifacts")
        return 2
    events = events_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    classification = classify_first_turn(events, stderr, first_returncode=1)
    report(classification["status"], args, first_events=events, first_stderr=stderr, first_contract=classification["first_contract"], model_status=classification["model_status"], thread_captured=classification["thread_captured"], resume_status="not-attempted-no-retry-policy", limitations=classification["limitations"])
    print(f"{classification['status']}: existing first-turn runtime classified without retry or model call")
    return 0


def _write_dynamic_report(status: str, args: argparse.Namespace, *, mode: str, task_id: str, first_events: str = "", resume_events: str = "", first_stderr: str = "", resume_stderr: str = "", first_contract: str = "not-run", resume_contract: str = "not-run", model_status: str = "not-run", thread_captured: bool = False, resume_status: str = "not-run", same_thread: bool = False, agent_write: bool = False, exec_succeeded: bool = False, resume_attempted: bool = False, resume_succeeded: bool = False, limitations: list[str] | None = None) -> None:
    report(status, args, mode=mode, task_id=task_id, first_events=first_events, resume_events=resume_events, first_stderr=first_stderr, resume_stderr=resume_stderr, first_contract=first_contract, resume_contract=resume_contract, model_status=model_status, thread_captured=thread_captured, resume_status=resume_status, same_thread=same_thread, agent_write=agent_write, exec_succeeded=exec_succeeded, resume_attempted=resume_attempted, resume_succeeded=resume_succeeded, limitations=limitations)


def run_dynamic(args: argparse.Namespace, *, mode: str, task_id: str) -> int:
    write_fixture(task_id)
    before = inventory(FIXTURE)
    try:
        first_rc, first_events, first_stderr = run(build_exec_command(prompt_for("initial", task_id)), "first")
    except FileNotFoundError:
        _write_dynamic_report("PARTIAL", args, mode=mode, task_id=task_id, model_status="MODEL_UNAVAILABLE", limitations=["Codex CLI or requested model is unavailable; no fallback was attempted."])
        print("PARTIAL: model command unavailable")
        return 0
    first = classify_first_turn(first_events, first_stderr, first_returncode=first_rc)
    first_result = extract_worker_result(first_events)
    first_errors = validate_dry_run_result(first_result, task_id)
    if first["status"] == "PARTIAL":
        _write_dynamic_report("PARTIAL", args, mode=mode, task_id=task_id, first_events=first_events, first_stderr=first_stderr, first_contract=first["first_contract"], model_status=first["model_status"], thread_captured=first["thread_captured"], limitations=first["limitations"])
        print("PARTIAL: requested model unavailable")
        return 0
    if first["status"] == "FAIL" or first_rc != 0 or not first["thread_captured"] or first_errors:
        limitations = first["limitations"] + first_errors
        _write_dynamic_report("FAIL", args, mode=mode, task_id=task_id, first_events=first_events, first_stderr=first_stderr, first_contract="FAIL" if first_errors else first["first_contract"], model_status=first["model_status"], thread_captured=first["thread_captured"], limitations=limitations)
        print("FAIL: initial contract, scope, or execution validation failed")
        return 1
    if before != inventory(FIXTURE):
        _write_dynamic_report("FAIL", args, mode=mode, task_id=task_id, first_events=first_events, first_stderr=first_stderr, first_contract="PASS", model_status="MODEL_AVAILABLE", thread_captured=True, agent_write=True, limitations=["Fixture SHA-256 content inventory changed outside .runtime."])
        print("FAIL: agent-created fixture writes detected")
        return 1
    if mode == "health-check":
        _write_dynamic_report("PASS", args, mode=mode, task_id=task_id, first_events=first_events, first_stderr=first_stderr, first_contract="PASS", model_status="MODEL_AVAILABLE", thread_captured=True, exec_succeeded=True, resume_status="not-attempted-health-check")
        print("PASS: health-check result validated and fixture content inventory unchanged")
        return 0
    thread_id = extract_thread_id(first_events)
    assert thread_id is not None
    try:
        resume_rc, resume_events, resume_stderr = run(build_resume_command(thread_id, prompt_for("resumed", task_id)), "resume")
    except FileNotFoundError:
        _write_dynamic_report("PARTIAL", args, mode=mode, task_id=task_id, first_events=first_events, first_stderr=first_stderr, first_contract="PASS", model_status="MODEL_AVAILABLE", thread_captured=True, resume_status="unavailable", resume_attempted=True, limitations=["Resume command unavailable; no fallback was attempted."])
        print("PARTIAL: resume command unavailable")
        return 0
    resumed = classify_first_turn(resume_events, resume_stderr, first_returncode=resume_rc)
    resume_result = extract_worker_result(resume_events)
    resume_errors = validate_dry_run_result(resume_result, task_id)
    resume_thread = extract_thread_id(resume_events)
    same_thread = resume_thread == thread_id
    if resumed["status"] == "PARTIAL":
        _write_dynamic_report("PARTIAL", args, mode=mode, task_id=task_id, first_events=first_events, resume_events=resume_events, first_stderr=first_stderr, resume_stderr=resume_stderr, first_contract="PASS", resume_contract=resumed["first_contract"], model_status=resumed["model_status"], thread_captured=True, resume_status="unavailable", same_thread=same_thread, exec_succeeded=True, resume_attempted=True, limitations=resumed["limitations"])
        print("PARTIAL: resume model unavailable")
        return 0
    if resumed["status"] == "FAIL" or resume_rc != 0 or resume_errors or not same_thread:
        limitations = resumed["limitations"] + resume_errors
        if not same_thread:
            limitations.append("Resume event stream did not report the initial thread id.")
        _write_dynamic_report("FAIL", args, mode=mode, task_id=task_id, first_events=first_events, resume_events=resume_events, first_stderr=first_stderr, resume_stderr=resume_stderr, first_contract="PASS", resume_contract="FAIL" if resume_errors else resumed["first_contract"], model_status=resumed["model_status"], thread_captured=True, resume_status="failed", same_thread=same_thread, exec_succeeded=True, resume_attempted=True, limitations=limitations)
        print("FAIL: resume contract, scope, or session validation failed")
        return 1
    if before != inventory(FIXTURE):
        _write_dynamic_report("FAIL", args, mode=mode, task_id=task_id, first_events=first_events, resume_events=resume_events, first_stderr=first_stderr, resume_stderr=resume_stderr, first_contract="PASS", resume_contract="PASS", model_status="MODEL_AVAILABLE", thread_captured=True, resume_status="passed", same_thread=True, agent_write=True, exec_succeeded=True, resume_attempted=True, resume_succeeded=True, limitations=["Fixture SHA-256 content inventory changed outside .runtime."])
        print("FAIL: agent-created fixture writes detected")
        return 1
    _write_dynamic_report("PASS", args, mode=mode, task_id=task_id, first_events=first_events, resume_events=resume_events, first_stderr=first_stderr, resume_stderr=resume_stderr, first_contract="PASS", resume_contract="PASS", model_status="MODEL_AVAILABLE", thread_captured=True, resume_status="passed", same_thread=True, exec_succeeded=True, resume_attempted=True, resume_succeeded=True)
    print("PASS: results validated, same thread confirmed, and fixture content inventory unchanged")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview by default; health-check performs one initial exec; execute performs one exec-resume flow.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--health-check", action="store_true", help="run one initial isolated read-only health check")
    mode.add_argument("--execute", action="store_true", help="run one isolated read-only exec-resume flow")
    mode.add_argument("--classify-existing", action="store_true", help="sanitize the legacy fixed first-turn runtime without invoking Codex")
    parser.add_argument("--fixture", type=Path, help="new /tmp fixture path required for --health-check and --execute")
    parser.add_argument("--task-id", help="uppercase task id required for --health-check and --execute")
    parser.add_argument("--static-result", default="not-run", help="caller-supplied static gate result")
    args = parser.parse_args(argv)
    print("SAFETY: preview is default; live modes use a fresh isolated read-only fixture; no fallback or retry.")
    if args.classify_existing:
        return classify_existing(args)
    if not args.health_check and not args.execute:
        print("PREVIEW: no model call was made. Provide --fixture and --task-id with --health-check or --execute for an isolated run.")
        return 0
    if args.fixture is None or args.task_id is None:
        parser.error("--health-check and --execute require both --fixture and --task-id")
    try:
        fixture = validate_live_fixture(args.fixture)
        task_id = validate_live_task_id(args.task_id)
    except ValueError as error:
        parser.error(str(error))
    configure_fixture(fixture)
    return run_dynamic(args, mode="health-check" if args.health_check else "full", task_id=task_id)


if __name__ == "__main__":
    raise SystemExit(main())
