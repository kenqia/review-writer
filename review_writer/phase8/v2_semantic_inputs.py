from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from collections import Counter
from pathlib import Path
from typing import Any

from .ai_adjudication import (
    _build_input_manifest,
    _copy_reflink,
    _is_within,
    _make_read_only,
    _schema_root,
    _template_root,
    atomic_write_json,
    atomic_write_jsonl,
    atomic_write_text,
    read_json,
    sha256_file,
    verify_manifest,
)


V2_RUN_ID_RE = re.compile(r"^phase8_three_layer_v2_\d{8}T\d{6}Z$")
VALID_IDENTITY_STATUSES = {
    "IDENTITY_VALIDATED_STRONG",
    "IDENTITY_VALIDATED_PROBABLE",
    "IDENTITY_CONFLICT",
    "IDENTITY_INSUFFICIENT",
}
VALID_TASK_MODES = {"CANDIDATE_VERIFICATION", "BLIND_DUAL_EXTRACTION"}
VALID_LOCATOR_QUALITIES = {"EXACT_VERIFIED", "SECTION_WINDOW", "PAGE_WINDOW", "SOURCE_ONLY", "UNAVAILABLE"}
SENTINEL_CANDIDATES = {
    "",
    "HUMAN_REVIEW_REQUIRED",
    "AI_EXTRACTED",
    "MISSING_SOURCE",
    "CONFLICT",
    "UNSUPPORTED_CANDIDATE",
    "NO_SI_PUBLISHED_ON_OFFICIAL_PAGE",
}


IDENTITY_PROFILES: dict[str, dict[str, Any]] = {
    "F3I_MAIN": {
        "source_document_id": "F3I_MAIN",
        "source_role": "MAIN",
        "paper_id": "F3I",
        "doi_family": ["10.1002/anie.201101460"],
        "title_markers": ["allenes", "catalytic asymmetric synthesis", "natural product syntheses"],
        "author_markers": ["shichao yu", "shengming ma"],
        "role_markers": ["angew. chem. int. ed."],
    },
    "F47A_MAIN": {
        "source_document_id": "F47A_MAIN",
        "source_role": "MAIN",
        "paper_id": "F47A",
        "doi_family": ["10.1021/ja005921o"],
        "title_markers": ["palladium-catalyzed asymmetric synthesis", "axially chiral allenes", "dibenzalacetone"],
        "author_markers": ["masamichi ogasawara", "hisashi ikeda", "tamio hayashi"],
        "role_markers": ["received december 26, 2000"],
    },
    "F47A_SI": {
        "source_document_id": "F47A_SI",
        "source_role": "SI",
        "paper_id": "F47A",
        "doi_family": ["10.1021/ja005921o"],
        "title_markers": ["palladium-catalyzed asymmetric synthesis", "axially chiral allenes", "dibenzalacetone"],
        "author_markers": ["masamichi ogasawara", "hisashi ikeda", "tamio hayashi"],
        "role_markers": ["general", "schlenk"],
    },
    "P403_MAIN": {
        "source_document_id": "P403_MAIN",
        "source_role": "MAIN",
        "paper_id": "P403",
        "doi_family": ["10.1021/acscatal.5c05571"],
        "title_markers": ["pd-catalyzed asymmetric allenylation", "secondary phosphine oxides", "enyne-type propargylic carbamates"],
        "author_markers": ["yujie dong", "nianci zhang", "hongchao guo"],
        "role_markers": ["acs catal. 2025"],
    },
    "P403_SI": {
        "source_document_id": "P403_SI",
        "source_role": "SI",
        "paper_id": "P403",
        "doi_family": ["10.1021/acscatal.5c05571"],
        "title_markers": ["pd-catalyzed asymmetric allenylation", "secondary phosphine oxides", "enyne-type propargylic carbamates"],
        "author_markers": ["yujie dong", "nianci zhang", "hongchao guo"],
        "role_markers": ["supporting information", "preparation of substrates"],
    },
}


def _compact(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _detected_dois(text: str) -> list[str]:
    return sorted(set(match.rstrip(".,);").casefold() for match in re.findall(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text, re.I)))


def classify_identity_text(profile: dict[str, Any], text: str) -> dict[str, Any]:
    compact = _compact(text)
    detected = _detected_dois(compact)
    expected = {doi.casefold() for doi in profile["doi_family"]}
    doi_match = bool(expected & set(detected))
    if profile["source_role"] == "MAIN" and detected and not doi_match:
        return {
            "source_document_id": profile["source_document_id"],
            "status": "IDENTITY_CONFLICT",
            "score": 0,
            "matched_evidence": [],
            "detected_dois": detected,
            "expected_doi_family": sorted(expected),
        }
    matched: list[str] = []
    score = 0
    if doi_match:
        score += 5
        matched.append("doi_match")
    title_hits = [marker for marker in profile["title_markers"] if _compact(marker) in compact]
    if len(title_hits) >= 2:
        score += 4
        matched.append("title_match")
    elif title_hits:
        score += 2
        matched.append("title_partial")
    author_hits = [marker for marker in profile["author_markers"] if _compact(marker) in compact]
    if len(author_hits) >= 2:
        score += 2
        matched.append("author_match")
    elif author_hits:
        score += 1
        matched.append("author_partial")
    if any(_compact(marker) in compact for marker in profile["role_markers"]):
        score += 1
        matched.append("role_match")
    status = "IDENTITY_VALIDATED_STRONG" if score >= 7 else "IDENTITY_VALIDATED_PROBABLE" if score >= 4 else "IDENTITY_INSUFFICIENT"
    return {
        "source_document_id": profile["source_document_id"],
        "status": status,
        "score": score,
        "matched_evidence": matched,
        "detected_dois": detected,
        "expected_doi_family": sorted(expected),
    }


def audit_source_file(path: Path, profile: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required in the existing Phase 8 environment") from exc
    document = fitz.open(path)
    pages = [document[index].get_text("text") or "" for index in range(len(document))]
    identity_text = "\n".join(pages[: min(5, len(pages))])
    audit = classify_identity_text(profile, identity_text)
    audit.update(
        {
            "paper_id": profile["paper_id"],
            "source_role": profile["source_role"],
            "sha256": sha256_file(path),
            "file_size": path.stat().st_size,
            "page_count": len(document),
        }
    )
    return audit, pages


def run_identity_audit(evidence_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    audits: dict[str, dict[str, Any]] = {}
    pages: dict[str, list[str]] = {}
    for source_id, profile in IDENTITY_PROFILES.items():
        path = evidence_root / "sources" / profile["paper_id"] / f"{source_id}.pdf"
        if not path.is_file():
            audits[source_id] = {
                "source_document_id": source_id,
                "paper_id": profile["paper_id"],
                "source_role": profile["source_role"],
                "status": "IDENTITY_INSUFFICIENT",
                "score": 0,
                "matched_evidence": [],
                "detected_dois": [],
                "expected_doi_family": profile["doi_family"],
                "sha256": None,
                "file_size": None,
                "page_count": None,
            }
            pages[source_id] = []
            continue
        audits[source_id], pages[source_id] = audit_source_file(path, profile)
    return audits, pages


def _is_placeholder_candidate(value: Any) -> bool:
    compact = _compact(value)
    return not compact or str(value).strip().upper() in SENTINEL_CANDIDATES or "requires human source check" in compact or ("candidate for" in compact and "requires" in compact)


def _fact_type(field_name: str) -> str:
    field = _compact(field_name)
    mapping = {
        "failed substrates": "negative_scope",
        "failed or low-performing substrates": "negative_scope",
        "limitations": "limitation",
        "mechanism claims": "mechanism_claim",
        "mechanistic experiments": "mechanistic_experiment",
        "control experiments": "control_experiment",
        "figures/schemes/tables": "visual_evidence",
        "supporting schemes/tables/figures": "visual_evidence",
        "si identity/status": "source_identity_status",
    }
    return mapping.get(field, field.replace(" ", "_"))


def _reaction_stage(fact_type: str) -> str:
    if fact_type == "source_identity_status":
        return "source_identity"
    if fact_type == "mechanism_claim":
        return "author_proposed_mechanism"
    if fact_type in {"mechanistic_experiment", "control_experiment"}:
        return "experimental_mechanism_evidence"
    if fact_type == "visual_evidence":
        return "source_visual_evidence"
    if fact_type in {"negative_scope", "limitation"}:
        return "target_catalytic_reaction_scope"
    return "target_catalytic_reaction"


def _locator_quality(locator: dict[str, Any], pages: list[str]) -> tuple[str, dict[str, Any], bool]:
    source_id = locator.get("source_document_id")
    if not pages:
        return "UNAVAILABLE", {"source_document_id": source_id}, False
    page_index = locator.get("pdf_page_index")
    if not isinstance(page_index, int) or page_index < 0 or page_index >= len(pages):
        return "SOURCE_ONLY", {"source_document_id": source_id, "search_instruction": "Search the full source independently."}, False
    page_text = _compact(pages[page_index])
    quote = _compact(locator.get("short_quote"))
    section = _compact(locator.get("section_heading"))
    precise_keys = ("compound_label", "entry_id", "table_id", "scheme_id", "figure_id")
    precise = {key: locator.get(key) for key in precise_keys if locator.get(key)}
    quote_match = bool(quote and quote in page_text)
    labels_match = all(_compact(value) in page_text for value in precise.values())
    base = {
        "source_document_id": source_id,
        "pdf_page_index": page_index,
        "printed_page_label": locator.get("printed_page_label"),
    }
    if quote_match and labels_match:
        return "EXACT_VERIFIED", {**base, "section": locator.get("section_heading"), **precise}, True
    window = [max(0, page_index - 1), min(len(pages) - 1, page_index + 1)]
    if section and section in page_text:
        return "SECTION_WINDOW", {"source_document_id": source_id, "section": locator.get("section_heading"), "page_window": window, "search_instruction": "Search within this section window; labels are not pre-verified."}, False
    return "PAGE_WINDOW", {"source_document_id": source_id, "page_window": window, "search_instruction": "Search this page window independently; labels are not pre-verified."}, False


def _evidence_target(fact_type: str, entity: str) -> str:
    descriptions = {
        "source_identity_status": "one source-identity determination",
        "negative_scope": "one explicit negative reaction-scope outcome",
        "limitation": "one explicit target-reaction limitation",
        "mechanism_claim": "one author-proposed mechanistic statement",
        "mechanistic_experiment": "one experimentally demonstrated mechanistic observation",
        "control_experiment": "one control-experiment observation",
        "visual_evidence": "one source figure, scheme, or table fact",
    }
    return f"{descriptions.get(fact_type, f'one directly reported {fact_type} fact')} for {entity}"


def _atomic(task: dict[str, Any]) -> bool:
    scalar_fields = ("entity", "reaction_stage", "fact_type", "evidence_target")
    if any(not isinstance(task.get(field), str) or not task[field].strip() for field in scalar_fields):
        return False
    if task["fact_type"] in {"yield_vs_conversion", "ee_er_dr", "substrate_vs_product"}:
        return False
    return True


def _hidden_calibration(human_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in human_events:
        if event.get("final_decision") != "edit":
            continue
        classification = str(event.get("classification") or "")
        if "substrate_preparation_yield" in classification:
            locator = event.get("source_locator") or {}
            classification_parts = [part.strip() for part in classification.split("/", maxsplit=1)]
            value_match = re.search(r"\b\d+(?:\.\d+)?\s*%", str(event.get("edited_value") or ""))
            return {
                "review_item_id": event.get("core_review_item_id") or event.get("review_item_id"),
                "source_document_id": locator.get("source_document_id"),
                "printed_page_label": locator.get("printed_page_label"),
                "compound_label": locator.get("compound_label"),
                "value": value_match.group(0).replace(" ", "") if value_match else event.get("edited_value"),
                "fact_type": classification_parts[0],
                "reaction_stage": classification_parts[1] if len(classification_parts) == 2 else None,
                "consumes_additional_human_budget": False,
                "visibility": "COORDINATOR_PRIVATE_POST_HOC_ONLY",
            }
    return None


def build_v2_semantic_state(
    *,
    core_items: list[dict[str, Any]],
    human_events: list[dict[str, Any]],
    source_pages: dict[str, list[str]],
    identity_audits: dict[str, dict[str, Any]],
    random_seed: int,
) -> dict[str, Any]:
    effective_human_ids = {
        event.get("core_review_item_id") or event.get("review_item_id")
        for event in human_events
        if event.get("final_decision") != "defer" and (event.get("core_review_item_id") or event.get("review_item_id"))
    }
    exclusions: list[dict[str, Any]] = []
    active_items: list[dict[str, Any]] = []
    for item in core_items:
        item_id = item["review_item_id"]
        source_id = item.get("source_locator", {}).get("source_document_id")
        if item_id in effective_human_ids:
            exclusions.append({"review_item_id": item_id, "reason": "effective_human_decision", "status": "HUMAN_DECISION_PRECEDENCE"})
        elif item.get("field_name") == "phase7_claim":
            exclusions.append({"review_item_id": item_id, "reason": "phase7_source_unavailable", "status": "NOT_ADJUDICATED_SOURCE_UNAVAILABLE"})
        elif source_id == "F3I_SI":
            exclusions.append({"review_item_id": item_id, "reason": "f3i_no_si_status", "status": "SOURCE_STATUS_NO_SI_PUBLISHED"})
        else:
            active_items.append(item)
    active_tasks: list[dict[str, Any]] = []
    for item in active_items:
        locator = item.get("source_locator", {})
        source_id = locator.get("source_document_id")
        fact_type = _fact_type(item.get("field_name", ""))
        quality, hint, exact_verified = _locator_quality(locator, source_pages.get(source_id, []))
        candidate = item.get("candidate_value")
        mode = "BLIND_DUAL_EXTRACTION" if _is_placeholder_candidate(candidate) else "CANDIDATE_VERIFICATION"
        precise_entity = next((locator.get(key) for key in ("entry_id", "compound_label", "table_id", "scheme_id", "figure_id") if locator.get(key)), None)
        entity = str(precise_entity) if exact_verified and precise_entity else source_id if fact_type == "source_identity_status" else "document_level"
        task = {
            "review_item_id": item["review_item_id"],
            "source_document_id": source_id,
            "task_mode": mode,
            "fact_type": fact_type,
            "entity": entity,
            "reaction_stage": _reaction_stage(fact_type),
            "evidence_target": _evidence_target(fact_type, entity),
            "locator_quality": quality,
            "locator_hint": hint,
            "exact_locator_verified": exact_verified,
            "candidate_claim": candidate if mode == "CANDIDATE_VERIFICATION" else None,
        }
        task["candidate_fact_matches"] = mode != "CANDIDATE_VERIFICATION" or (
            fact_type == "source_identity_status" and str(candidate).strip() in {"SI_VALIDATED", "SOURCE_FOUND"}
        ) or _compact(item.get("field_name")) in _compact(candidate)
        task["atomic"] = _atomic(task)
        active_tasks.append(task)
    exclusion_counts = dict(Counter(row["reason"] for row in exclusions))
    mode_counts = dict(Counter(row["task_mode"] for row in active_tasks))
    active_source_ids = {task["source_document_id"] for task in active_tasks}
    gates = {
        "active_task_count_is_41": len(active_tasks) == 41,
        "no_source_identity_conflicts": all(identity_audits.get(source_id, {}).get("status") in {"IDENTITY_VALIDATED_STRONG", "IDENTITY_VALIDATED_PROBABLE"} for source_id in active_source_ids),
        "no_unavailable_source_ids": all(source_id in source_pages and bool(source_pages[source_id]) for source_id in active_source_ids),
        "no_sentinel_candidates": all(task["candidate_claim"] is None or not _is_placeholder_candidate(task["candidate_claim"]) for task in active_tasks),
        "no_existing_human_decided_item": not any(task["review_item_id"] in effective_human_ids for task in active_tasks),
        "all_task_modes_valid": all(task["task_mode"] in VALID_TASK_MODES for task in active_tasks),
        "all_exact_locators_verified": all(task["locator_quality"] != "EXACT_VERIFIED" or task["exact_locator_verified"] for task in active_tasks),
        "all_tasks_atomic": all(task["atomic"] for task in active_tasks),
        "fact_type_matches_candidate": all(task["candidate_fact_matches"] for task in active_tasks),
        "reaction_stage_explicit": all(bool(task["reaction_stage"]) for task in active_tasks),
    }
    preflight = {"status": "PASS" if all(gates.values()) else "FAIL", "gates": gates}
    return {
        "schema_version": "2.0",
        "random_seed": random_seed,
        "active_tasks": active_tasks,
        "exclusions": exclusions,
        "exclusion_counts": exclusion_counts,
        "mode_counts": mode_counts,
        "locator_quality_counts": dict(Counter(task["locator_quality"] for task in active_tasks)),
        "hidden_calibration": _hidden_calibration(human_events),
        "preflight": preflight,
    }


def _blind_id(run_id: str, index: int, random_seed: int) -> str:
    digest = hashlib.sha256(f"v2\0{run_id}\0{random_seed}\0{index}".encode()).hexdigest()[:16]
    return f"BT-{digest}"


def _layer1_projection(task: dict[str, Any], blind_id: str) -> dict[str, Any]:
    return {
        "blind_task_id": blind_id,
        "task_mode": task["task_mode"],
        "source_document_id": task["source_document_id"],
        "fact_type": task["fact_type"],
        "entity": task["entity"],
        "reaction_stage": task["reaction_stage"],
        "evidence_target": task["evidence_target"],
        "locator_quality": task["locator_quality"],
        "locator_hint": task["locator_hint"],
    }


def _layer2_projection(task: dict[str, Any], blind_id: str) -> dict[str, Any]:
    row = _layer1_projection(task, blind_id)
    if task["task_mode"] == "CANDIDATE_VERIFICATION":
        row["candidate_claim"] = task["candidate_claim"]
    return row


def _prepare_workspace(workspace: Path, role: str, tasks: list[dict[str, Any]], sources: list[tuple[str, Path]]) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=False)
    for directory in ("schemas", "sources", "input", "output"):
        (workspace / directory).mkdir()
    atomic_write_text(workspace / "AGENTS.md", (_template_root() / f"{role}_v2_AGENTS.md").read_text(encoding="utf-8"))
    atomic_write_text(workspace / "WORK_ORDER.md", (_template_root() / f"{role}_v2_WORK_ORDER.md").read_text(encoding="utf-8"))
    atomic_write_jsonl(workspace / "input/tasks.jsonl", tasks)
    shutil.copy2(_template_root() / "finalize_output.py", workspace / "input/finalize_output.py")
    schema_name = f"{role}_v2_output.schema.json"
    shutil.copy2(_schema_root() / schema_name, workspace / "schemas" / schema_name)
    source_hashes = {}
    for source_id, source in sources:
        destination = workspace / "sources" / f"{source_id}.pdf"
        _copy_reflink(source, destination)
        source_hashes[destination.name] = sha256_file(destination)
    manifest = _build_input_manifest(workspace, f"{role}_v2")
    atomic_write_json(workspace / "INPUT_MANIFEST.json", manifest)
    manifest_hash = sha256_file(workspace / "INPUT_MANIFEST.json")
    atomic_write_text(workspace / "INPUT_MANIFEST.sha256", f"{manifest_hash}  INPUT_MANIFEST.json\n")
    _make_read_only(workspace)
    return {"manifest_hash": manifest_hash, "source_hashes": source_hashes}


def validate_v2_workspace(workspace: Path, role: str, *, repo_root: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    issues: list[str] = []
    if role not in {"layer1", "layer2"}:
        raise ValueError("role must be layer1 or layer2")
    if _is_within(workspace, repo_root.resolve()):
        issues.append("workspace must be outside the Git repository")
    if (workspace / ".git").exists():
        issues.append("workspace contains .git")
    for path in workspace.rglob("*"):
        if path.is_symlink():
            issues.append(f"symlink is forbidden: {path.relative_to(workspace)}")
    manifest = verify_manifest(workspace)
    issues.extend(manifest["issues"])
    for relative in ("AGENTS.md", "WORK_ORDER.md", "INPUT_MANIFEST.json", "INPUT_MANIFEST.sha256"):
        path = workspace / relative
        if not path.is_file() or path.stat().st_mode & stat.S_IWUSR:
            issues.append(f"required root input is missing or writable: {relative}")
    output = workspace / "output"
    if not output.is_dir() or not output.stat().st_mode & stat.S_IWUSR:
        issues.append("output directory is not owner-writable")
    for directory in ("sources", "input", "schemas"):
        for path in (workspace / directory).rglob("*"):
            if path.is_file() and path.stat().st_mode & stat.S_IWUSR:
                issues.append(f"input file is writable: {path.relative_to(workspace)}")
    tasks_path = workspace / "input/tasks.jsonl"
    tasks = [json.loads(line) for line in tasks_path.read_text(encoding="utf-8").splitlines() if line.strip()] if tasks_path.is_file() else []
    if len(tasks) != 41:
        issues.append(f"active task count is {len(tasks)}, expected 41")
    ids = [row.get("blind_task_id") for row in tasks]
    if len(ids) != len(set(ids)) or any(not isinstance(item, str) or not re.fullmatch(r"BT-[0-9a-f]{16}", item) for item in ids):
        issues.append("blind task IDs are invalid or duplicated")
    precise_keys = {"compound_label", "entry_id", "table_id", "scheme_id", "figure_id"}
    for index, row in enumerate(tasks):
        if row.get("task_mode") not in VALID_TASK_MODES:
            issues.append(f"row {index} has invalid task mode")
        if row.get("locator_quality") not in VALID_LOCATOR_QUALITIES:
            issues.append(f"row {index} has invalid locator quality")
        if row.get("locator_quality") != "EXACT_VERIFIED" and precise_keys & set(row.get("locator_hint", {})):
            issues.append(f"row {index} leaks unverified precise locator labels")
        if role == "layer1" and "candidate_claim" in row:
            issues.append(f"row {index} leaks a candidate into blind extraction")
        if role == "layer2" and row.get("task_mode") == "BLIND_DUAL_EXTRACTION" and "candidate_claim" in row:
            issues.append(f"row {index} leaks a sentinel/placeholder candidate into dual extraction")
    forbidden = ("human_review_required", "reviewer_1", "final_decision", "hidden_calibration", "substrate preparation yield", "layer3", "phase7_generated_section")
    for path in workspace.rglob("*"):
        if not path.is_file() or path.suffix.lower() == ".pdf":
            continue
        text = path.read_text(encoding="utf-8", errors="replace").casefold()
        for term in forbidden:
            if term in text:
                issues.append(f"forbidden V2 context leaked in {path.relative_to(workspace)}: {term}")
        if str(repo_root.resolve()).casefold() in text or re.search(r"(?:^|[\s\"'])/(?:home|users|mnt)/", text):
            issues.append(f"absolute path leaked in {path.relative_to(workspace)}")
    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": sorted(set(issues)),
        "task_count": len(tasks),
        "manifest_hash": manifest.get("manifest_hash"),
    }


def prepare_v2_workspaces(
    *,
    repo_root: Path,
    evidence_root: Path,
    workspace_parent: Path,
    run_id: str,
    semantic_state: dict[str, Any],
    identity_audits: dict[str, dict[str, Any]],
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
    if not V2_RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid V2 run ID")
    if semantic_state.get("preflight", {}).get("status") != "PASS":
        raise ValueError("semantic hard gates must pass before workspace creation")
    run_root = workspace_parent / run_id
    saved = run_root / "coordinator/preparation_result.json"
    if run_root.exists():
        if not saved.is_file():
            raise FileExistsError("V2 run exists without resume state")
        result = read_json(saved)
        for role, key in (("layer1", "layer1_workspace"), ("layer2", "layer2_workspace")):
            if validate_v2_workspace(Path(result[key]), role, repo_root=repo_root)["status"] != "PASS":
                raise ValueError(f"existing V2 {role} workspace is invalid")
        return result
    temporary_root = workspace_parent / f".{run_id}.tmp-{os.getpid()}"
    if temporary_root.exists():
        raise FileExistsError(f"temporary V2 run already exists: {temporary_root}")
    active_tasks = semantic_state["active_tasks"]
    public1 = []
    public2 = []
    private_mapping = {}
    for index, task in enumerate(active_tasks):
        blind_id = _blind_id(run_id, index, random_seed)
        public1.append(_layer1_projection(task, blind_id))
        public2.append(_layer2_projection(task, blind_id))
        private_mapping[blind_id] = {"review_item_id": task["review_item_id"]}
    source_ids = sorted({task["source_document_id"] for task in active_tasks})
    sources = []
    for source_id in source_ids:
        audit = identity_audits.get(source_id, {})
        if audit.get("status") not in {"IDENTITY_VALIDATED_STRONG", "IDENTITY_VALIDATED_PROBABLE"}:
            raise ValueError(f"source identity gate failed: {source_id}")
        profile = IDENTITY_PROFILES[source_id]
        path = evidence_root / "sources" / profile["paper_id"] / f"{source_id}.pdf"
        if not path.is_file() or sha256_file(path) != audit.get("sha256"):
            raise ValueError(f"source file/hash gate failed: {source_id}")
        sources.append((source_id, path))
    temporary_root.mkdir(parents=True)
    coordinator = temporary_root / "coordinator"
    coordinator.mkdir()
    atomic_write_json(coordinator / "private_task_mapping.json", private_mapping)
    atomic_write_json(coordinator / "private_hidden_calibration.json", semantic_state["hidden_calibration"])
    atomic_write_json(coordinator / "source_identity_audit.json", {"items": [identity_audits[source_id] for source_id in source_ids]})
    atomic_write_json(coordinator / "semantic_preflight.json", semantic_state["preflight"])
    atomic_write_json(coordinator / "exclusions.json", {"items": semantic_state["exclusions"]})
    temporary_layer1 = temporary_root / "layer1_extractor"
    temporary_layer2 = temporary_root / "layer2_verifier"
    state1 = _prepare_workspace(temporary_layer1, "layer1", public1, sources)
    state2 = _prepare_workspace(temporary_layer2, "layer2", public2, sources)
    report1 = validate_v2_workspace(temporary_layer1, "layer1", repo_root=repo_root)
    report2 = validate_v2_workspace(temporary_layer2, "layer2", repo_root=repo_root)
    if report1["status"] != "PASS" or report2["status"] != "PASS":
        raise ValueError("V2 cross-layer/package validation failed")
    if state1["source_hashes"] != state2["source_hashes"]:
        raise ValueError("V2 A/B source hashes differ")
    run_manifest = {
        "schema_version": "2.0",
        "run_id": run_id,
        "stage": "PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2_V2",
        "repo_head": repo_head,
        "branch": branch,
        "pr_number": pr_number,
        "random_seed": random_seed,
        "active_task_count": len(active_tasks),
        "mode_counts": semantic_state["mode_counts"],
        "locator_quality_counts": semantic_state["locator_quality_counts"],
        "layer1_input_manifest_hash": state1["manifest_hash"],
        "layer2_input_manifest_hash": state2["manifest_hash"],
        "source_hashes": state1["source_hashes"],
        "hidden_calibration_private": True,
        "layer3_created": False,
        "phase8b_started": False,
    }
    atomic_write_json(coordinator / "run_manifest.json", run_manifest)
    final_layer1 = run_root / "layer1_extractor"
    final_layer2 = run_root / "layer2_verifier"
    resume = f"""# Phase 8 V2 Coordinator Resume

- run ID: `{run_id}`
- checkpoint: `PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2_V2`
- active tasks: `{len(active_tasks)}`
- candidate verification: `{semantic_state['mode_counts'].get('CANDIDATE_VERIFICATION', 0)}`
- blind dual extraction: `{semantic_state['mode_counts'].get('BLIND_DUAL_EXTRACTION', 0)}`
- Layer 1 workspace: `{final_layer1}`
- Layer 2 workspace: `{final_layer2}`
- Layer 3: not created
- hidden calibration: coordinator-private, not passed to either layer
- Phase 8B: not started
"""
    atomic_write_text(coordinator / "COORDINATOR_RESUME.md", resume)
    result = {
        "run_id": run_id,
        "run_root": str(run_root),
        "layer1_workspace": str(final_layer1),
        "layer2_workspace": str(final_layer2),
        "layer1_manifest_hash": state1["manifest_hash"],
        "layer2_manifest_hash": state2["manifest_hash"],
        "active_task_count": len(active_tasks),
        "mode_counts": semantic_state["mode_counts"],
        "locator_quality_counts": semantic_state["locator_quality_counts"],
        "stage": "PREPARED_FOR_INDEPENDENT_LAYER_1_AND_2_V2",
    }
    atomic_write_json(coordinator / "preparation_result.json", result)
    os.replace(temporary_root, run_root)
    return result
