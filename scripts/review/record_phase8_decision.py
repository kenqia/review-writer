#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

FINAL_DECISIONS = {"accept", "reject", "edit", "cannot_verify", "defer"}
REQUIRED_EVENT_FIELDS = {
    "decision_id",
    "batch_id",
    "sequence_number",
    "reviewer_id",
    "review_mode",
    "review_item_id",
    "core_review_item_id",
    "atomic_review_item_ids",
    "original_ai_record_hash",
    "preliminary_decision",
    "ai_recommendation_shown",
    "ai_recommendation",
    "final_decision",
    "edited_value",
    "reviewer_note",
    "evidence_opened",
    "evidence_document_ids",
    "evidence_locators",
    "created_at",
    "supersedes_decision_id",
    "decision_scope",
    "original_value",
}
PACKAGE_FILES = (
    "inventories/source_inventory.local.json",
    "review_queue/core_review_queue.json",
    "review_queue/extended_review_queue.json",
    "review_queue/core_to_atomic_map.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit or append Phase 8A guided human decisions safely.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--root", type=Path, required=True)
    audit.add_argument("--write-reports", action="store_true")
    audit.add_argument("--repair-corrupt-tail", action="store_true")
    audit.add_argument("--dashboard-port", type=int, default=8787)
    audit.add_argument("--warning", action="append", default=[])
    record = subparsers.add_parser("record")
    record.add_argument("--root", type=Path, required=True)
    record.add_argument("--input", type=Path, required=True)
    record.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_state(root: Path) -> dict:
    missing = [rel for rel in PACKAGE_FILES if not (root / rel).is_file()]
    if missing:
        raise ValueError(f"missing package files: {', '.join(missing)}")
    file_hashes = {rel: sha256_file(root / rel) for rel in PACKAGE_FILES}
    manifest_payload = "".join(f"{rel}\0{file_hashes[rel]}\n" for rel in PACKAGE_FILES).encode()
    core = json.loads((root / PACKAGE_FILES[1]).read_text(encoding="utf-8"))["items"]
    extended = json.loads((root / PACKAGE_FILES[2]).read_text(encoding="utf-8"))["items"]
    mapping = json.loads((root / PACKAGE_FILES[3]).read_text(encoding="utf-8"))["items"]
    return {
        "package_manifest_hash": hashlib.sha256(manifest_payload).hexdigest(),
        "source_inventory_hash": file_hashes[PACKAGE_FILES[0]],
        "core_queue_hash": file_hashes[PACKAGE_FILES[1]],
        "extended_queue_hash": file_hashes[PACKAGE_FILES[2]],
        "mapping_hash": file_hashes[PACKAGE_FILES[3]],
        "core_items": core,
        "extended_items": extended,
        "mapping": mapping,
    }


def audit_log(root: Path) -> dict:
    path = root / "review_decisions/reviewer_1.jsonl"
    result = {"events": [], "warnings": [], "blockers": [], "corrupt_tail": False}
    if not path.exists():
        result["effective"] = {}
        return result
    raw_lines = path.read_bytes().splitlines(keepends=True)
    for index, raw in enumerate(raw_lines, start=1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if index == len(raw_lines):
                result["corrupt_tail"] = True
                result["warnings"].append(f"corrupt final JSONL line {index}: {exc}")
            else:
                result["blockers"].append(f"corrupt non-final JSONL line {index}: {exc}")
            continue
        missing = REQUIRED_EVENT_FIELDS - set(event)
        if missing or event.get("final_decision") not in FINAL_DECISIONS:
            result["blockers"].append(f"unknown or invalid decision event at line {index}")
            continue
        result["events"].append(event)
    ids = [event["decision_id"] for event in result["events"]]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        result["blockers"].append(f"duplicate decision_id: {', '.join(duplicates)}")
    result["effective"] = effective_events(result["events"], result["blockers"])
    return result


def effective_events(events: list[dict], blockers: list[str]) -> dict[str, dict]:
    effective: dict[str, dict] = {}
    id_to_item: dict[str, str] = {}
    for event in events:
        item_id = event["core_review_item_id"]
        supersedes = event.get("supersedes_decision_id")
        if supersedes:
            if id_to_item.get(supersedes) != item_id:
                blockers.append(f"invalid supersedes relation: {event['decision_id']}")
                continue
            if effective.get(item_id, {}).get("decision_id") != supersedes:
                blockers.append(f"supersedes is not current: {event['decision_id']}")
                continue
        elif item_id in effective:
            blockers.append(f"multiple effective decisions without supersedes: {item_id}")
            continue
        effective[item_id] = event
        id_to_item[event["decision_id"]] = item_id
    return effective


def repair_corrupt_tail(root: Path, audit: dict) -> None:
    if not audit["corrupt_tail"]:
        return
    timestamp = utc_now().replace(":", "").replace("-", "")
    recovery = root / "backups" / f"recovery_{timestamp}"
    recovery.mkdir(parents=True, exist_ok=False)
    log = root / "review_decisions/reviewer_1.jsonl"
    shutil.copy2(log, recovery / "reviewer_1.original.jsonl")
    valid = b"".join((json.dumps(event, ensure_ascii=False) + "\n").encode() for event in audit["events"])
    atomic_write_bytes(log, valid)


def validate_batch(events: list[dict], package: dict, audit: dict) -> list[dict]:
    if not events:
        raise ValueError("batch contains no events")
    if audit["blockers"] or audit["corrupt_tail"]:
        raise ValueError("decision log requires reconciliation before recording")
    core_by_id = {item["review_item_id"]: item for item in package["core_items"]}
    existing_ids = {event["decision_id"] for event in audit["events"]}
    batch_ids: set[str] = set()
    normalized = []
    for source in events:
        event = dict(source)
        missing = REQUIRED_EVENT_FIELDS - set(event)
        if missing:
            raise ValueError(f"missing event fields: {', '.join(sorted(missing))}")
        decision_id = event["decision_id"]
        if decision_id in existing_ids or decision_id in batch_ids:
            raise ValueError(f"duplicate decision_id: {decision_id}")
        batch_ids.add(decision_id)
        if event["reviewer_id"] != "reviewer_1" or event["review_mode"] != "guided_chat":
            raise ValueError("reviewer_id/review_mode mismatch")
        if event["final_decision"] not in FINAL_DECISIONS:
            raise ValueError("invalid final_decision")
        if event["final_decision"] == "edit" and not event["edited_value"]:
            raise ValueError("edit requires edited_value")
        item = core_by_id.get(event["core_review_item_id"])
        if not item or event["review_item_id"] != event["core_review_item_id"]:
            raise ValueError(f"unknown core review item: {event['core_review_item_id']}")
        if event["original_ai_record_hash"] != item["ai_record_hash"]:
            raise ValueError(f"AI record hash mismatch: {event['core_review_item_id']}")
        expected_atomic = item.get("atomic_extended_review_item_ids", [])
        if event["atomic_review_item_ids"] != expected_atomic:
            raise ValueError(f"atomic mapping mismatch: {event['core_review_item_id']}")
        current = audit["effective"].get(event["core_review_item_id"])
        if current and event.get("supersedes_decision_id") != current["decision_id"]:
            raise ValueError(f"existing decision requires supersedes: {event['core_review_item_id']}")
        if not current and event.get("supersedes_decision_id"):
            raise ValueError(f"supersedes target missing: {event['core_review_item_id']}")
        for key in ("package_manifest_hash", "source_inventory_hash"):
            if event.get(key) not in (None, package[key]):
                raise ValueError(f"{key} mismatch")
            event[key] = package[key]
        normalized.append(event)
    if len({event["batch_id"] for event in normalized}) != 1:
        raise ValueError("all events must share one batch_id")
    if len({event["sequence_number"] for event in normalized}) != len(normalized):
        raise ValueError("sequence_number must be unique within the batch")
    return sorted(normalized, key=lambda event: event["sequence_number"])


def record_batch(root: Path, input_path: Path, dry_run: bool) -> dict:
    package = package_state(root)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    events = payload.get("events", [])
    lock_path = root / "review_decisions/.reviewer_1.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        audit = audit_log(root)
        normalized = validate_batch(events, package, audit)
        if dry_run:
            return {"status": "dry_run", "event_count": len(normalized), **hash_summary(package)}
        log_path = root / "review_decisions/reviewer_1.jsonl"
        block = b"".join((json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n").encode() for event in normalized)
        append_and_fsync(log_path, block)
        verified = audit_log(root)
        if verified["blockers"] or verified["corrupt_tail"]:
            raise RuntimeError("post-write decision log validation failed")
        state = write_state_reports(root, package, verified)
        backup = create_batch_backup(root, normalized[0]["batch_id"])
        return {"status": "recorded", "event_count": len(normalized), "backup": backup.name, **state}


def write_state_reports(root: Path, package: dict, audit: dict, settings: dict | None = None) -> dict:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    settings = settings or load_session_settings(root)
    effective = audit["effective"]
    counts = Counter(event["final_decision"] for event in effective.values())
    decided_ids = {item_id for item_id, event in effective.items() if event["final_decision"] != "defer"}
    unresolved = [item for item in package["core_items"] if item["review_item_id"] not in decided_ids]
    last = audit["events"][-1] if audit["events"] else None
    log_path = root / "review_decisions/reviewer_1.jsonl"
    checkpoint = {
        "schema_version": "1.0",
        "branch": git_value("branch"),
        "head_sha": git_value("head"),
        "pr_number": 3,
        **hash_summary(package),
        "decision_log_hash": sha256_file(log_path) if log_path.exists() else hashlib.sha256(b"").hexdigest(),
        "review_input_mode": "guided_chat",
        "dashboard_port": settings["dashboard_port"],
        "warnings": settings["warnings"],
        "total_core": len(package["core_items"]),
        "effective_decided": len(decided_ids),
        **{f"{decision}_count": counts[decision] for decision in sorted(FINAL_DECISIONS)},
        "unresolved_count": len(unresolved),
        "last_completed_batch_id": last.get("batch_id") if last else None,
        "last_completed_review_item_id": last.get("core_review_item_id") if last else None,
        "next_review_item_ids": [item["review_item_id"] for item in unresolved[:5]],
        "atomic_coverage": sorted({atomic for item_id, event in effective.items() if item_id in decided_ids for atomic in event["atomic_review_item_ids"]}),
        "created_at": utc_now(),
    }
    atomic_write_json(reports / "checkpoint.json", checkpoint)
    progress = render_progress(package["core_items"], effective, checkpoint)
    atomic_write_text(reports / "progress.md", progress)
    resume = render_resume(checkpoint)
    atomic_write_text(reports / "session_resume.md", resume)
    return {"effective_decided": checkpoint["effective_decided"], "unresolved_count": checkpoint["unresolved_count"]}


def render_progress(core_items: list[dict], effective: dict[str, dict], checkpoint: dict) -> str:
    lines = [
        "# Phase 8A Human Review Progress",
        "",
        f"- effective decided: `{checkpoint['effective_decided']}/{checkpoint['total_core']}`",
        f"- unresolved: `{checkpoint['unresolved_count']}`",
    ]
    for decision in sorted(FINAL_DECISIONS):
        lines.append(f"- {decision}: `{checkpoint[f'{decision}_count']}`")
    for field in ("phase7_claim", "numeric", "mechanism", "figure"):
        ids = [item["review_item_id"] for item in core_items if field in item.get("field_name", "").lower()]
        done = sum(item_id in effective and effective[item_id]["final_decision"] != "defer" for item_id in ids)
        lines.append(f"- {field}: `{done}/{len(ids)}`")
    lines.extend(["", f"- last batch: `{checkpoint['last_completed_batch_id']}`", ""])
    return "\n".join(lines)


def render_resume(checkpoint: dict) -> str:
    safe = {
        "repository": "review-writer",
        "branch": checkpoint["branch"],
        "PR number": checkpoint["pr_number"],
        "package manifest hash": checkpoint["package_manifest_hash"],
        "core queue hash": checkpoint["core_queue_hash"],
        "extended queue hash": checkpoint["extended_queue_hash"],
        "decision log hash": checkpoint["decision_log_hash"],
        "total core items": checkpoint["total_core"],
        "effective decided count": checkpoint["effective_decided"],
        "unresolved count": checkpoint["unresolved_count"],
        "last completed batch": checkpoint["last_completed_batch_id"],
        "next unresolved item IDs": checkpoint["next_review_item_ids"],
        "current checkpoint": "HUMAN_REVIEW_REQUIRED",
        "dashboard command": f"make phase8-dashboard-check && conda run -n review-writer-phase8 python scripts/review/serve_phase8_evidence_review.py --root local/phase8_evidence --host 127.0.0.1 --port {checkpoint['dashboard_port']}",
        "decision input mode": "guided_chat",
        "warnings/blockers": checkpoint["warnings"],
        "updated_at": checkpoint["created_at"],
    }
    return "# Phase 8A Session Resume\n\n```json\n" + json.dumps(safe, ensure_ascii=False, indent=2) + "\n```\n"


def write_recovery_audit(root: Path, package: dict, audit: dict) -> None:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    data = {
        "status": "BLOCKED" if audit["blockers"] or audit["corrupt_tail"] else "RECOVERED",
        "event_count": len(audit["events"]),
        "effective_decision_count": len(audit["effective"]),
        "warnings": audit["warnings"],
        "blockers": audit["blockers"],
        **hash_summary(package),
        "updated_at": utc_now(),
    }
    atomic_write_json(reports / "recovery_audit.json", data)
    lines = ["# Phase 8A Recovery Audit", ""] + [f"- {key}: `{value}`" for key, value in data.items() if key not in {"warnings", "blockers"}]
    lines += ["", "## Warnings", ""] + [f"- {warning}" for warning in data["warnings"]] if data["warnings"] else ["", "## Warnings", "", "- none"]
    lines += ["", "## Blockers", ""] + [f"- {blocker}" for blocker in data["blockers"]] if data["blockers"] else ["", "## Blockers", "", "- none"]
    atomic_write_text(reports / "recovery_audit.md", "\n".join(lines) + "\n")


def create_batch_backup(root: Path, batch_id: str) -> Path:
    timestamp = utc_now().replace(":", "").replace("-", "")
    target = root / "backups" / f"{batch_id}_{timestamp}"
    target.mkdir(parents=True, exist_ok=False)
    sources = [
        root / "review_decisions/reviewer_1.jsonl",
        root / "reports/checkpoint.json",
        root / "reports/progress.md",
        root / "reports/session_resume.md",
    ]
    manifest = []
    for source in sources:
        destination = target / source.name
        shutil.copy2(source, destination)
        manifest.append(f"{sha256_file(destination)}  {destination.name}")
    atomic_write_text(target / "manifest.sha256", "\n".join(manifest) + "\n")
    return target


def hash_summary(package: dict) -> dict:
    return {key: package[key] for key in ("package_manifest_hash", "source_inventory_hash", "core_queue_hash", "extended_queue_hash")}


def load_session_settings(root: Path) -> dict:
    path = root / "reports/session_settings.json"
    if not path.exists():
        return {"dashboard_port": 8787, "warnings": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"dashboard_port": int(data.get("dashboard_port", 8787)), "warnings": list(data.get("warnings", []))}


def append_and_fsync(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def atomic_write_text(path: Path, value: str) -> None:
    atomic_write_bytes(path, value.encode("utf-8"))


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(value)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def git_value(kind: str) -> str:
    command = ["git", "branch", "--show-current"] if kind == "branch" else ["git", "rev-parse", "HEAD"]
    result = subprocess.run(command, text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main() -> int:
    args = parse_args()
    try:
        root = args.root.resolve()
        if args.command == "record":
            result = record_batch(root, args.input, args.dry_run)
        else:
            package = package_state(root)
            audit = audit_log(root)
            if args.repair_corrupt_tail and audit["corrupt_tail"] and not audit["blockers"]:
                repair_corrupt_tail(root, audit)
                audit = audit_log(root)
                audit["warnings"].append("corrupt final line recovered from last complete event")
            audit["warnings"].extend(args.warning)
            if args.write_reports:
                settings = {"dashboard_port": args.dashboard_port, "warnings": audit["warnings"] + audit["blockers"]}
                atomic_write_json(root / "reports/session_settings.json", settings)
                write_recovery_audit(root, package, audit)
                write_state_reports(root, package, audit, settings)
            result = {
                "status": "blocked" if audit["blockers"] or audit["corrupt_tail"] else "audited",
                "event_count": len(audit["events"]),
                "effective_decision_count": len(audit["effective"]),
                "warnings": audit["warnings"],
                "blockers": audit["blockers"],
                **hash_summary(package),
            }
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] != "blocked" else 2
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"phase8-decision-writer: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
