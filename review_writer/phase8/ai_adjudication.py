from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable


RUN_ID_RE = re.compile(r"^phase8_three_layer_\d{8}T\d{6}Z$")
BLIND_ID_RE = re.compile(r"^BT-[0-9a-f]{16}$")
SENTINEL_VALUES = {
    "HUMAN_REVIEW_REQUIRED",
    "AI_EXTRACTED",
    "MISSING_SOURCE",
    "CONFLICT",
    "UNSUPPORTED_CANDIDATE",
    "NOT_FOUND",
    "N/A",
    "NA",
    "UNKNOWN",
}
MECHANISM_CLASSES = {
    "experimentally demonstrated",
    "author-proposed",
    "reviewer inference",
    "AI inference",
}
NEGATIVE_TERMS = ("no reaction", "failed", "not reported", "low-performing")

LAYER1_REQUIRED = {
    "blind_task_id",
    "fact_type",
    "entity_or_compound",
    "reaction_stage",
    "value_as_reported",
    "unit_as_reported",
    "normalized_value_candidate",
    "source_document_id",
    "pdf_page_index",
    "printed_page_label",
    "section",
    "table_scheme_entry_compound",
    "short_evidence",
    "directness",
    "source_found",
    "ambiguity_reason",
    "input_manifest_hash",
}
LAYER2_REQUIRED = {
    "blind_task_id",
    "verdict",
    "corrected_value_candidate",
    "fact_type_candidate",
    "reaction_stage_candidate",
    "source_document_id",
    "pdf_page_index",
    "printed_page_label",
    "section",
    "table_scheme_entry_compound",
    "short_evidence",
    "error_categories",
    "human_escalation_recommended",
    "input_manifest_hash",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _copy_reflink(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cp", "--reflink=auto", "--preserve=mode,timestamps", str(source), str(destination)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        shutil.copy2(source, destination)
    if sha256_file(source) != sha256_file(destination):
        raise RuntimeError(f"source copy hash mismatch: {source.name}")


def _source_files(evidence_root: Path, inventory: list[dict[str, Any]]) -> list[tuple[dict[str, Any], Path]]:
    found: list[tuple[dict[str, Any], Path]] = []
    for record in inventory:
        document_id = record["source_document_id"]
        path = evidence_root / "sources" / record["paper_id"] / f"{document_id}.pdf"
        if not path.is_file():
            if record.get("status") in {"SOURCE_FOUND", "SI_VALIDATED"}:
                raise ValueError(f"source inventory file missing: {document_id}")
            continue
        actual_hash = sha256_file(path)
        if record.get("sha256") and record["sha256"] != actual_hash:
            raise ValueError(f"source inventory hash mismatch: {document_id}")
        found.append((record, path))
    return found


def _opaque_task_id(run_id: str, index: int, random_seed: int) -> str:
    value = hashlib.sha256(f"{run_id}\0{random_seed}\0{index}".encode()).hexdigest()[:16]
    return f"BT-{value}"


def _minimal_locator(locator: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "source_document_id",
        "pdf_page_index",
        "printed_page_label",
        "section_heading",
        "table_id",
        "scheme_id",
        "figure_id",
        "entry_id",
        "compound_label",
    }
    return {key: locator.get(key) for key in sorted(allowed) if locator.get(key) is not None}


def _layer1_task(item: dict[str, Any], blind_id: str) -> dict[str, Any]:
    locator = _minimal_locator(item.get("source_locator", {}))
    return {
        "blind_task_id": blind_id,
        "source_document_id": locator.get("source_document_id"),
        "fact_category": item.get("field_name"),
        "required_output_fields": sorted(LAYER1_REQUIRED),
        "locator_hint": locator,
    }


def _layer2_task(item: dict[str, Any], blind_id: str) -> dict[str, Any]:
    locator = _minimal_locator(item.get("source_locator", {}))
    return {
        "blind_task_id": blind_id,
        "candidate_claim": item.get("candidate_value"),
        "candidate_locator": locator,
        "fact_type": item.get("field_name"),
        "source_document_id": locator.get("source_document_id"),
        "verification_rubric": "Open the source, check the value, entity, reaction stage, unit, and locator, then emit one schema-valid result.",
    }


def _agents_text(role: str) -> str:
    return (_template_root() / f"{role}_AGENTS.md").read_text(encoding="utf-8")


def _work_order_text(role: str) -> str:
    return (_template_root() / f"{role}_WORK_ORDER.md").read_text(encoding="utf-8")


def _schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas/phase8_ai_adjudication"


def _template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "templates/phase8_ai_adjudication"


def _build_input_manifest(workspace: Path, role: str) -> dict[str, Any]:
    paths = [workspace / "AGENTS.md", workspace / "WORK_ORDER.md"]
    for directory in ("sources", "input", "schemas"):
        paths.extend(path for path in (workspace / directory).rglob("*") if path.is_file())
    files = [
        {"path": path.relative_to(workspace).as_posix(), "sha256": sha256_file(path), "size": path.stat().st_size}
        for path in sorted(paths)
    ]
    return {
        "schema_version": "1.0",
        "package_role": role,
        "procedural_isolation_only": True,
        "files": files,
    }


def _make_read_only(workspace: Path) -> None:
    for relative in ("AGENTS.md", "WORK_ORDER.md", "INPUT_MANIFEST.json", "INPUT_MANIFEST.sha256"):
        os.chmod(workspace / relative, 0o444)
    for directory in ("sources", "input", "schemas"):
        for path in (workspace / directory).rglob("*"):
            if path.is_file():
                os.chmod(path, 0o444)
    os.chmod(workspace / "output", 0o755)


def _prepare_layer(
    workspace: Path,
    role: str,
    tasks: list[dict[str, Any]],
    sources: list[tuple[dict[str, Any], Path]],
) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=False)
    for directory in ("schemas", "sources", "input", "output"):
        (workspace / directory).mkdir()
    atomic_write_text(workspace / "AGENTS.md", _agents_text(role))
    atomic_write_text(workspace / "WORK_ORDER.md", _work_order_text(role))
    atomic_write_jsonl(workspace / "input/tasks.jsonl", tasks)
    shutil.copy2(_template_root() / "finalize_output.py", workspace / "input/finalize_output.py")
    source_hashes: dict[str, str] = {}
    for record, source in sources:
        destination = workspace / "sources" / f"{record['source_document_id']}.pdf"
        _copy_reflink(source, destination)
        source_hashes[destination.name] = sha256_file(destination)
    schema_name = f"{role}_output.schema.json"
    shutil.copy2(_schema_root() / schema_name, workspace / "schemas" / schema_name)
    manifest = _build_input_manifest(workspace, role)
    atomic_write_json(workspace / "INPUT_MANIFEST.json", manifest)
    manifest_hash = sha256_file(workspace / "INPUT_MANIFEST.json")
    atomic_write_text(workspace / "INPUT_MANIFEST.sha256", f"{manifest_hash}  INPUT_MANIFEST.json\n")
    _make_read_only(workspace)
    return {"manifest_hash": manifest_hash, "source_hashes": source_hashes}


def prepare_ab_workspaces(
    *,
    repo_root: Path,
    evidence_root: Path,
    workspace_parent: Path,
    run_id: str,
    repo_head: str,
    branch: str,
    pr_number: int,
    random_seed: int,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    evidence_root = evidence_root.resolve()
    workspace_parent = workspace_parent.resolve()
    if _is_within(workspace_parent, repo_root):
        raise ValueError("workspace parent must be outside the Git repository")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid run_id")
    run_root = workspace_parent / run_id
    saved_result = run_root / "coordinator/preparation_result.json"
    if run_root.exists():
        if saved_result.is_file():
            result = read_json(saved_result)
            for role, key in (("layer1", "layer1_workspace"), ("layer2", "layer2_workspace")):
                report = validate_workspace(Path(result[key]), role, repo_root=repo_root)
                if report["status"] != "PASS":
                    raise ValueError(f"existing prepared run is invalid: {role}")
            return result
        raise FileExistsError(f"run root already exists without resume state: {run_root}")
    inventory_path = evidence_root / "inventories/source_inventory.local.json"
    core_path = evidence_root / "review_queue/core_review_queue.json"
    extended_path = evidence_root / "review_queue/extended_review_queue.json"
    mapping_path = evidence_root / "review_queue/core_to_atomic_map.json"
    decisions_path = evidence_root / "review_decisions/reviewer_1.jsonl"
    inventory = read_json(inventory_path)
    core_items = read_json(core_path)["items"]
    sources = _source_files(evidence_root, inventory)
    run_root.mkdir(parents=True)
    coordinator = run_root / "coordinator"
    coordinator.mkdir()
    task_mapping: dict[str, dict[str, Any]] = {}
    tasks1: list[dict[str, Any]] = []
    tasks2: list[dict[str, Any]] = []
    for index, item in enumerate(core_items):
        blind_id = _opaque_task_id(run_id, index, random_seed)
        task_mapping[blind_id] = {
            "core_review_item_id": item["review_item_id"],
            "atomic_review_item_ids": item.get("atomic_extended_review_item_ids", []),
            "source_document_id": item.get("source_locator", {}).get("source_document_id"),
        }
        tasks1.append(_layer1_task(item, blind_id))
        tasks2.append(_layer2_task(item, blind_id))
    atomic_write_json(coordinator / "private_task_mapping.json", task_mapping)
    layer1 = run_root / "layer1_extractor"
    layer2 = run_root / "layer2_verifier"
    state1 = _prepare_layer(layer1, "layer1", tasks1, sources)
    state2 = _prepare_layer(layer2, "layer2", tasks2, sources)
    available_document_ids = {record["source_document_id"] for record, _ in sources}
    missing_references: dict[str, int] = {}
    for task in tasks1:
        document_id = task.get("source_document_id")
        if document_id and document_id not in available_document_ids:
            missing_references[document_id] = missing_references.get(document_id, 0) + 1
    input_blockers = [
        f"{count} task(s) reference unavailable source document {document_id}; do not substitute old generated content"
        for document_id, count in sorted(missing_references.items())
    ]
    run_manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "stage": "PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2",
        "repo_head": repo_head,
        "branch": branch,
        "pr_number": pr_number,
        "random_seed": random_seed,
        "source_inventory_hash": sha256_file(inventory_path),
        "core_queue_hash": sha256_file(core_path),
        "extended_queue_hash": sha256_file(extended_path),
        "core_to_atomic_map_hash": sha256_file(mapping_path),
        "human_decision_log_hash": sha256_file(decisions_path),
        "source_pdf_si_hashes": state1["source_hashes"],
        "scripts_version": sha256_file(Path(__file__)),
        "layer1_input_manifest_hash": state1["manifest_hash"],
        "layer2_input_manifest_hash": state2["manifest_hash"],
        "layer3_created": False,
        "method_label": "HUMAN_SPOT_CHECKED_AI_ADJUDICATION",
        "procedural_isolation_only": True,
        "input_blockers": input_blockers,
    }
    atomic_write_json(coordinator / "run_manifest.json", run_manifest)
    result = {
        "run_id": run_id,
        "run_root": str(run_root),
        "layer1_workspace": str(layer1),
        "layer2_workspace": str(layer2),
        "layer1_manifest_hash": state1["manifest_hash"],
        "layer2_manifest_hash": state2["manifest_hash"],
        "source_hashes_layer1": state1["source_hashes"],
        "source_hashes_layer2": state2["source_hashes"],
        "stage": "PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2",
        "input_blockers": input_blockers,
    }
    atomic_write_json(saved_result, result)
    return result


def verify_manifest(workspace: Path) -> dict[str, Any]:
    issues: list[str] = []
    manifest_path = workspace / "INPUT_MANIFEST.json"
    digest_path = workspace / "INPUT_MANIFEST.sha256"
    if not manifest_path.is_file() or not digest_path.is_file():
        return {"valid": False, "issues": ["input manifest files are missing"]}
    expected_manifest_hash = digest_path.read_text(encoding="utf-8").split()[0]
    if expected_manifest_hash != sha256_file(manifest_path):
        issues.append("INPUT_MANIFEST.json hash mismatch")
    try:
        manifest = read_json(manifest_path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"valid": False, "issues": [f"invalid input manifest: {exc}"]}
    for item in manifest.get("files", []):
        relative = Path(item.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts:
            issues.append(f"unsafe manifest path: {relative}")
            continue
        path = workspace / relative
        if not path.is_file():
            issues.append(f"manifest file missing: {relative.as_posix()}")
        elif sha256_file(path) != item.get("sha256"):
            issues.append(f"manifest hash mismatch: {relative.as_posix()}")
    return {"valid": not issues, "issues": issues, "manifest_hash": sha256_file(manifest_path)}


def _walk_json(value: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield path, "key", key
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")
    else:
        yield path, "value", value


def _scan_json_file(path: Path, role: str) -> list[str]:
    issues: list[str] = []
    value = read_json(path) if path.suffix == ".json" else read_jsonl(path)
    layer1_terms = ("candidate_value", "final_decision", "reviewer_note", "ai_accepted", "supported", "cannot_verify", "reviewer_1.jsonl", "layer2", "layer3")
    layer2_terms = ("layer1", "extractor_output", "reviewer_note", "reviewer_1.jsonl", "human decision log", "final correct value")
    terms = layer1_terms if role == "layer1" else layer2_terms
    for json_path, kind, item in _walk_json(value):
        if not isinstance(item, str):
            continue
        lowered = item.lower()
        for term in terms:
            if term in lowered:
                allowed = role == "layer1" and path.name == "layer1_output.schema.json" and kind == "value" and item in {"TABLE_SUPPORTED", "FIGURE_SUPPORTED"}
                if not allowed:
                    issues.append(f"{path.relative_to(path.parents[1]).as_posix()} {kind} at {json_path} contains forbidden term {term}")
    return issues


def validate_workspace(workspace: Path, role: str, *, repo_root: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    issues: list[str] = []
    if role not in {"layer1", "layer2"}:
        raise ValueError("role must be layer1 or layer2")
    if _is_within(workspace, repo_root.resolve()):
        issues.append("workspace is not outside the Git repository")
    if (workspace / ".git").exists():
        issues.append("workspace contains .git")
    for path in workspace.rglob("*"):
        if path.is_symlink():
            issues.append(f"symlink is forbidden: {path.relative_to(workspace)}")
    manifest = verify_manifest(workspace)
    issues.extend(manifest["issues"])
    for directory in ("sources", "input", "schemas"):
        for path in (workspace / directory).rglob("*"):
            if path.is_file() and path.stat().st_mode & stat.S_IWUSR:
                issues.append(f"input file is writable: {path.relative_to(workspace)}")
    for relative in ("AGENTS.md", "WORK_ORDER.md", "INPUT_MANIFEST.json", "INPUT_MANIFEST.sha256"):
        path = workspace / relative
        if path.is_file() and path.stat().st_mode & stat.S_IWUSR:
            issues.append(f"input file is writable: {relative}")
    if not (workspace / "output").is_dir() or not (workspace / "output").stat().st_mode & stat.S_IWUSR:
        issues.append("output directory is not writable")
    forbidden_filename_terms = ("reviewer_1", "layer2", "layer3") if role == "layer1" else ("layer1", "extractor_output", "reviewer_1")
    for path in workspace.rglob("*"):
        relative = path.relative_to(workspace).as_posix().lower()
        if any(term in relative for term in forbidden_filename_terms):
            issues.append(f"filename contains forbidden term: {relative}")
        if not path.is_file() or path.suffix.lower() == ".pdf":
            continue
        if path.suffix.lower() in {".json", ".jsonl"}:
            try:
                issues.extend(_scan_json_file(path, role))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                issues.append(f"invalid JSON content: {path.relative_to(workspace)}: {exc}")
        text = path.read_text(encoding="utf-8", errors="replace")
        if str(repo_root.resolve()) in text or re.search(r"(?:^|[\s\"'])/(?:home|Users|mnt)/", text):
            issues.append(f"absolute source path leaked: {path.relative_to(workspace)}")
        if re.search(r"chain[-_ ]of[-_ ]thought", text, flags=re.IGNORECASE):
            issues.append(f"reasoning-trace field leaked: {path.relative_to(workspace)}")
    tracked = subprocess.run(["git", "-C", str(repo_root), "ls-files"], capture_output=True, text=True)
    if tracked.returncode == 0 and any(line.lower().endswith((".pdf", ".si", ".supp")) for line in tracked.stdout.splitlines()):
        issues.append("Git tracks a PDF/SI source")
    return {"status": "PASS" if not issues else "FAIL", "issues": sorted(set(issues)), "manifest_hash": manifest.get("manifest_hash")}


def validate_ab_pair(layer1: Path, layer2: Path, *, repo_root: Path) -> dict[str, Any]:
    report1 = validate_workspace(layer1, "layer1", repo_root=repo_root)
    report2 = validate_workspace(layer2, "layer2", repo_root=repo_root)
    issues = [f"layer1: {issue}" for issue in report1["issues"]] + [f"layer2: {issue}" for issue in report2["issues"]]
    tasks1 = read_jsonl(layer1 / "input/tasks.jsonl")
    tasks2 = read_jsonl(layer2 / "input/tasks.jsonl")
    ids1 = [row.get("blind_task_id") for row in tasks1]
    ids2 = [row.get("blind_task_id") for row in tasks2]
    if ids1 != ids2 or len(ids1) != len(set(ids1)):
        issues.append("A/B task mappings are not one-to-one and ordered identically")
    if any(not isinstance(item, str) or not BLIND_ID_RE.fullmatch(item) for item in ids1):
        issues.append("blind task IDs are not opaque")
    manifest1 = read_json(layer1 / "INPUT_MANIFEST.json")
    manifest2 = read_json(layer2 / "INPUT_MANIFEST.json")
    sources1 = {item["path"]: item["sha256"] for item in manifest1["files"] if item["path"].startswith("sources/")}
    sources2 = {item["path"]: item["sha256"] for item in manifest2["files"] if item["path"].startswith("sources/")}
    if sources1 != sources2:
        issues.append("A/B source hashes differ")
    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": sorted(set(issues)),
        "task_count": len(ids1),
        "source_count": len(sources1),
        "layer1_manifest_hash": sha256_file(layer1 / "INPUT_MANIFEST.json"),
        "layer2_manifest_hash": sha256_file(layer2 / "INPUT_MANIFEST.json"),
    }


def _verify_output_manifest(workspace: Path) -> list[str]:
    issues: list[str] = []
    output = workspace / "output"
    manifest_path = output / "OUTPUT_MANIFEST.json"
    digest_path = output / "OUTPUT_MANIFEST.sha256"
    if not manifest_path.is_file() or not digest_path.is_file():
        return ["OUTPUT_MANIFEST.json and OUTPUT_MANIFEST.sha256 are required"]
    expected = digest_path.read_text(encoding="utf-8").split()[0]
    if expected != sha256_file(manifest_path):
        issues.append("OUTPUT_MANIFEST.json hash mismatch")
    manifest = read_json(manifest_path)
    results = output / "results.jsonl"
    if manifest.get("results_file") != "results.jsonl" or not results.is_file():
        issues.append("output manifest must reference results.jsonl")
    elif manifest.get("results_sha256") != sha256_file(results):
        issues.append("results.jsonl hash mismatch")
    else:
        rows = read_jsonl(results)
        if manifest.get("row_count") != len(rows):
            issues.append("output manifest row_count mismatch")
        if manifest.get("input_manifest_hash") != sha256_file(workspace / "INPUT_MANIFEST.json"):
            issues.append("output manifest input_manifest_hash mismatch")
    return issues


def validate_layer_output(workspace: Path, role: str) -> dict[str, Any]:
    issues = list(verify_manifest(workspace)["issues"])
    issues.extend(_verify_output_manifest(workspace))
    results = workspace / "output/results.jsonl"
    if not results.is_file():
        issues.append("output/results.jsonl is missing")
        return {"status": "FAIL", "issues": sorted(set(issues))}
    try:
        rows = read_jsonl(results)
        tasks = read_jsonl(workspace / "input/tasks.jsonl")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"status": "FAIL", "issues": sorted(set(issues + [f"invalid JSONL: {exc}"]))}
    expected_ids = [row["blind_task_id"] for row in tasks]
    actual_ids = [row.get("blind_task_id") for row in rows]
    if sorted(actual_ids) != sorted(expected_ids) or len(actual_ids) != len(set(actual_ids)):
        issues.append("output task coverage is not exactly one row per input task")
    required = LAYER1_REQUIRED if role == "layer1" else LAYER2_REQUIRED
    input_hash = sha256_file(workspace / "INPUT_MANIFEST.json")
    prohibited = {"accept", "reject", "verified", "human_verified", "chain_of_thought"}
    for index, row in enumerate(rows, start=1):
        missing = required - set(row)
        if missing:
            issues.append(f"row {index} missing fields: {', '.join(sorted(missing))}")
        if row.get("input_manifest_hash") != input_hash:
            issues.append(f"row {index} input_manifest_hash mismatch")
        if prohibited & {key.lower() for key in row}:
            issues.append(f"row {index} contains prohibited decision/reasoning fields")
        values = {str(value).upper() for value in row.values() if isinstance(value, str)}
        if values & {"VERIFIED", "HUMAN_VERIFIED", "FULLY_VERIFIED", "SCIENTIFICALLY_VERIFIED"}:
            issues.append(f"row {index} contains a prohibited verification label")
    allowed_files = {"results.jsonl", "OUTPUT_MANIFEST.json", "OUTPUT_MANIFEST.sha256"}
    extras = {path.name for path in (workspace / "output").iterdir() if path.name not in allowed_files}
    if extras:
        issues.append(f"unexpected output files: {', '.join(sorted(extras))}")
    return {"status": "PASS" if not issues else "FAIL", "issues": sorted(set(issues)), "row_count": len(rows)}


def _compact_candidate(row: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "fact_type",
        "fact_type_candidate",
        "reaction_stage",
        "reaction_stage_candidate",
        "value_as_reported",
        "normalized_value_candidate",
        "corrected_value_candidate",
        "unit_as_reported",
        "source_document_id",
        "pdf_page_index",
        "printed_page_label",
        "section",
        "table_scheme_entry_compound",
        "short_evidence",
        "directness",
        "source_found",
        "ambiguity_reason",
        "verdict",
        "error_categories",
        "human_escalation_recommended",
    }
    return {key: row[key] for key in sorted(allowed) if key in row}


def build_anonymous_layer3_inputs(
    first_rows: list[dict[str, Any]],
    second_rows: list[dict[str, Any]],
    *,
    random_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    first = {row["blind_task_id"]: row for row in first_rows}
    second = {row["blind_task_id"]: row for row in second_rows}
    if set(first) != set(second):
        raise ValueError("input task sets differ")
    ids = sorted(first)
    shuffled = list(ids)
    random.Random(random_seed).shuffle(shuffled)
    first_as_x = set(shuffled[::2])
    package: list[dict[str, Any]] = []
    private: dict[str, dict[str, str]] = {}
    for blind_id in ids:
        if blind_id in first_as_x:
            x, y = first[blind_id], second[blind_id]
            mapping = {"candidate_x_source": "first", "candidate_y_source": "second"}
        else:
            x, y = second[blind_id], first[blind_id]
            mapping = {"candidate_x_source": "second", "candidate_y_source": "first"}
        package.append({"blind_task_id": blind_id, "candidate_x": _compact_candidate(x), "candidate_y": _compact_candidate(y), "deterministic_rule_flags": []})
        private[blind_id] = mapping
    return package, private


def _flag(code: str, message: str, *, blocking: bool = True) -> dict[str, Any]:
    return {"code": code, "message": message, "blocking": blocking}


def deterministic_rule_flags(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    value = str(candidate.get("candidate_value") or candidate.get("value_as_reported") or "").strip()
    evidence = str(candidate.get("short_evidence") or "")
    fact_type = str(candidate.get("fact_type") or candidate.get("field_name") or "").lower()
    stage = str(candidate.get("reaction_stage") or "").lower()
    if value.upper() in SENTINEL_VALUES:
        flags.append(_flag("SENTINEL_SCIENTIFIC_VALUE", "Workflow sentinel cannot be used as a scientific value."))
    if not candidate.get("source_document_id") or candidate.get("pdf_page_index") is None:
        flags.append(_flag("MISSING_LOCATOR", "A source document and PDF page index are required."))
    numeric = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    if numeric and numeric.group(0) not in evidence:
        flags.append(_flag("NUMERIC_NOT_IN_LOCATOR_EVIDENCE", "The reported number is absent from the locator evidence."))
    unit = str(candidate.get("unit_as_reported") or "").strip()
    if unit and unit not in evidence:
        flags.append(_flag("UNIT_MISMATCH", "The reported unit is absent from the locator evidence."))
    if candidate.get("compound_label") and candidate.get("located_compound_label") and candidate["compound_label"] != candidate["located_compound_label"]:
        flags.append(_flag("COMPOUND_MISMATCH", "Candidate and located compound labels differ."))
    if candidate.get("entry_id") and candidate.get("located_entry_id") and candidate["entry_id"] != candidate["located_entry_id"]:
        flags.append(_flag("ENTRY_MISMATCH", "Candidate and located entry labels differ."))
    source_document_id = str(candidate.get("source_document_id") or "")
    source_role = str(candidate.get("source_role") or "").upper()
    if source_role and ((source_document_id.endswith("_SI") and source_role != "SI") or (source_document_id.endswith("_MAIN") and source_role != "MAIN")):
        flags.append(_flag("SOURCE_ROLE_MISMATCH", "Main article and supporting-information roles differ."))
    preparation_cues = ("prepared according to", "preparation of substrate", "isolated as a", "general procedure a")
    if any(cue in evidence.lower() for cue in preparation_cues) and stage in {"target_reaction", "catalytic_reaction", "product_formation"}:
        flags.append(_flag("SUBSTRATE_PREPARATION_VS_TARGET_REACTION", "The evidence describes substrate preparation rather than the target catalytic reaction."))
    if "substrate" in evidence.lower() and stage == "product_formation":
        flags.append(_flag("SUBSTRATE_VS_PRODUCT", "The named substrate must not be treated as the target product."))
    yield_type = str(candidate.get("yield_type") or "").lower()
    if yield_type and yield_type not in {"isolated_yield", "nmr_yield", "assay_yield", "conversion"}:
        flags.append(_flag("YIELD_TYPE_UNRECOGNIZED", "Yield, assay, and conversion types must remain distinct."))
    if any(metric in fact_type for metric in ("ee", "er", "dr")) and candidate.get("conversion_formula") and not candidate.get("original_value"):
        flags.append(_flag("UNTRACEABLE_STEREOMETRIC_CONVERSION", "A stereometric conversion requires the original value and formula."))
    if "mechanism" in fact_type:
        mechanism_class = candidate.get("mechanism_class")
        if mechanism_class not in MECHANISM_CLASSES:
            flags.append(_flag("MECHANISM_EPISTEMIC_CLASS_MISSING", "Mechanistic claims require an allowed epistemic class."))
        elif mechanism_class in {"reviewer inference", "AI inference"}:
            flags.append(_flag("MECHANISM_EPISTEMIC_CLASS", f"Mechanistic statement is classified as {mechanism_class}.", blocking=False))
    negative_claim = str(candidate.get("negative_claim") or "").lower()
    if negative_claim and not any(term in evidence.lower() for term in NEGATIVE_TERMS):
        flags.append(_flag("UNSUPPORTED_NEGATIVE_CLAIM", "Negative performance language lacks an explicit source statement."))
    if "figure" in fact_type and not (candidate.get("figure_id") and candidate.get("pdf_page_index") is not None):
        flags.append(_flag("FIGURE_LOCATOR_REQUIRED", "Figure conclusions require figure/caption/page location."))
    if source_role == "BIBLIOGRAPHY" and fact_type not in {"bibliography", "metadata"}:
        flags.append(_flag("BIBLIOGRAPHY_NOT_SCIENTIFIC_EVIDENCE", "Bibliographic metadata cannot substitute for scientific body evidence."))
    return flags


def reconcile_ai_with_human(ai_rows: list[dict[str, Any]], human_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    effective: dict[str, dict[str, Any]] = {}
    for row in human_rows:
        item_id = row.get("core_review_item_id") or row.get("review_item_id")
        if item_id:
            effective[item_id] = row
    result: list[dict[str, Any]] = []
    for source in ai_rows:
        row = dict(source)
        human = effective.get(row.get("core_review_item_id"))
        row["superseded_by_human_decision"] = human is not None
        row["human_decision_id"] = human.get("decision_id") if human else None
        result.append(row)
    return result


def select_human_spot_checks(
    ai_rows: list[dict[str, Any]],
    human_rows: list[dict[str, Any]],
    *,
    total_budget: int,
    random_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    used_ids = {
        row.get("core_review_item_id") or row.get("review_item_id")
        for row in human_rows
        if row.get("core_review_item_id") or row.get("review_item_id")
    }
    used = len(used_ids)
    if used > total_budget:
        raise ValueError("existing human decisions exceed total budget")
    remaining = total_budget - used
    pool = [row for row in ai_rows if row.get("core_review_item_id") not in used_ids]
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def add(row: dict[str, Any], reason: str) -> None:
        item_id = row["core_review_item_id"]
        if len(selected) < remaining and item_id not in selected_ids:
            selected.append({**row, "selection_reason": reason})
            selected_ids.add(item_id)

    high = sorted(
        (row for row in pool if row.get("final_ai_status") in {"AI_UNRESOLVED", "RULE_BLOCKED"} or int(row.get("human_risk_score", 0)) >= 3),
        key=lambda row: (-int(row.get("human_risk_score", 0)), row["core_review_item_id"]),
    )
    for row in high[:2]:
        add(row, "highest_risk")
    risk_types = {"mechanism", "figure", "unsupported negative claim", "negative_claim"}
    if not any(str(row.get("fact_type", "")).lower() in risk_types for row in selected):
        candidates = sorted(
            (row for row in pool if str(row.get("fact_type", "")).lower() in risk_types),
            key=lambda row: (-int(row.get("human_risk_score", 0)), row["core_review_item_id"]),
        )
        if candidates:
            add(candidates[0], "highest_risk_special_category")
    low = [
        row
        for row in pool
        if row.get("final_ai_status") in {"AI_CONSENSUS_ACCEPT", "AI_ADJUDICATED_ACCEPT"}
        and int(row.get("human_risk_score", 0)) <= 1
        and row.get("rules_passed", False)
        and row["core_review_item_id"] not in selected_ids
    ]
    random.Random(random_seed).shuffle(low)
    if low:
        add(low[0], "seeded_low_risk_consensus_sample")
    report = {
        "used_budget": used,
        "total_budget": total_budget,
        "remaining_budget_before_selection": remaining,
        "selected_count": len(selected),
        "remaining_budget_after_selection": remaining - len(selected),
        "random_seed": random_seed,
        "unselected_high_risk_count": sum(row["core_review_item_id"] not in selected_ids for row in high),
        "sample_size_note": "small human spot-check sample; engineering signal only; not a publication-grade validation estimate",
    }
    return selected, report


def initialize_local_ai_state(evidence_root: Path, result: dict[str, Any], *, random_seed: int) -> dict[str, Any]:
    root = evidence_root / "ai_adjudication"
    for relative in ("layer1", "layer2", "layer3", "deterministic_rules", "reports"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    human_path = evidence_root / "review_decisions/reviewer_1.jsonl"
    human_rows = read_jsonl(human_path) if human_path.is_file() else []
    effective_ids = {
        row.get("core_review_item_id") or row.get("review_item_id")
        for row in human_rows
        if row.get("core_review_item_id") or row.get("review_item_id")
    }
    reconciliation = {
        "schema_version": "1.0",
        "run_id": result["run_id"],
        "effective_human_decisions": len(effective_ids),
        "human_budget_total": 10,
        "human_budget_remaining": max(0, 10 - len(effective_ids)),
        "expected_first_six_present": len(effective_ids) >= 6,
        "target_edit_present": any(
            (row.get("core_review_item_id") or row.get("review_item_id")) == "RU-P403-SI-FIELD-11"
            and row.get("final_decision") == "edit"
            for row in human_rows
        ),
        "decision_log_hash": sha256_file(human_path) if human_path.is_file() else hashlib.sha256(b"").hexdigest(),
        "method_label": "HUMAN_SPOT_CHECKED_AI_ADJUDICATION",
        "random_seed": random_seed,
    }
    atomic_write_json(root / "reports/human_decision_reconciliation.json", reconciliation)
    report_md = "\n".join(
        [
            "# Human Decision Reconciliation",
            "",
            f"- effective unique core decisions: `{reconciliation['effective_human_decisions']}`",
            f"- budget used: `{reconciliation['effective_human_decisions']}/10`",
            f"- budget remaining: `{reconciliation['human_budget_remaining']}`",
            f"- target edit present: `{reconciliation['target_edit_present']}`",
            "- decision precedence: effective human decision > new AI adjudication > old AI extraction",
            "",
        ]
    )
    atomic_write_text(root / "reports/human_decision_reconciliation.md", report_md)
    coordinator_manifest = read_json(Path(result["run_root"]) / "coordinator/run_manifest.json")
    atomic_write_json(root / "run_manifest.json", coordinator_manifest)
    return reconciliation


def write_coordinator_resume(
    result: dict[str, Any],
    *,
    human_budget_used: int,
    blockers: list[str],
) -> Path:
    launch = "请严格遵循当前工作区 AGENTS.md 与 WORK_ORDER.md，离线完成全部任务，只写 schema 要求的结构化结果及输出 manifest；完成后停止，不读取工作区外任何路径。"
    path = Path(result["run_root"]) / "coordinator/COORDINATOR_RESUME.md"
    text = f"""# Phase 8 Three-Layer Coordinator Resume

- run ID: `{result['run_id']}`
- current stage: `PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2`
- method: `HUMAN_SPOT_CHECKED_AI_ADJUDICATION`
- Layer 1 input manifest: `{result['layer1_manifest_hash']}`
- Layer 2 input manifest: `{result['layer2_manifest_hash']}`
- Layer 1 workspace: `{result['layer1_workspace']}`
- Layer 2 workspace: `{result['layer2_workspace']}`
- Layer 3: not created
- human budget: `{human_budget_used}/10` used, `{max(0, 10 - human_budget_used)}` remaining

## Manual Launch

Open each workspace in a separate new VS Code window and start a fresh Codex session with no inherited context. Send this same sentence in each session:

```text
{launch}
```

Do not copy results between the two sessions. Neither session may read a parent, sibling, repository, or network path.

## Ingest After Both Sessions Finish

Return to the coordinator session and state that both independent sessions are complete. The coordinator must verify both output manifests, exact task coverage, unchanged inputs, allowed fields, and absence of human labels or reasoning traces before creating any anonymous third-stage package. Scientific values must not be silently repaired during ingest.

## Isolation Scope

This is procedural context isolation, not an operating-system security sandbox and not statistical independence between model weights.

## Blockers

{chr(10).join(f'- {item}' for item in blockers) if blockers else '- none'}
"""
    atomic_write_text(path, text)
    return path


def utc_run_id() -> str:
    return time.strftime("phase8_three_layer_%Y%m%dT%H%M%SZ", time.gmtime())
