#!/usr/bin/env python3
"""Preview-first no-Schema provider qualification transport harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

CLI_VERSION = "0.144.5"
MODEL = "gpt-5.6-terra"
REASONING = "medium"
TIMEOUT_SECONDS = 600
TASK_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,79}\Z")
QUALIFICATION_FILE = "owner-phase.txt"
PHASE1_CONTENT = "phase-1: owner created this deterministic marker\n"
PHASE2_CONTENT = "phase-2: owner resumed, read phase-1, and updated this marker\n"
PRIVATE_KEYS = {"thread_id", "turn_id", "session", "session_id", "session_id_reference", "thread_reference", "thread_ref", "session_reference", "session_ref", "turn_reference", "turn_ref", "prompt", "reply", "replies", "response", "responses", "last_message", "stdout", "stderr", "events", "raw_log", "full_output", "output", "auth", "authorization", "token", "cookie"}


def validate_fixture(value: Path) -> Path:
    """Accept only a new lexical direct child of /tmp, never a resolved descendant."""
    if not value.is_absolute() or ".." in value.parts or value.parent != Path("/tmp"):
        raise ValueError("fixture must be a lexical direct child of /tmp")
    if value.exists() or value.is_symlink():
        raise ValueError("fixture must not exist or be a symlink")
    resolved_parent = value.parent.resolve(strict=True)
    if resolved_parent != Path("/tmp").resolve():
        raise ValueError("fixture parent must resolve to /tmp")
    return value


def validate_task_id(value: str) -> str:
    if not TASK_ID.fullmatch(value):
        raise ValueError("task_id must be a safe identifier")
    return value


def _route_options(sandbox: str, last_message: Path) -> list[str]:
    if sandbox not in {"read-only", "workspace-write"}:
        raise ValueError("unsupported sandbox")
    return ["--json", "--output-last-message", str(last_message), "--model", MODEL, "-c", 'model_provider="custom"', "-c", f"model_reasoning_effort={REASONING}", "-c", f'sandbox_mode="{sandbox}"']


def build_initial_command(sandbox: str, prompt: str, last_message: Path) -> list[str]:
    return ["codex", "exec", "--skip-git-repo-check", "--sandbox", sandbox, *_route_options(sandbox, last_message), prompt]


def build_resume_command(session_reference: str, sandbox: str, prompt: str, last_message: Path) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", session_reference):
        raise ValueError("invalid opaque session reference")
    return ["codex", "exec", "resume", "--skip-git-repo-check", *_route_options(sandbox, last_message), session_reference, prompt]


def _event_objects(events: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line in events.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def parse_lifecycle(events: str, stderr: str) -> dict[str, Any]:
    facts: dict[str, Any] = {"thread_started": False, "turn_started": False, "turn_completed": False, "turn_failed": False, "main_failed": False, "failure_code": None, "tool_events": 0, "warnings": []}
    for event in _event_objects(events):
        kind = event.get("type")
        if kind == "thread.started": facts["thread_started"] = True
        elif kind == "turn.started": facts["turn_started"] = True
        elif kind == "turn.completed": facts["turn_completed"] = True
        elif kind == "turn.failed":
            facts["turn_failed"] = facts["main_failed"] = True
            error = event.get("error")
            if isinstance(error, dict): facts["failure_code"] = error.get("code") or error.get("type")
        elif kind in {"item.started", "item.completed"} and isinstance(event.get("item"), dict):
            if event["item"].get("type") in {"command_execution", "tool_call", "function_call"}: facts["tool_events"] += 1
    if re.search(r"\b401\b", stderr, re.I) and re.search(r"auxiliary|feature|auth", stderr, re.I): facts["warnings"].append("auxiliary-401")
    return facts


def thread_reference(events: str) -> str | None:
    for event in _event_objects(events):
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str): return event["thread_id"]
    return None


def transport_outcome(returncode: int, last_message: str, stderr: str) -> str:
    del last_message, stderr
    return "transport-complete" if returncode == 0 else "transport-failed"


def turn_transport_complete(completed: subprocess.CompletedProcess[str]) -> bool:
    facts = parse_lifecycle(completed.stdout, completed.stderr)
    return completed.returncode == 0 and facts["thread_started"] and facts["turn_started"] and facts["turn_completed"] and not facts["turn_failed"] and not facts["main_failed"]


def has_natural_language_message(path: Path) -> bool:
    return path.is_file() and bool(path.read_text(encoding="utf-8", errors="replace").strip())


def sanitize_report(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: sanitize_report(value) for key, value in payload.items() if key.lower() not in PRIVATE_KEYS}
    if isinstance(payload, list): return [sanitize_report(value) for value in payload]
    return payload


def _catalog_models(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list): return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("models", "data", "items"):
            if isinstance(value.get(key), list): return [item for item in value[key] if isinstance(item, dict)]
    return []


def _catalog_json(catalog_text: str) -> Any:
    """The CLI may emit non-catalog diagnostics before its one JSON catalog object."""
    for line in reversed(catalog_text.splitlines()):
        if line.lstrip().startswith("{"):
            return json.loads(line)
    raise json.JSONDecodeError("missing bundled catalog JSON", catalog_text, 0)


def preflight_result(version_text: str, catalog_text: str, *, version_returncode: int = 0, catalog_returncode: int = 0) -> dict[str, Any]:
    exact_version = version_returncode == 0 and bool(re.fullmatch(rf"\s*codex-cli {re.escape(CLI_VERSION)}\s*", version_text))
    try: catalog = _catalog_json(catalog_text)
    except json.JSONDecodeError: catalog = None
    terra = next((item for item in _catalog_models(catalog) if item.get("id") == MODEL or item.get("model") == MODEL or item.get("slug") == MODEL), None)
    if not isinstance(terra, dict):
        facts = False
    else:
        context = terra.get("context_window", terra.get("max_context", terra.get("max_context_tokens")))
        max_context = terra.get("max_context_window", context)
        reasoning = terra.get("default_reasoning_level", terra.get("default_reasoning_effort", terra.get("reasoning_effort")))
        patch = terra.get("apply_patch_tool_type", terra.get("apply_patch", terra.get("patch_mode")))
        shell = terra.get("shell_type", terra.get("shell_command", terra.get("supports_shell_command")))
        parallel = terra.get("supports_parallel_tool_calls", terra.get("parallel_tool_calls", terra.get("parallel_tools")))
        summaries = terra.get("supports_reasoning_summaries", terra.get("reasoning_summaries"))
        modalities = terra.get("input_modalities", terra.get("modalities", []))
        facts = context == 372000 and max_context == 372000 and reasoning == "medium" and patch == "freeform" and shell in {True, "shell_command"} and parallel is True and summaries is True and isinstance(modalities, list) and {"text", "image"}.issubset(set(modalities))
    return {"cli_version": CLI_VERSION if exact_version else "unqualified", "terra_catalog_verified": facts, "qualified": exact_version and catalog_returncode == 0 and facts}


def _preflight() -> dict[str, Any]:
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS)
    catalog = subprocess.run(["codex", "debug", "models", "--bundled"], capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS)
    return preflight_result(version.stdout, catalog.stdout, version_returncode=version.returncode, catalog_returncode=catalog.returncode)


def qualification_plan() -> list[dict[str, str]]:
    return [{"id": f"Q{n}", "name": name, "status": status} for n, name, status in ((0,"route snapshot","recorded"),(1,"plain exec","historical"),(2,"JSON events","historical"),(3,"provider Output Schema capability","unsupported-recorded-only"),(4,"same-session resume","historical"),(5,"sandbox","historical"),(6,"Owner-resume-Reviewer natural-language closure","pending"),(7,"native subagent disabled","disabled-unqualified"))]


def inventory(root: Path) -> dict[str, str]:
    runtime = root / ".runtime"
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file() and runtime not in path.parents}


def _write_report(runtime: Path, report: dict[str, Any]) -> None:
    sanitized = sanitize_report(report)
    (runtime / "qualification-report.json").write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")
    (runtime / "qualification-report.md").write_text("# Provider qualification\n\nTransport and deterministic evidence only; Worker prose is private.\n", encoding="utf-8")


def _run(command: list[str], fixture: Path, runtime: Path, name: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=fixture, capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS)
    (runtime / f"{name}.events.jsonl").write_text(completed.stdout, encoding="utf-8")
    (runtime / f"{name}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    return completed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="explicitly permit the authorized three-turn Q6 closure")
    parser.add_argument("--fixture", type=Path, default=Path("/tmp/provider-qualification-preview"))
    parser.add_argument("--task-id", default="Q6-CLOSURE")
    args = parser.parse_args(argv)
    if not args.execute:
        print("PREVIEW: no model call was made."); return 0
    fixture, task_id = validate_fixture(args.fixture), validate_task_id(args.task_id)
    preflight = _preflight()
    if not preflight["qualified"]:
        print("REFUSED: Codex CLI or bundled Terra catalog is not qualified."); return 2
    runtime = fixture / ".runtime"; runtime.mkdir(parents=True)
    phase1_prompt = f"Qualification {task_id}: as the sole Owner, create {QUALIFICATION_FILE} with exactly: {PHASE1_CONTENT!r}. Return concise natural-language status. Do not dispatch agents."
    owner_last = runtime / "owner-initial-last-message.txt"
    owner = _run(build_initial_command("workspace-write", phase1_prompt, owner_last), fixture, runtime, "owner-initial")
    owner_ref, after_initial = thread_reference(owner.stdout), inventory(fixture)
    phase1_ok = turn_transport_complete(owner) and (fixture / QUALIFICATION_FILE).read_text(encoding="utf-8") == PHASE1_CONTENT if (fixture / QUALIFICATION_FILE).is_file() else False
    evidence = {"owner_phase1": phase1_ok, "owner_phase2": False, "same_owner_thread": False, "reviewer_fresh_thread": False, "reviewer_read_only": False, "owner_initial_last_message": has_natural_language_message(owner_last), "owner_resume_last_message": False, "reviewer_last_message": False}
    turns = [owner]
    if phase1_ok and owner_ref:
        phase2_prompt = f"Qualification {task_id}: resume the same Owner. Read {QUALIFICATION_FILE}, then replace it with exactly: {PHASE2_CONTENT!r}. Return concise natural-language status."
        resume_last = runtime / "owner-resume-last-message.txt"
        resumed = _run(build_resume_command(owner_ref, "workspace-write", phase2_prompt, resume_last), fixture, runtime, "owner-resume")
        turns.append(resumed); resume_ref = thread_reference(resumed.stdout)
        evidence["same_owner_thread"] = resume_ref == owner_ref
        evidence["owner_resume_last_message"] = has_natural_language_message(resume_last)
        evidence["owner_phase2"] = turn_transport_complete(resumed) and evidence["same_owner_thread"] and (fixture / QUALIFICATION_FILE).is_file() and (fixture / QUALIFICATION_FILE).read_text(encoding="utf-8") == PHASE2_CONTENT
        if evidence["owner_phase2"]:
            before_reviewer = inventory(fixture)
            reviewer_prompt = f"Qualification {task_id}: fresh read-only Reviewer; inspect {QUALIFICATION_FILE} and return a concise natural-language report. Do not write or dispatch agents."
            reviewer_last = runtime / "reviewer-read-only-last-message.txt"
            reviewer = _run(build_initial_command("read-only", reviewer_prompt, reviewer_last), fixture, runtime, "reviewer-read-only")
            turns.append(reviewer); reviewer_ref = thread_reference(reviewer.stdout)
            evidence["reviewer_fresh_thread"] = reviewer_ref is not None and reviewer_ref != owner_ref
            evidence["reviewer_last_message"] = has_natural_language_message(reviewer_last)
            evidence["reviewer_read_only"] = turn_transport_complete(reviewer) and evidence["reviewer_fresh_thread"] and inventory(fixture) == before_reviewer
    lifecycle = [parse_lifecycle(turn.stdout, turn.stderr) for turn in turns]
    complete = len(turns) == 3 and all(turn_transport_complete(turn) for turn in turns) and all(evidence.values())
    _write_report(runtime, {"task_id": task_id, "route": {"model": MODEL, "provider": "custom", "reasoning_effort": REASONING, "timeout_seconds": TIMEOUT_SECONDS, "output_schema": False, "fallback": False}, "preflight": preflight, "transport_outcome": "transport-complete" if complete else "transport-failed", "turn_count": len(turns), "evidence": evidence, "lifecycle": lifecycle, "inventory_after_initial": after_initial, "protocol": qualification_plan()})
    return 0 if complete else 1


if __name__ == "__main__": raise SystemExit(main())
