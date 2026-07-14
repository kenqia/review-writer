from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .ai_adjudication import _is_within, atomic_write_json, atomic_write_jsonl, atomic_write_text, sha256_file


CLOSURE_RUN_ID_RE = re.compile(r"^phase8a_closure_v3_1_1_\d{8}T\d{6}Z$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
EXPECTED_CLAIM_COUNT = 44
EXPECTED_SPOT_CHECK_COUNT = 4
METHOD_LABEL = "HUMAN_SPOT_CHECKED_AI_ADJUDICATION"
SPOT_CHECK_IDS = (
    "CL-SU-eb42b7e36b700462-004",
    "CL-SU-df53ec3ac051d023-004",
    "CL-SU-6a771b839d148d00-003",
    "CL-SU-eb42b7e36b700462-001",
)
SELECTED_DECISIONS = {
    SPOT_CHECK_IDS[0]: "删除 DBA-specific 条件后保留",
    SPOT_CHECK_IDS[1]: "确认 conflict 真实并保留",
    SPOT_CHECK_IDS[2]: "采用 Layer B entity 修正",
    SPOT_CHECK_IDS[3]: "确认无问题",
}
EXPECTED_INITIAL_DISPOSITIONS = {
    "AI_SUPPORTED": 29,
    "AI_CORRECTED_LOCATOR": 4,
    "AI_CORRECTED_REACTION_STAGE": 2,
    "AI_CORRECTED_ENTITY_PENDING_SPOT_CHECK": 1,
    "SOURCE_CONFLICT_RETAINED": 7,
    "HUMAN_REVIEW_REQUIRED": 1,
}
EXPECTED_FINAL_DISPOSITIONS = {
    "AI_SUPPORTED": 29,
    "AI_CORRECTED_LOCATOR": 4,
    "AI_CORRECTED_REACTION_STAGE": 2,
    "AI_CORRECTED_ENTITY": 1,
    "HUMAN_SPOT_CHECKED_CORRECTED_ACCEPT": 1,
    "SOURCE_CONFLICT_RETAINED": 7,
}
FORBIDDEN_OUTPUT_TOKENS = (
    "human_verified",
    "fully_verified",
    "scientifically_verified",
    "publication-grade",
)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _file_tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _verify_hash_manifest(root: Path, expected_manifest_sha256: str) -> dict[str, str]:
    manifest_path = root / "HASH_MANIFEST.sha256"
    if not manifest_path.is_file() or sha256_file(manifest_path) != expected_manifest_sha256:
        raise ValueError("frozen reconciliation hash manifest mismatch")
    checksums = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", maxsplit=1)
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"frozen reconciliation artifact hash mismatch: {relative}")
        checksums[relative] = digest
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if set(checksums) != actual:
        raise ValueError("frozen reconciliation hash manifest coverage mismatch")
    return checksums


def _verify_frozen_hashes(
    *,
    layer_a_workspace: Path,
    layer_b_workspace: Path,
    expected_layer_a_results_sha256: str,
    expected_layer_a_input_manifest_hash: str,
    expected_layer_b_results_sha256: str,
    expected_layer_b_output_manifest_sha256: str,
    expected_layer_b_input_manifest_hash: str,
) -> dict[str, str]:
    checks = {
        "layer_a_results_sha256": (layer_a_workspace / "output/results.jsonl", expected_layer_a_results_sha256),
        "layer_a_input_manifest_hash": (layer_a_workspace / "INPUT_MANIFEST.json", expected_layer_a_input_manifest_hash),
        "layer_b_results_sha256": (layer_b_workspace / "output/results.jsonl", expected_layer_b_results_sha256),
        "layer_b_output_manifest_sha256": (layer_b_workspace / "output/OUTPUT_MANIFEST.json", expected_layer_b_output_manifest_sha256),
        "layer_b_input_manifest_hash": (layer_b_workspace / "INPUT_MANIFEST.json", expected_layer_b_input_manifest_hash),
    }
    verified = {}
    for field, (path, expected) in checks.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"frozen input hash mismatch: {field}")
        verified[field] = expected
    return verified


def _validate_response(
    template: dict[str, Any],
    queue: list[dict[str, Any]],
    response: dict[str, Any],
) -> None:
    if set(template) != {"schema_version", "human_decisions_recorded", "items"}:
        raise ValueError("frozen human response template has an unexpected shape")
    if template.get("human_decisions_recorded") is not False:
        raise ValueError("frozen human response template is not blank")
    template_items = template.get("items")
    response_items = response.get("items")
    if not isinstance(template_items, list) or not isinstance(response_items, list):
        raise ValueError("human response items must be arrays")
    if len(template_items) != EXPECTED_SPOT_CHECK_COUNT or len(response_items) != EXPECTED_SPOT_CHECK_COUNT:
        raise ValueError("human response must contain exactly four items")
    if response.get("human_decisions_recorded") is not True:
        raise ValueError("confirmed human response must declare recorded decisions")
    template_ids = [row.get("claim_id") for row in template_items]
    queue_ids = [row.get("claim_id") for row in queue]
    response_ids = [row.get("claim_id") for row in response_items]
    if template_ids != list(SPOT_CHECK_IDS) or response_ids != template_ids or queue_ids != template_ids:
        raise ValueError("template, queue, and confirmed response claim IDs/order differ")
    for template_row, queue_row, response_row in zip(template_items, queue, response_items):
        if set(template_row) != {"claim_id", "selected_decision", "reviewer_note"}:
            raise ValueError("human response template item has an unexpected shape")
        if template_row["selected_decision"] is not None or template_row["reviewer_note"] is not None:
            raise ValueError("frozen human response template item is not blank")
        if set(response_row) != {"claim_id", "selected_decision", "reviewer_note"}:
            raise ValueError("confirmed human response item has an unexpected shape")
        selected = response_row.get("selected_decision")
        if selected not in queue_row.get("user_options", []):
            raise ValueError(f"selected decision is not a frozen queue option: {response_row.get('claim_id')}")
        if selected != SELECTED_DECISIONS[response_row["claim_id"]]:
            raise ValueError(f"confirmed decision does not match the user instruction: {response_row['claim_id']}")
        note = response_row.get("reviewer_note")
        if note is not None and (not isinstance(note, str) or len(note) > 500):
            raise ValueError("reviewer note must be null or a short string")
    folded = json.dumps(response, ensure_ascii=False).casefold()
    if "chain_of_thought" in folded or '"reasoning"' in folded:
        raise ValueError("hidden reasoning fields are forbidden in human responses")


def _remove_phrase(value: str | None, pattern: str) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(pattern, "", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,")
    return cleaned


def _apply_dba_correction(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    claim = copy.deepcopy(record["layer_a_claim"])
    if claim.get("value_as_reported") != 76 or claim.get("unit_as_reported") != "%":
        raise ValueError("DBA correction target no longer has the frozen 76% value")
    if claim.get("intermediate_id") != "complex 5" or claim.get("product_id") != "allene 3an":
        raise ValueError("DBA correction target entity binding changed")
    if "sodium salt of 2n" not in claim.get("substrate_ids", []):
        raise ValueError("DBA correction target substrate binding changed")

    before = copy.deepcopy(claim)
    conditions = claim.get("conditions_as_reported")
    if not isinstance(conditions, str):
        raise ValueError("DBA correction target lacks structured conditions")
    segments = [segment.strip() for segment in conditions.split(",")]
    kept = [segment for segment in segments if not re.search(r"\b(?:DBA|dibenzalacetone)\b", segment, re.IGNORECASE)]
    if len(kept) == len(segments):
        raise ValueError("DBA-specific condition was not present")
    claim["conditions_as_reported"] = ", ".join(kept)

    partners = claim.get("reagent_or_partner_ids")
    if not isinstance(partners, list):
        raise ValueError("DBA correction target reagent binding is malformed")
    claim["reagent_or_partner_ids"] = [
        value for value in partners if not re.fullmatch(r"(?:DBA|dibenzalacetone)", value, re.IGNORECASE)
    ]
    locator = claim.get("evidence_locator")
    if not isinstance(locator, dict):
        raise ValueError("DBA correction target locator is malformed")
    locator["entry_id"] = _remove_phrase(locator.get("entry_id"), r"\s+(?:with|in the presence of)\s+(?:DBA|dibenzalacetone)\b")
    claim["reaction_entry"] = _remove_phrase(
        claim.get("reaction_entry"),
        r"\s+(?:with|in the presence of)\s+(?:DBA|dibenzalacetone)\b",
    )
    claim["short_evidence"] = _remove_phrase(
        claim.get("short_evidence"),
        r"\s+in the presence of\s+(?:DBA|dibenzalacetone)\b",
    )
    claim["reaction_stage"] = "target_stoichiometric_reaction"
    serialized = json.dumps(claim, ensure_ascii=False).casefold()
    if re.search(r"\bdba\b|\bdibenzalacetone\b", serialized):
        raise ValueError("DBA-specific binding remains after correction")

    changed_fields = []
    for field in ("conditions_as_reported", "reaction_stage", "reagent_or_partner_ids", "short_evidence"):
        if claim[field] != before[field]:
            changed_fields.append(field)
    if claim["evidence_locator"]["entry_id"] != before["evidence_locator"]["entry_id"]:
        changed_fields.append("evidence_locator.entry_id")
    changed_fields.sort()
    application = {
        "claim_id": claim["claim_id"],
        "selected_decision": SELECTED_DECISIONS[claim["claim_id"]],
        "changed_fields": changed_fields,
        "checked_unchanged_fields": ["reaction_entry"] if claim["reaction_entry"] == before["reaction_entry"] else [],
        "removed_dba_specific_bindings": {
            "conditions_as_reported": {"before": before["conditions_as_reported"], "after": claim["conditions_as_reported"]},
            "reagent_or_partner_ids": {"before": before["reagent_or_partner_ids"], "after": claim["reagent_or_partner_ids"]},
            "evidence_locator.entry_id": {
                "before": before["evidence_locator"]["entry_id"],
                "after": claim["evidence_locator"]["entry_id"],
            },
            "short_evidence": {"before": before["short_evidence"], "after": claim["short_evidence"]},
        },
        "preserved_value": {"value_as_reported": 76, "unit_as_reported": "%"},
    }
    return claim, application


def _build_decisions(
    *,
    queue: list[dict[str, Any]],
    response: dict[str, Any],
    decision_time_utc: str,
    reconciliation_run_id: str,
    reconciliation_manifest_sha256: str,
    queue_sha256: str,
) -> list[dict[str, Any]]:
    decisions = []
    for sequence, (queue_row, response_row) in enumerate(zip(queue, response["items"]), start=1):
        payload = {
            "schema_version": "3.1.1-human-spot-check-decision",
            "sequence_number": sequence,
            "claim_id": response_row["claim_id"],
            "spot_check_item_hash": _canonical_hash(queue_row),
            "spot_check_queue_sha256": queue_sha256,
            "selected_decision": response_row["selected_decision"],
            "reviewer_note": response_row["reviewer_note"],
            "decision_time_utc": decision_time_utc,
            "reconciliation_run_id": reconciliation_run_id,
            "reconciliation_manifest_sha256": reconciliation_manifest_sha256,
            "reviewer_id": "user",
            "review_mode": "direct_user_confirmation",
            "method_label": METHOD_LABEL,
            "consumes_human_budget": True,
        }
        decisions.append({**payload, "decision_id": f"HD-{_canonical_hash(payload)[:16]}"})
    return decisions


def _apply_decisions(
    reconciliation_rows: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    initial = Counter(row.get("final_disposition") for row in reconciliation_rows)
    if dict(initial) != EXPECTED_INITIAL_DISPOSITIONS:
        raise ValueError("frozen reconciliation disposition distribution changed")
    by_decision = {row["claim_id"]: row for row in decisions}
    final_rows = []
    applications = []
    for record in reconciliation_rows:
        claim_id = record["claim_id"]
        final_claim = copy.deepcopy(record.get("reconciled_claim"))
        disposition = record["final_disposition"]
        spot_status = None
        decision_id = None
        decision = by_decision.get(claim_id)
        if decision:
            decision_id = decision["decision_id"]
            if claim_id == SPOT_CHECK_IDS[0]:
                final_claim, application = _apply_dba_correction(record)
                disposition = "HUMAN_SPOT_CHECKED_CORRECTED_ACCEPT"
                spot_status = "CORRECTED_ACCEPTED"
            elif claim_id == SPOT_CHECK_IDS[1]:
                if disposition != "SOURCE_CONFLICT_RETAINED" or not final_claim.get("source_conflict_detected"):
                    raise ValueError("confirmed Table S2 source conflict is no longer retained")
                if len(final_claim.get("source_conflict", {}).get("alternatives", [])) < 2:
                    raise ValueError("confirmed Table S2 source conflict lost its alternatives")
                spot_status = "CONFIRMED_SOURCE_CONFLICT_RETAINED"
                application = {
                    "claim_id": claim_id,
                    "selected_decision": decision["selected_decision"],
                    "changed_fields": [],
                    "confirmed_without_winner_selection": True,
                }
            elif claim_id == SPOT_CHECK_IDS[2]:
                if final_claim.get("substrate_ids") != ["allene-tethered hydroxyamines and hydrazines 139"]:
                    raise ValueError("confirmed entity correction differs from the Layer B correction")
                disposition = "AI_CORRECTED_ENTITY"
                spot_status = "CONFIRMED_CORRECTION"
                application = {
                    "claim_id": claim_id,
                    "selected_decision": decision["selected_decision"],
                    "changed_fields": [],
                    "confirmed_entity_binding": final_claim["substrate_ids"],
                }
            elif claim_id == SPOT_CHECK_IDS[3]:
                if disposition != "AI_SUPPORTED" or final_claim != record.get("layer_a_claim"):
                    raise ValueError("deterministically sampled supported claim changed")
                spot_status = "PASSED"
                application = {
                    "claim_id": claim_id,
                    "selected_decision": decision["selected_decision"],
                    "changed_fields": [],
                    "confirmed_without_correction": True,
                }
            else:  # pragma: no cover
                raise ValueError(f"unexpected human spot-check claim: {claim_id}")
            applications.append(application)
        if final_claim is None:
            raise ValueError(f"final claim remains unresolved: {claim_id}")
        final_rows.append(
            {
                "schema_version": "3.1.1-phase8a-final-claim",
                "claim_id": claim_id,
                "final_claim": final_claim,
                "final_claim_hash": _canonical_hash(final_claim),
                "final_disposition": disposition,
                "human_spot_check_status": spot_status,
                "human_spot_check_decision_id": decision_id,
                "source_reconciliation_record_hash": _canonical_hash(record),
                "method_label": METHOD_LABEL,
            }
        )
    if set(by_decision) != set(SPOT_CHECK_IDS) or len(applications) != EXPECTED_SPOT_CHECK_COUNT:
        raise ValueError("exactly four human decisions must be applied")
    counts = Counter(row["final_disposition"] for row in final_rows)
    if dict(counts) != EXPECTED_FINAL_DISPOSITIONS:
        raise ValueError("final disposition distribution differs from the closure contract")
    return final_rows, applications


def _write_hash_manifest(root: Path) -> None:
    paths = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "HASH_MANIFEST.sha256")
    atomic_write_text(
        root / "HASH_MANIFEST.sha256",
        "\n".join(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in paths) + "\n",
    )


def _assert_no_forbidden_output(root: Path) -> None:
    folded = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in root.rglob("*")
        if path.is_file()
    ).casefold()
    for token in FORBIDDEN_OUTPUT_TOKENS:
        if token in folded:
            raise ValueError(f"forbidden closure label present: {token}")


def prepare_phase8a_closure(
    *,
    repo_root: Path,
    output_parent: Path,
    run_id: str,
    reconciliation_run: Path,
    layer_a_workspace: Path,
    layer_b_workspace: Path,
    confirmed_response_path: Path,
    decision_time_utc: str,
    coordinator_repo_head: str,
    expected_reconciliation_manifest_sha256: str,
    expected_layer_a_results_sha256: str,
    expected_layer_a_input_manifest_hash: str,
    expected_layer_b_results_sha256: str,
    expected_layer_b_output_manifest_sha256: str,
    expected_layer_b_input_manifest_hash: str,
    previous_human_budget_used: int,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_parent = output_parent.resolve()
    reconciliation_run = reconciliation_run.resolve()
    layer_a_workspace = layer_a_workspace.resolve()
    layer_b_workspace = layer_b_workspace.resolve()
    confirmed_response_path = confirmed_response_path.resolve()
    if not CLOSURE_RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid Phase 8A closure run ID")
    if not UTC_TIMESTAMP_RE.fullmatch(decision_time_utc):
        raise ValueError("decision time must be a UTC second-resolution timestamp")
    if _is_within(output_parent, repo_root):
        raise ValueError("Phase 8A closure must be outside the Git repository")
    if previous_human_budget_used != 6:
        raise ValueError("Phase 8A closure requires exactly six previously used human decisions")

    run_root = output_parent / run_id
    if run_root.exists():
        raise FileExistsError(f"Phase 8A closure run already exists: {run_root}")
    frozen_before = {
        "reconciliation": _file_tree_hashes(reconciliation_run),
        "layer_a": _file_tree_hashes(layer_a_workspace),
        "layer_b": _file_tree_hashes(layer_b_workspace),
    }
    _verify_hash_manifest(reconciliation_run, expected_reconciliation_manifest_sha256)
    frozen_inputs = _verify_frozen_hashes(
        layer_a_workspace=layer_a_workspace,
        layer_b_workspace=layer_b_workspace,
        expected_layer_a_results_sha256=expected_layer_a_results_sha256,
        expected_layer_a_input_manifest_hash=expected_layer_a_input_manifest_hash,
        expected_layer_b_results_sha256=expected_layer_b_results_sha256,
        expected_layer_b_output_manifest_sha256=expected_layer_b_output_manifest_sha256,
        expected_layer_b_input_manifest_hash=expected_layer_b_input_manifest_hash,
    )
    source_manifest = _read_json(reconciliation_run / "coordinator/run_manifest.json")
    if (
        source_manifest.get("stage") != "PREPARED_FOR_FINAL_4_HUMAN_SPOT_CHECKS"
        or source_manifest.get("claim_count") != EXPECTED_CLAIM_COUNT
        or source_manifest.get("human_decisions_recorded") is not False
        or source_manifest.get("layer_c_created") is not False
        or source_manifest.get("phase8b_started") is not False
        or any(source_manifest.get("frozen_inputs", {}).get(field) != value for field, value in frozen_inputs.items())
    ):
        raise ValueError("frozen reconciliation run manifest is incompatible with closure")

    reconciliation_rows = _read_jsonl(reconciliation_run / "reconciliation/reconciliation.jsonl")
    queue_path = reconciliation_run / "spot_checks/spot_check_queue.jsonl"
    queue = _read_jsonl(queue_path)
    template = _read_json(reconciliation_run / "spot_checks/human_response_template.json")
    response = _read_json(confirmed_response_path)
    if len(reconciliation_rows) != EXPECTED_CLAIM_COUNT or len({row.get("claim_id") for row in reconciliation_rows}) != EXPECTED_CLAIM_COUNT:
        raise ValueError("frozen reconciliation does not contain 44 unique claims")
    _validate_response(template, queue, response)
    decisions = _build_decisions(
        queue=queue,
        response=response,
        decision_time_utc=decision_time_utc,
        reconciliation_run_id=source_manifest["run_id"],
        reconciliation_manifest_sha256=expected_reconciliation_manifest_sha256,
        queue_sha256=sha256_file(queue_path),
    )
    final_rows, applications = _apply_decisions(reconciliation_rows, decisions)

    temporary = output_parent / f".{run_id}.tmp-{os.getpid()}"
    if temporary.exists():
        raise FileExistsError(f"temporary Phase 8A closure run already exists: {temporary}")
    for relative in ("final", "human_decisions", "coordinator"):
        (temporary / relative).mkdir(parents=True, exist_ok=True)
    atomic_write_jsonl(temporary / "final/final_reconciled_claims.jsonl", final_rows)
    atomic_write_jsonl(temporary / "human_decisions/human_spot_check_decisions.jsonl", decisions)
    budget = {
        "previously_used": previous_human_budget_used,
        "newly_recorded": len(decisions),
        "total_used": previous_human_budget_used + len(decisions),
        "maximum": 10,
        "remaining": 10 - previous_human_budget_used - len(decisions),
    }
    recorded_response = {
        "schema_version": "3.1.1-human-spot-check-response-recorded",
        "source_template_sha256": sha256_file(reconciliation_run / "spot_checks/human_response_template.json"),
        "human_decisions_recorded": True,
        "budget": budget,
        "items": decisions,
    }
    atomic_write_json(temporary / "human_decisions/human_response.json", recorded_response)
    application_report = {
        "schema_version": "3.1.1-human-decision-application-report",
        "status": "PASS",
        "decision_count": len(decisions),
        "applications": applications,
        "budget": budget,
        "unresolved_after_application": 0,
    }
    atomic_write_json(temporary / "human_decisions/human_decision_application_report.json", application_report)
    application_lines = [
        "# Phase 8A Human Decision Application Report",
        "",
        f"- decisions applied: `{len(decisions)}`",
        f"- budget: `{budget['total_used']}/{budget['maximum']}`",
        "- unresolved after application: `0`",
        "",
    ]
    application_lines.extend(
        f"- `{row['claim_id']}`: `{row['selected_decision']}`; changed fields: `{row['changed_fields']}`"
        for row in applications
    )
    atomic_write_text(temporary / "human_decisions/human_decision_application_report.md", "\n".join(application_lines) + "\n")

    counts = dict(Counter(row["final_disposition"] for row in final_rows))
    summary = {
        "schema_version": "3.1.1-phase8a-closure-summary",
        "status": "COMPLETE",
        "checkpoint": "PHASE8A_COMPLETE_PR3_READY_FOR_REVIEW",
        "method_label": METHOD_LABEL,
        "claim_count": len(final_rows),
        "final_disposition_counts": counts,
        "human_review_required_count": 0,
        "usable_non_conflict_claim_count": sum(row["final_disposition"] != "SOURCE_CONFLICT_RETAINED" for row in final_rows),
        "retained_source_conflict_count": sum(row["final_disposition"] == "SOURCE_CONFLICT_RETAINED" for row in final_rows),
        "human_spot_check_count": len(decisions),
        "human_budget": budget,
        "calibration_status": "PASS",
        "layer_a_row_count": 8,
        "layer_a_claim_count": 44,
        "layer_b_completed_count": 44,
        "layer_c_created": False,
        "layer_c_reason": "SKIPPED_AS_UNNECESSARY",
        "phase8b_started": False,
        "validation_scope": "engineering and internal demonstration",
        "full_human_review_claimed": False,
    }
    atomic_write_json(temporary / "final/phase8a_closure_summary.json", summary)
    summary_lines = [
        "# Phase 8A Closure Summary",
        "",
        f"- status: `{summary['status']}`",
        f"- checkpoint: `{summary['checkpoint']}`",
        f"- method label: `{METHOD_LABEL}`",
        f"- final claims: `{summary['claim_count']}`",
        f"- disposition counts: `{json.dumps(counts, ensure_ascii=False, sort_keys=True)}`",
        "- human-review-required claims: `0`",
        f"- usable non-conflict claims: `{summary['usable_non_conflict_claim_count']}`",
        f"- retained source conflicts: `{summary['retained_source_conflict_count']}`",
        f"- human budget: `{budget['total_used']}/{budget['maximum']}`",
        "- Layer C: skipped as unnecessary",
        "- Phase 8B: not started",
        "- scope: engineering validation and internal demonstration; no complete human review claim",
        "",
    ]
    atomic_write_text(temporary / "final/phase8a_closure_summary.md", "\n".join(summary_lines))

    frozen_after = {
        "reconciliation": _file_tree_hashes(reconciliation_run),
        "layer_a": _file_tree_hashes(layer_a_workspace),
        "layer_b": _file_tree_hashes(layer_b_workspace),
    }
    if frozen_after != frozen_before:
        raise RuntimeError("a frozen reconciliation, Layer A, or Layer B input changed during closure")
    result = {
        "schema_version": "3.1.1-phase8a-closure-run",
        "run_id": run_id,
        "closure_root": str(run_root),
        "stage": summary["checkpoint"],
        "coordinator_repo_head": coordinator_repo_head,
        "source_reconciliation_run_id": source_manifest["run_id"],
        "source_reconciliation_manifest_sha256": expected_reconciliation_manifest_sha256,
        "frozen_inputs": frozen_inputs,
        "frozen_file_hashes_before": frozen_before,
        "frozen_file_hashes_after": frozen_after,
        "claim_count": len(final_rows),
        "final_disposition_counts": counts,
        "human_budget": budget,
        "human_decisions_recorded": True,
        "layer_c_created": False,
        "phase8b_started": False,
    }
    atomic_write_json(temporary / "coordinator/run_manifest.json", result)
    atomic_write_text(
        temporary / "coordinator/PHASE8A_CLOSURE.md",
        "\n".join(
            [
                "# Phase 8A Closure Record",
                "",
                f"- run ID: `{run_id}`",
                f"- checkpoint: `{summary['checkpoint']}`",
                f"- final claims: `{len(final_rows)}`",
                f"- human budget: `{budget['total_used']}/{budget['maximum']}`",
                "- Layer C: skipped as unnecessary",
                "- Phase 8B: not started",
                "",
            ]
        ),
    )
    atomic_write_text(
        temporary / "coordinator/COORDINATOR_RESUME.md",
        "\n".join(
            [
                "# Phase 8A Coordinator Resume",
                "",
                f"- checkpoint: `{summary['checkpoint']}`",
                "- Phase 8A: complete",
                "- PR #3: target state Ready for Review; do not merge in this workflow",
                "- Layer C: not created",
                "- Phase 8B: not started",
                "",
            ]
        ),
    )
    _assert_no_forbidden_output(temporary)
    _write_hash_manifest(temporary)
    output_parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, run_root)
    return {**result, "hash_manifest_sha256": sha256_file(run_root / "HASH_MANIFEST.sha256")}
