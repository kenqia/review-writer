"""Standard-library-only helpers for safe Owner-Review orchestration."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESS_TIMEOUT_SECONDS = 600
ROLES = {
    "leader",
    "implementation-owner",
    "scientific-reviewer",
    "artifact-reviewer",
    "final-verifier",
    "explorer",
    "integration-owner",
}
READ_ONLY_ROLES = {"leader", "scientific-reviewer", "artifact-reviewer", "final-verifier", "explorer"}
RESULT_ROLES = {"implementation-owner", "integration-owner", "final-verifier"}
FINDING_ROLES = {"leader", "scientific-reviewer", "artifact-reviewer", "explorer"}
SAFE_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._+@=:/ -]+$")
TASK_SPEC_FIELDS = (
    "task_id", "objective", "background", "frozen_decisions", "allowed_paths",
    "forbidden_paths", "inputs", "required_outputs", "acceptance_criteria",
    "verification_commands", "safety_boundaries", "network_policy", "model_policy",
    "stop_conditions", "human_checkpoint",
)
ACCEPTANCE_ITEM_FIELDS = (
    "id", "requirement", "evidence_required", "verification_command", "expected_result",
    "owner", "severity", "status",
)
FINDING_FIELDS = (
    "finding_id", "reviewer_role", "severity", "requirement_id", "evidence",
    "affected_paths", "required_fix", "acceptance_test", "status",
)
WORKER_RESULT_FIELDS = (
    "task_id", "role", "session_id_reference", "status", "changed_files",
    "created_artifacts", "checks", "unresolved_findings", "risk_notes",
    "recommended_next_action",
)
FINDING_STATUSES = {"open", "resolved", "waived"}
MATRIX_STATUSES = {"pending", "pass", "partial", "fail"}
SEVERITIES = {"blocker", "major", "minor"}


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]


@dataclass(frozen=True)
class LaunchPlan:
    command: list[str]
    prompt: str
    sandbox: str
    execute: bool
    task_dir: Path
    turn: str
    role: str
    result_kind: str


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def is_safe_path(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and bool(SAFE_PATH.fullmatch(value))


def _required(payload: dict[str, Any], fields: Iterable[str]) -> list[str]:
    return [f"missing required field: {field}" for field in fields if field not in payload]


def _unexpected(payload: dict[str, Any], fields: Iterable[str]) -> list[str]:
    allowed = set(fields)
    return [f"unexpected field: {field}" for field in payload if field not in allowed]


def _safe_paths(payload: dict[str, Any], field: str) -> list[str]:
    values = payload.get(field, [])
    if not isinstance(values, list) or not values:
        return [f"{field} must be a non-empty list"]
    return [f"unsafe path in {field}: {value!r}" for value in values if not is_safe_path(value)]


def _safe_path_list(payload: dict[str, Any], field: str, *, allow_empty: bool = False) -> list[str]:
    values = payload.get(field)
    if not isinstance(values, list) or (not allow_empty and not values):
        return [f"{field} must be a {'list' if allow_empty else 'non-empty list'}"]
    return [f"unsafe path in {field}: {value!r}" for value in values if not is_safe_path(value)]


def _strings(payload: dict[str, Any], fields: Iterable[str]) -> list[str]:
    return [f"{field} must be a non-empty string" for field in fields if not isinstance(payload.get(field), str) or not payload[field].strip()]


def _string_list(payload: dict[str, Any], field: str) -> list[str]:
    values = payload.get(field)
    if not isinstance(values, list) or not values:
        return [f"{field} must be a non-empty list"]
    return [f"{field} contains a non-string value" for value in values if not isinstance(value, str) or not value.strip()]


def validate_task_spec(task: dict[str, Any]) -> list[str]:
    errors = _required(task, TASK_SPEC_FIELDS) + _unexpected(task, TASK_SPEC_FIELDS)
    if not re.fullmatch(r"[A-Z][A-Z0-9-]+", str(task.get("task_id", ""))):
        errors.append("invalid task_id")
    errors += _strings(task, ("objective", "background", "network_policy", "model_policy", "human_checkpoint"))
    for field in ("frozen_decisions", "inputs", "required_outputs", "acceptance_criteria", "verification_commands", "safety_boundaries", "stop_conditions"):
        errors += _string_list(task, field)
    errors += _safe_paths(task, "allowed_paths")
    errors += _safe_paths(task, "forbidden_paths")
    return errors


def validate_acceptance_matrix(matrix: dict[str, Any], task_id: str | None = None) -> list[str]:
    errors = _required(matrix, ("task_id", "items")) + _unexpected(matrix, ("task_id", "items"))
    if task_id is not None and matrix.get("task_id") != task_id:
        errors.append("task_id differs between task spec and acceptance matrix")
    items = matrix.get("items")
    if not isinstance(items, list) or not items:
        return errors + ["acceptance items must be a non-empty list"]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"acceptance item {index} must be an object")
            continue
        errors += [f"acceptance item {index}: {error}" for error in _required(item, ACCEPTANCE_ITEM_FIELDS)]
        errors += [f"acceptance item {index}: {error}" for error in _unexpected(item, ACCEPTANCE_ITEM_FIELDS)]
        errors += [f"acceptance item {index}: {error}" for error in _strings(item, ACCEPTANCE_ITEM_FIELDS)]
        if item.get("severity") not in SEVERITIES:
            errors.append(f"acceptance item {index}: invalid severity")
        if item.get("status") not in MATRIX_STATUSES:
            errors.append(f"acceptance item {index}: invalid status")
    return errors


def validate_contract(kind: str, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if kind == "findings":
        errors += _required(payload, ("task_id", "reviewer_role", "findings"))
        errors += _unexpected(payload, ("task_id", "reviewer_role", "findings"))
        if payload.get("reviewer_role") not in FINDING_ROLES:
            errors.append("invalid findings role")
        findings = payload.get("findings")
        if not isinstance(findings, list):
            errors.append("findings must be a list")
        else:
            for index, finding in enumerate(findings):
                if not isinstance(finding, dict):
                    errors.append(f"finding {index} must be an object")
                    continue
                errors += [f"finding {index}: {error}" for error in _required(finding, FINDING_FIELDS)]
                errors += [f"finding {index}: {error}" for error in _unexpected(finding, FINDING_FIELDS)]
                errors += [f"finding {index}: {error}" for error in _strings(finding, ("finding_id", "requirement_id", "evidence", "required_fix", "acceptance_test"))]
                if finding.get("reviewer_role") not in FINDING_ROLES:
                    errors.append(f"finding {index}: invalid reviewer_role")
                if finding.get("severity") not in SEVERITIES:
                    errors.append(f"finding {index}: invalid severity")
                if finding.get("status") not in FINDING_STATUSES:
                    errors.append(f"finding {index}: invalid status")
                errors += [f"finding {index}: {error}" for error in _safe_paths(finding, "affected_paths")]
    elif kind == "worker_result":
        errors += _required(payload, WORKER_RESULT_FIELDS)
        errors += _unexpected(payload, WORKER_RESULT_FIELDS)
        if payload.get("role") not in RESULT_ROLES:
            errors.append("invalid worker-result role")
        allowed_statuses = {"PASS", "BLOCKED", "ENVIRONMENT_UNDETERMINED"} if payload.get("role") == "final-verifier" else {"PASS", "PARTIAL", "FAIL"}
        if payload.get("status") not in allowed_statuses:
            errors.append("invalid worker-result status")
        errors += _strings(payload, ("task_id", "session_id_reference", "recommended_next_action"))
        if not re.fullmatch(r"captured-by-[A-Za-z0-9-]+", str(payload.get("session_id_reference", ""))):
            errors.append("invalid session_id_reference")
        for field in ("changed_files", "created_artifacts"):
            errors += _safe_path_list(payload, field, allow_empty=True)
        for field in ("unresolved_findings", "risk_notes"):
            errors += _string_list(payload, field) if payload.get(field) else ([] if isinstance(payload.get(field), list) else [f"{field} must be a list"])
        checks = payload.get("checks")
        if not isinstance(checks, list):
            errors.append("checks must be a list")
        else:
            for index, check in enumerate(checks):
                if not isinstance(check, dict):
                    errors.append(f"check {index} must be an object")
                    continue
                errors += [f"check {index}: {error}" for error in _required(check, ("requirement_id", "command", "status", "evidence"))]
                errors += [f"check {index}: {error}" for error in _strings(check, ("requirement_id", "command", "status", "evidence"))]
                if check.get("status") not in {"passed", "failed", "not-run"}:
                    errors.append(f"check {index}: invalid status")
    else:
        errors.append(f"unknown contract kind: {kind}")
    return errors


def result_kind_for_role(role: str) -> str:
    if role in FINDING_ROLES:
        return "findings"
    if role in RESULT_ROLES:
        return "worker_result"
    raise ValueError(f"role does not have an output contract: {role}")


def validate_role_result(role: str, payload: dict[str, Any]) -> list[str]:
    kind = result_kind_for_role(role)
    errors = validate_contract(kind, payload)
    if kind == "findings" and payload.get("reviewer_role") != role:
        errors.append("findings reviewer_role does not match launch role")
    if kind == "worker_result" and payload.get("role") != role:
        errors.append("worker-result role does not match launch role")
    return errors


def validate_task_package(task_dir: Path) -> ValidationResult:
    errors: list[str] = []
    try:
        task = load_json(task_dir / "task_spec.json")
        matrix = load_json(task_dir / "acceptance_matrix.json")
        assignments = load_json(task_dir / "agent_assignments.json")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return ValidationResult([str(error)])
    errors += validate_task_spec(task)
    errors += validate_acceptance_matrix(matrix, task.get("task_id"))
    errors += validate_assignments(assignments)
    if assignments.get("task_id") != task.get("task_id"):
        errors.append("task_id differs between task spec and assignments")
    return ValidationResult(errors)


def validate_assignments(payload: dict[str, Any]) -> list[str]:
    errors = _required(payload, ("task_id", "parallel_worktrees", "human_approval", "assignments"))
    errors += _unexpected(payload, ("task_id", "parallel_worktrees", "human_approval", "assignments"))
    if not isinstance(payload.get("parallel_worktrees"), bool):
        errors.append("parallel_worktrees must be a boolean")
    approval = payload.get("human_approval")
    if not isinstance(approval, dict) or approval.get("status") not in {"approved", "not-required"} or not isinstance(approval.get("recorded_by"), str) or not approval["recorded_by"].strip():
        errors.append("human_approval must record status and recorded_by")
    assignments = payload.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        return errors + ["assignments must be a non-empty list"]
    active_writers: dict[str, int] = {}
    review_roles = {"scientific-reviewer", "artifact-reviewer", "final-verifier"}
    worktrees: set[str] = set()
    for index, assignment in enumerate(assignments):
        if not isinstance(assignment, dict):
            errors.append(f"assignment {index} must be an object")
            continue
        fields = ("role", "worktree", "session_policy", "sandbox_mode", "status")
        errors += [f"assignment {index}: {error}" for error in _required(assignment, fields)]
        errors += [f"assignment {index}: {error}" for error in _unexpected(assignment, fields)]
        role = assignment.get("role")
        worktree = assignment.get("worktree")
        if role not in ROLES:
            errors.append(f"assignment {index}: invalid role")
        if not is_safe_path(worktree):
            errors.append(f"assignment {index}: unsafe worktree")
        else:
            worktrees.add(worktree)
        if assignment.get("status") not in {"planned", "active", "complete", "stopped"}:
            errors.append(f"assignment {index}: invalid status")
        if role in review_roles and (assignment.get("session_policy") != "fresh" or assignment.get("sandbox_mode") != "read-only"):
            errors.append(f"assignment {index}: reviewers and final verifier must be fresh read-only")
        if role in {"implementation-owner", "integration-owner"} and assignment.get("session_policy") != "persistent":
            errors.append(f"assignment {index}: writable owner must be persistent")
        if role in READ_ONLY_ROLES and assignment.get("sandbox_mode") != "read-only":
            errors.append(f"assignment {index}: read-only role is writable")
        if role in {"implementation-owner", "integration-owner"} and assignment.get("sandbox_mode") != "workspace-write":
            errors.append(f"assignment {index}: owner must use workspace-write")
        if assignment.get("status") == "active" and assignment.get("sandbox_mode") == "workspace-write" and isinstance(worktree, str):
            active_writers[worktree] = active_writers.get(worktree, 0) + 1
        if role == "integration-owner" and (not payload.get("parallel_worktrees") or not isinstance(approval, dict) or approval.get("status") != "approved"):
            errors.append("integration-owner requires recorded human approval and parallel worktrees")
    active_owner_entries = [item for item in assignments if isinstance(item, dict) and item.get("role") == "implementation-owner" and item.get("status") == "active"]
    active_integration = [item for item in assignments if isinstance(item, dict) and item.get("role") == "integration-owner" and item.get("status") == "active"]
    for worktree, count in active_writers.items():
        if count != 1:
            errors.append(f"worktree {worktree} has {count} active workspace-write owners")
    if not active_writers:
        errors.append("at least one active workspace-write owner is required")
    if not payload.get("parallel_worktrees"):
        if len(active_owner_entries) != 1 or active_integration:
            errors.append("non-parallel mode requires exactly one active Implementation Owner globally")
    else:
        owner_worktrees = {item.get("worktree") for item in active_owner_entries}
        if not isinstance(approval, dict) or approval.get("status") != "approved":
            errors.append("parallel mode requires explicit approved human record")
        if len(active_owner_entries) < 2 or len(owner_worktrees) != len(active_owner_entries):
            errors.append("parallel mode requires multiple Owners in distinct worktrees")
        if len(active_integration) != 1:
            errors.append("parallel mode requires one active Integration Owner")
    return errors


def validate_role_policy(repo_root: Path) -> ValidationResult:
    """Validate role documents and simple project-local Codex descriptors."""
    errors: list[str] = []
    role_dir = repo_root / "docs" / "agent-roles"
    descriptor_dir = repo_root / ".codex" / "agents"
    required_headings = ("Goal", "Inputs", "Outputs", "Allowed actions", "Forbidden actions", "Sandbox", "Session policy", "Completion standard", "Escalation")
    for role in sorted(ROLES):
        role_path = role_dir / f"{role}.md"
        if not role_path.is_file():
            errors.append(f"missing role document: {role_path.relative_to(repo_root)}")
        else:
            content = role_path.read_text(encoding="utf-8")
            for heading in required_headings:
                if heading not in content:
                    errors.append(f"role document missing {heading}: {role}")
        descriptor_path = descriptor_dir / f"{role}.toml"
        if not descriptor_path.is_file():
            errors.append(f"missing role descriptor: {descriptor_path.relative_to(repo_root)}")
            continue
        try:
            descriptor = tomllib.loads(descriptor_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            errors.append(f"invalid TOML descriptor {role}: {error}")
            continue
        for key in ("name", "description", "model", "reasoning_effort", "sandbox_mode", "instructions"):
            if not isinstance(descriptor.get(key), str) or not descriptor[key]:
                errors.append(f"descriptor {role} missing simple field: {key}")
        if descriptor.get("name") != role:
            errors.append(f"descriptor role mismatch: {role}")
        if descriptor.get("instructions") != f"docs/agent-roles/{role}.md":
            errors.append(f"descriptor instruction mismatch: {role}")
        expected_sandbox = "read-only" if role in READ_ONLY_ROLES else "workspace-write"
        if descriptor.get("sandbox_mode") != expected_sandbox:
            errors.append(f"descriptor sandbox mismatch: {role}")
        if role in READ_ONLY_ROLES and descriptor.get("sandbox_mode") == "workspace-write":
            errors.append(f"review/read-only role is writable: {role}")
    return ValidationResult(errors)


def _task_path(task_dir: Path) -> str:
    resolved = task_dir.resolve()
    root = REPO_ROOT.resolve()
    if root not in resolved.parents:
        raise ValueError("task package must remain inside the project")
    if validate_task_package(resolved).errors:
        raise ValueError("task package does not validate")
    return str(resolved.relative_to(root))


def _prompt(role: str, task_path: str, session_mode: str) -> str:
    return (
        f"Role: {role}. Task package: {task_path}. Session policy: {session_mode}. "
        "Read only the task package and explicitly allowed artifacts. Do not invoke nested codex exec. "
        "Do not read authentication material, install dependencies, commit, push, publish, deploy, or perform remote writes. "
        "Return a concise natural-language report: status, changes, checks, unresolved issues, and next step. "
        "The Leader interprets report meaning; the runner records transport evidence only."
    )


def _codex_command(model: str, reasoning_effort: str, sandbox: str, prompt: str, result_kind: str, resume: str | None = None) -> list[str]:
    """Build a no-Schema command with all route controls before a resume reference."""
    command = ["codex", "exec"]
    if resume is not None:
        command += ["resume", "--json", "--output-last-message", ".runtime/last-message.txt", "--model", model, "-c", 'model_provider="custom"', "-c", f'sandbox_mode="{sandbox}"', "-c", f"model_reasoning_effort={reasoning_effort}", resume, prompt]
    else:
        command += ["--json", "--output-last-message", ".runtime/last-message.txt", "--model", model, "--sandbox", sandbox, "-c", 'model_provider="custom"', "-c", f"model_reasoning_effort={reasoning_effort}", prompt]
    return command


def build_owner_command(
    task_dir: Path, *, execute: bool, workspace_write: bool, allow_workspace_write: bool = False,
    model: str = "gpt-5.6-terra", reasoning_effort: str = "medium"
) -> LaunchPlan:
    if execute and (model != "gpt-5.6-terra" or reasoning_effort != "medium"):
        raise ValueError("executable launches require the qualified Terra/custom/medium route")
    if workspace_write and not (execute and allow_workspace_write):
        raise ValueError("workspace-write requires --execute and --allow-workspace-write")
    task_path = _task_path(task_dir)
    sandbox = "workspace-write" if workspace_write else "read-only"
    prompt = _prompt("implementation-owner", task_path, "persistent owner")
    return LaunchPlan(_codex_command(model, reasoning_effort, sandbox, prompt, "worker_result"), prompt, sandbox, execute, task_dir, "initial", "implementation-owner", "worker_result")


def build_resume_command(task_dir: Path, session_reference: str, *, execute: bool, allow_workspace_write: bool = False, model: str = "gpt-5.6-terra", reasoning_effort: str = "medium") -> LaunchPlan:
    if execute and (model != "gpt-5.6-terra" or reasoning_effort != "medium"):
        raise ValueError("executable launches require the qualified Terra/custom/medium route")
    if execute and not allow_workspace_write:
        raise ValueError("workspace-write resume requires --execute and --allow-workspace-write")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", session_reference):
        raise ValueError("invalid opaque session reference")
    task_path = _task_path(task_dir)
    prompt = _prompt("implementation-owner", task_path, "resume original owner")
    return LaunchPlan(_codex_command(model, reasoning_effort, "workspace-write", prompt, "worker_result", session_reference), prompt, "workspace-write", execute, task_dir, "resume", "implementation-owner", "worker_result")


def build_reviewer_command(task_dir: Path, role: str, *, execute: bool, model: str = "gpt-5.6-terra", reasoning_effort: str = "medium") -> LaunchPlan:
    if execute and (model != "gpt-5.6-terra" or reasoning_effort != "medium"):
        raise ValueError("executable launches require the qualified Terra/custom/medium route")
    if role not in READ_ONLY_ROLES - {"leader"}:
        raise ValueError("review role must be a fresh read-only reviewer or verifier")
    task_path = _task_path(task_dir)
    prompt = _prompt(role, task_path, "fresh read-only session")
    kind = result_kind_for_role(role)
    return LaunchPlan(_codex_command(model, reasoning_effort, "read-only", prompt, kind), prompt, "read-only", execute, task_dir, "review", role, kind)


def run_plan(plan: LaunchPlan, runtime_dir: Path) -> int:
    print(f"SAFETY: sandbox={plan.sandbox}; execute={plan.execute}; no fallback; no nested codex exec.")
    print(f"COMMAND: codex exec {plan.turn} [redacted no-Schema JSON invocation]")
    if not plan.execute:
        print("PREVIEW: no model call was made.")
        return 0
    task = load_json(plan.task_dir / "task_spec.json")
    turn_identity = f"{plan.turn}-{plan.role}" if plan.turn == "review" else plan.turn
    turn_dir = runtime_dir / str(task["task_id"]) / turn_identity
    turn_dir.mkdir(parents=True, exist_ok=True)
    command = list(plan.command)
    output_index = command.index("--output-last-message") + 1
    command[output_index] = str(turn_dir / "last-message.txt")
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=PROCESS_TIMEOUT_SECONDS)
    (turn_dir / "events.jsonl").write_text(completed.stdout, encoding="utf-8")
    (turn_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    thread = _extract_thread_id(completed.stdout)
    if thread:
        (turn_dir / "session-reference.txt").write_text(thread + "\n", encoding="utf-8")
    errors = ["missing thread reference"] if thread is None else []
    if plan.turn == "resume":
        initial = runtime_dir / str(task["task_id"]) / "initial" / "session-reference.txt"
        if not initial.is_file() or initial.read_text(encoding="utf-8").strip() != thread:
            errors.append("resume thread does not match initial thread")
    # Worker reports are natural language.  Contract utilities remain available for
    # historical/offline packages, but must not turn prose into a workflow decision.
    return completed.returncode if not errors else 1


def merge_findings(reports: list[dict[str, Any]]) -> dict[str, Any]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for report in reports:
        for finding in report.get("findings", []):
            key = (str(finding.get("severity", "")), str(finding.get("required_fix", "")).strip().lower())
            if key not in seen:
                seen.add(key)
                merged.append(finding)
    task_id = reports[0].get("task_id", "") if reports else ""
    return {"task_id": task_id, "reviewer_role": "leader", "findings": merged}


def sanitize_summary(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"session_id", "session", "session_id_reference", "thread_id", "turn_id", "thread_reference", "thread_ref", "session_reference", "session_ref", "turn_reference", "turn_ref", "raw_log", "stderr", "stdout", "events", "full_output", "last_message", "prompt", "reply", "replies", "response", "responses", "output", "auth", "token", "authorization", "cookie"}
    def clean(value: Any, key: str = "") -> Any:
        if key.lower() in blocked:
            return None
        if isinstance(value, dict):
            return {child: cleaned for child, item in value.items() if (cleaned := clean(item, child)) is not None}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value
    return clean(payload)


def validate_worker_result_context(result: dict[str, Any], task: dict[str, Any], matrix: dict[str, Any]) -> list[str]:
    errors = validate_contract("worker_result", result)
    if result.get("task_id") != task.get("task_id"):
        errors.append("worker result task_id does not match task")
    if result.get("status") == "PASS":
        checks = result.get("checks", [])
        if not checks or any(check.get("status") != "passed" for check in checks if isinstance(check, dict)):
            errors.append("PASS requires non-empty passed checks")
        if result.get("unresolved_findings"):
            errors.append("PASS requires no unresolved findings")
        if result.get("role") == "final-verifier":
            covered = {check.get("requirement_id") for check in checks if isinstance(check, dict) and check.get("status") == "passed"}
            required = {item.get("id") for item in matrix.get("items", []) if isinstance(item, dict)}
            if not required.issubset(covered):
                errors.append("Final Verifier PASS lacks acceptance coverage")
    return errors


def _extract_thread_id(events: str) -> str | None:
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            return event["thread_id"]
    return None


def _extract_agent_result(events: str, output_path: Path) -> dict[str, Any] | None:
    text = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
    if not text:
        for line in events.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item") if isinstance(event, dict) else None
            if isinstance(item, dict) and event.get("type") == "item.completed" and item.get("type") == "agent_message":
                text = str(item.get("text", ""))
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
