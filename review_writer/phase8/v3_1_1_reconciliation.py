from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .ai_adjudication import _is_within, atomic_write_json, atomic_write_jsonl, atomic_write_text, sha256_file


RECONCILIATION_RUN_ID_RE = re.compile(r"^phase8_final_reconciliation_v3_1_1_\d{8}T\d{6}Z$")
EXPECTED_CLAIM_COUNT = 44
EXPECTED_SOURCE_CONFLICT_COUNT = 7
FIXED_SPOT_CHECK_IDS = (
    "CL-SU-eb42b7e36b700462-004",
    "CL-SU-df53ec3ac051d023-004",
    "CL-SU-6a771b839d148d00-003",
)
SPOT_CHECK_SEED = "phase8a-final-spotcheck-v1:"
ENTITY_FIELDS = {
    "substrate_ids",
    "reagent_or_partner_ids",
    "product_id",
    "intermediate_id",
    "reaction_entry",
}


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _output_tree_hashes(workspace: Path) -> dict[str, str]:
    output = workspace / "output"
    return {
        path.relative_to(workspace).as_posix(): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }


def _flatten_claims(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    flattened = []
    for row in rows:
        source_unit_id = row.get("source_unit_id")
        for claim in row.get("claims", []):
            flattened.append((source_unit_id, claim))
    return flattened


def _require_correction(
    row: dict[str, Any],
    *,
    expected_fields: set[str],
    verdict: str,
) -> dict[str, Any]:
    corrected = row.get("corrected_fields")
    if not isinstance(corrected, dict) or not corrected or set(corrected) != expected_fields:
        raise ValueError(f"{row.get('claim_id')}: {verdict} correction fields must equal {sorted(expected_fields)}")
    return corrected


def _require_no_correction(row: dict[str, Any]) -> None:
    if row.get("corrected_fields") not in (None, {}):
        raise ValueError(f"{row.get('claim_id')}: verdict cannot carry corrected fields")


def reconcile_claims(
    layer_a_rows: list[dict[str, Any]],
    layer_b_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claims = _flatten_claims(layer_a_rows)
    if len(claims) != EXPECTED_CLAIM_COUNT or len(layer_b_rows) != EXPECTED_CLAIM_COUNT:
        raise ValueError("reconciliation requires exactly 44 Layer A claims and 44 Layer B results")
    claim_ids = [claim["claim_id"] for _, claim in claims]
    if len(set(claim_ids)) != EXPECTED_CLAIM_COUNT:
        raise ValueError("Layer A claim IDs are not unique")
    b_by_claim = {row.get("claim_id"): row for row in layer_b_rows}
    if len(b_by_claim) != EXPECTED_CLAIM_COUNT or set(b_by_claim) != set(claim_ids):
        raise ValueError("Layer A claims and Layer B results are not one-to-one")

    records = []
    for source_unit_id, claim in claims:
        claim_id = claim["claim_id"]
        verification = b_by_claim[claim_id]
        claim_hash = _canonical_hash(claim)
        if verification.get("claim_hash") != claim_hash:
            raise ValueError(f"{claim_id}: Layer B result does not bind the Layer A claim hash")
        verdict = verification.get("verdict")
        reconciled = copy.deepcopy(claim)
        applied_fields: list[str] = []

        if verdict == "SUPPORTED":
            _require_no_correction(verification)
            disposition = "AI_SUPPORTED"
        elif verdict == "LOCATOR_ERROR":
            corrected = _require_correction(
                verification,
                expected_fields={"evidence_locator"},
                verdict=verdict,
            )
            if not isinstance(corrected["evidence_locator"], dict):
                raise ValueError(f"{claim_id}: corrected evidence locator must be structured")
            reconciled["evidence_locator"] = copy.deepcopy(corrected["evidence_locator"])
            applied_fields = ["evidence_locator"]
            disposition = "AI_CORRECTED_LOCATOR"
        elif verdict == "REACTION_STAGE_ERROR":
            corrected = _require_correction(
                verification,
                expected_fields={"reaction_stage"},
                verdict=verdict,
            )
            if not isinstance(corrected["reaction_stage"], str) or not corrected["reaction_stage"]:
                raise ValueError(f"{claim_id}: corrected reaction stage must be nonempty")
            reconciled["reaction_stage"] = corrected["reaction_stage"]
            applied_fields = ["reaction_stage"]
            disposition = "AI_CORRECTED_REACTION_STAGE"
        elif verdict == "ENTITY_BINDING_ERROR":
            corrected = verification.get("corrected_fields")
            if not isinstance(corrected, dict) or not corrected or not set(corrected).issubset(ENTITY_FIELDS):
                raise ValueError(f"{claim_id}: entity correction contains a missing or forbidden field")
            for field, value in corrected.items():
                reconciled[field] = copy.deepcopy(value)
            applied_fields = sorted(corrected)
            disposition = "AI_CORRECTED_ENTITY_PENDING_SPOT_CHECK"
        elif verdict == "SOURCE_CONFLICT":
            _require_no_correction(verification)
            if verification.get("source_conflict_assessment") != "FAITHFULLY_RECORDED":
                raise ValueError(f"{claim_id}: source conflict was not assessed as faithfully recorded")
            conflict = claim.get("source_conflict")
            if not claim.get("source_conflict_detected") or not isinstance(conflict, dict) or len(conflict.get("alternatives", [])) < 2:
                raise ValueError(f"{claim_id}: retained source conflict lacks structured alternatives")
            disposition = "SOURCE_CONFLICT_RETAINED"
        elif verdict == "INSUFFICIENT_EVIDENCE":
            _require_no_correction(verification)
            reconciled = None
            disposition = "HUMAN_REVIEW_REQUIRED"
        else:
            raise ValueError(f"{claim_id}: unsupported final reconciliation verdict {verdict!r}")

        records.append(
            {
                "schema_version": "3.1.1-final-reconciliation",
                "claim_id": claim_id,
                "source_unit_id": source_unit_id,
                "layer_a_claim_hash": claim_hash,
                "layer_a_claim": copy.deepcopy(claim),
                "layer_b_verification": copy.deepcopy(verification),
                "applied_correction_fields": applied_fields,
                "reconciled_claim": reconciled,
                "final_disposition": disposition,
            }
        )
    return records


def deterministic_supported_spot_claim_id(layer_b_rows: list[dict[str, Any]]) -> str:
    supported = sorted({row["claim_id"] for row in layer_b_rows if row.get("verdict") == "SUPPORTED"})
    if not supported:
        raise ValueError("no supported claim is available for deterministic spot checking")
    return min(supported, key=lambda claim_id: hashlib.sha256(f"{SPOT_CHECK_SEED}{claim_id}".encode()).hexdigest())


def _default_page_renderer(source: Path, packaged_page_index: int, destination: Path) -> None:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required to render spot-check pages") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as document:
        if packaged_page_index < 0 or packaged_page_index >= len(document):
            raise ValueError(f"packaged PDF page index is out of range: {packaged_page_index}")
        pixmap = document[packaged_page_index].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        pixmap.save(destination)


def _spot_check_spec(claim_id: str, deterministic_id: str) -> dict[str, Any]:
    if claim_id == FIXED_SPOT_CHECK_IDS[0]:
        return {
            "selection_reason": "76% yield 与 DBA-present 条件的绑定证据不足",
            "recommendation": "删除 DBA-specific 条件后保留该数值 claim",
            "reason": "Layer B 确认页面报告 76% yield，但页面只分别比较有无 DBA 的 ee，未把 76% 明确绑定到 DBA-present 变体。",
            "options": ["保留原 claim", "删除 DBA-specific 条件后保留", "unresolved/exclude"],
        }
    if claim_id == FIXED_SPOT_CHECK_IDS[1]:
        return {
            "selection_reason": "Table S2 图示与脚注存在内部标签冲突",
            "recommendation": "确认冲突真实并保留结构化 alternatives，不选择 winner",
            "reason": "Layer B 独立核对到图示 1q/3qa 与脚注 1a+2a 同页并存。",
            "options": ["确认 conflict 真实并保留", "conflict 记录需编辑", "unresolved/exclude"],
        }
    if claim_id == FIXED_SPOT_CHECK_IDS[2]:
        return {
            "selection_reason": "Layer B 提出高风险 entity binding 修正",
            "recommendation": "采用更具体的 allene-tethered hydroxyamines and hydrazines 139",
            "reason": "Layer B 认为来源把 substrates 139 明确描述为带 allene 的 hydroxyamines 和 hydrazines。",
            "options": ["采用 Layer B entity 修正", "保留 Layer A 泛称", "unresolved/exclude"],
        }
    if claim_id != deterministic_id:
        raise ValueError(f"unexpected spot-check claim: {claim_id}")
    return {
        "selection_reason": f"29 个 SUPPORTED claims 的固定种子抽样；seed={SPOT_CHECK_SEED}",
        "recommendation": "确认来源与结构化 claim 一致后保留 AI_SUPPORTED",
        "reason": "该项由固定 SHA-256 规则选出，不是人工挑选。",
        "options": ["确认无问题", "需要编辑", "unresolved/exclude"],
    }


def _write_spot_card(path: Path, row: dict[str, Any]) -> None:
    claim = row["layer_a_claim"]
    verification = row["layer_b_verification"]
    locator = row["source_locator"]
    options = "\n".join(f"- [ ] {option}" for option in row["user_options"])
    original = json.dumps(claim, ensure_ascii=False, indent=2, sort_keys=True)
    content = "\n".join(
        [
            f"# Human Spot Check: {row['claim_id']}",
            "",
            "本卡仅用于小样本人工抽查准备；尚未记录人工决定。",
            "",
            "## Layer A 原 claim",
            "",
            "```json",
            original,
            "```",
            "",
            "## Layer B 独立验证",
            "",
            f"- verdict: `{verification['verdict']}`",
            f"- independent evidence: {verification['short_independent_evidence']}",
            f"- observed locator: `{json.dumps(verification.get('observed_evidence_locator'), ensure_ascii=False, sort_keys=True)}`",
            "",
            "## 原始来源定位",
            "",
            f"- source document: `{claim['source_document_id']}`",
            f"- PDF page index: `{locator['pdf_page_index']}`",
            f"- printed page label: `{locator['printed_page_label_observed']}`",
            f"- section: `{locator.get('section')}`",
            f"- table/scheme/figure/entry: `{locator.get('table_id')}` / `{locator.get('scheme_id')}` / `{locator.get('figure_id')}` / `{locator.get('entry_id')}`",
            "",
            f"![来源页截图](../screenshots/{row['claim_id']}.png)",
            "",
            "## Coordinator 推荐",
            "",
            f"- 推荐：{row['coordinator_recommendation']}",
            f"- 理由：{row['coordinator_reason']}",
            "",
            "## 用户可选决定",
            "",
            options,
            "",
        ]
    )
    atomic_write_text(path, content)


def _write_hash_manifest(run_root: Path) -> None:
    paths = sorted(path for path in run_root.rglob("*") if path.is_file() and path.name != "HASH_MANIFEST.sha256")
    rows = [f"{sha256_file(path)}  {path.relative_to(run_root).as_posix()}" for path in paths]
    atomic_write_text(run_root / "HASH_MANIFEST.sha256", "\n".join(rows) + "\n")


def _verify_frozen_inputs(
    *,
    layer_a_workspace: Path,
    layer_b_workspace: Path,
    expected_layer_a_results_sha256: str,
    expected_layer_a_input_manifest_hash: str,
    expected_layer_b_results_sha256: str,
    expected_layer_b_output_manifest_sha256: str,
    expected_layer_b_input_manifest_hash: str,
    expected_layer_b_repo_head: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    checks = {
        layer_a_workspace / "output/results.jsonl": expected_layer_a_results_sha256,
        layer_a_workspace / "INPUT_MANIFEST.json": expected_layer_a_input_manifest_hash,
        layer_b_workspace / "output/results.jsonl": expected_layer_b_results_sha256,
        layer_b_workspace / "output/OUTPUT_MANIFEST.json": expected_layer_b_output_manifest_sha256,
        layer_b_workspace / "INPUT_MANIFEST.json": expected_layer_b_input_manifest_hash,
    }
    for path, expected in checks.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"frozen input hash mismatch: {path.name}")

    a_rows = _read_jsonl(layer_a_workspace / "output/results.jsonl")
    b_rows = _read_jsonl(layer_b_workspace / "output/results.jsonl")
    tasks = _read_jsonl(layer_b_workspace / "input/verifier_tasks.jsonl")
    b_input = _read_json(layer_b_workspace / "INPUT_MANIFEST.json")
    b_output = _read_json(layer_b_workspace / "output/OUTPUT_MANIFEST.json")
    expected_output_fields = {
        "status": "PASS",
        "package_role": "EXACT_CLAIM_VERIFICATION",
        "result_count": EXPECTED_CLAIM_COUNT,
        "source_conflict_result_count": EXPECTED_SOURCE_CONFLICT_COUNT,
        "repo_head": expected_layer_b_repo_head,
        "upstream_layer_a_results_sha256": expected_layer_a_results_sha256,
        "upstream_layer_a_input_manifest_hash": expected_layer_a_input_manifest_hash,
        "input_manifest_hash": expected_layer_b_input_manifest_hash,
        "results_sha256": expected_layer_b_results_sha256,
    }
    if any(b_output.get(field) != value for field, value in expected_output_fields.items()):
        raise ValueError("Layer B output manifest does not bind the frozen A/B inputs")
    if (
        b_input.get("repo_head") != expected_layer_b_repo_head
        or b_input.get("upstream_layer_a_results_sha256") != expected_layer_a_results_sha256
        or b_input.get("upstream_layer_a_input_manifest_hash") != expected_layer_a_input_manifest_hash
    ):
        raise ValueError("Layer B input manifest does not bind the frozen Layer A input")
    if len(tasks) != EXPECTED_CLAIM_COUNT:
        raise ValueError("Layer B verifier task package does not contain exactly 44 tasks")
    task_ids = [task.get("verifier_task_id") for task in tasks]
    if [row.get("verifier_task_id") for row in b_rows] != task_ids:
        raise ValueError("Layer B results are not in frozen verifier task order")
    task_by_claim = {task.get("claim_id"): task for task in tasks}
    if len(task_by_claim) != EXPECTED_CLAIM_COUNT:
        raise ValueError("Layer B verifier task claim IDs are not unique")
    for row in b_rows:
        task = task_by_claim.get(row.get("claim_id"))
        if task is None or any(row.get(field) != task.get(field) for field in ("verifier_task_id", "claim_hash", "task_hash")):
            raise ValueError(f"Layer B result does not bind its verifier task: {row.get('claim_id')}")
        if row.get("input_manifest_hash") != expected_layer_b_input_manifest_hash:
            raise ValueError(f"Layer B result has the wrong manifest hash: {row.get('claim_id')}")
    return a_rows, b_rows, tasks


def prepare_final_reconciliation(
    *,
    repo_root: Path,
    output_parent: Path,
    run_id: str,
    layer_a_workspace: Path,
    layer_b_workspace: Path,
    expected_layer_a_results_sha256: str,
    expected_layer_a_input_manifest_hash: str,
    expected_layer_b_results_sha256: str,
    expected_layer_b_output_manifest_sha256: str,
    expected_layer_b_input_manifest_hash: str,
    expected_layer_b_repo_head: str,
    coordinator_repo_head: str,
    page_renderer: Callable[[Path, int, Path], None] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_parent = output_parent.resolve()
    layer_a_workspace = layer_a_workspace.resolve()
    layer_b_workspace = layer_b_workspace.resolve()
    if not RECONCILIATION_RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid V3.1.1 final reconciliation run ID")
    if _is_within(output_parent, repo_root):
        raise ValueError("final reconciliation run must be outside the Git repository")
    run_root = output_parent / run_id
    if run_root.exists():
        raise FileExistsError(f"final reconciliation run already exists: {run_root}")

    frozen_before = {
        "layer_a_output": _output_tree_hashes(layer_a_workspace),
        "layer_b_output": _output_tree_hashes(layer_b_workspace),
    }
    a_rows, b_rows, tasks = _verify_frozen_inputs(
        layer_a_workspace=layer_a_workspace,
        layer_b_workspace=layer_b_workspace,
        expected_layer_a_results_sha256=expected_layer_a_results_sha256,
        expected_layer_a_input_manifest_hash=expected_layer_a_input_manifest_hash,
        expected_layer_b_results_sha256=expected_layer_b_results_sha256,
        expected_layer_b_output_manifest_sha256=expected_layer_b_output_manifest_sha256,
        expected_layer_b_input_manifest_hash=expected_layer_b_input_manifest_hash,
        expected_layer_b_repo_head=expected_layer_b_repo_head,
    )
    records = reconcile_claims(a_rows, b_rows)
    deterministic_id = deterministic_supported_spot_claim_id(b_rows)
    spot_ids = [*FIXED_SPOT_CHECK_IDS, deterministic_id]
    if len(spot_ids) != 4 or len(set(spot_ids)) != 4:
        raise ValueError("spot-check package must contain exactly four unique claims")

    temporary = output_parent / f".{run_id}.tmp-{os.getpid()}"
    if temporary.exists():
        raise FileExistsError(f"temporary reconciliation run already exists: {temporary}")
    for relative in (
        "reconciliation",
        "spot_checks/cards",
        "spot_checks/screenshots",
        "coordinator",
    ):
        (temporary / relative).mkdir(parents=True, exist_ok=True)
    atomic_write_jsonl(temporary / "reconciliation/reconciliation.jsonl", records)

    by_id = {row["claim_id"]: row for row in records}
    task_by_claim = {task["claim_id"]: task for task in tasks}
    renderer = page_renderer or _default_page_renderer
    spot_rows = []
    for claim_id in spot_ids:
        record = by_id.get(claim_id)
        task = task_by_claim.get(claim_id)
        if record is None or task is None:
            raise ValueError(f"required spot-check claim is absent: {claim_id}")
        claim = record["layer_a_claim"]
        verification = record["layer_b_verification"]
        locator = verification.get("observed_evidence_locator") or claim["evidence_locator"]
        original_page = locator.get("pdf_page_index")
        page_map = task["source_binding"]["original_to_packaged_page_index"]
        if not isinstance(original_page, int) or str(original_page) not in page_map:
            raise ValueError(f"spot-check locator is outside its packaged source: {claim_id}")
        source = (layer_b_workspace / task["source_artifact"]).resolve()
        if not _is_within(source, layer_b_workspace) or source.is_symlink() or not source.is_file():
            raise ValueError(f"spot-check source artifact is unsafe or missing: {claim_id}")
        expected_source_hash = task["source_binding"].get("packaged_artifact_sha256")
        if sha256_file(source) != expected_source_hash:
            raise ValueError(f"spot-check source artifact hash mismatch: {claim_id}")
        screenshot_relative = f"spot_checks/screenshots/{claim_id}.png"
        renderer(source, page_map[str(original_page)], temporary / screenshot_relative)
        spec = _spot_check_spec(claim_id, deterministic_id)
        card_relative = f"spot_checks/cards/{claim_id}.md"
        spot_row = {
            "schema_version": "3.1.1-human-spot-check-preparation",
            "claim_id": claim_id,
            "selection_reason": spec["selection_reason"],
            "layer_a_claim": copy.deepcopy(claim),
            "layer_b_verdict": verification["verdict"],
            "layer_b_short_independent_evidence": verification["short_independent_evidence"],
            "source_locator": copy.deepcopy(locator),
            "source_artifact_sha256": expected_source_hash,
            "screenshot_path": screenshot_relative,
            "card_path": card_relative,
            "coordinator_recommendation": spec["recommendation"],
            "coordinator_reason": spec["reason"],
            "user_options": spec["options"],
            "human_decision_recorded": False,
        }
        _write_spot_card(temporary / card_relative, {**record, **spot_row})
        spot_rows.append(spot_row)
    atomic_write_jsonl(temporary / "spot_checks/spot_check_queue.jsonl", spot_rows)
    atomic_write_json(
        temporary / "spot_checks/human_response_template.json",
        {
            "schema_version": "3.1.1-human-spot-check-response",
            "human_decisions_recorded": False,
            "items": [
                {"claim_id": row["claim_id"], "selected_decision": None, "reviewer_note": None}
                for row in spot_rows
            ],
        },
    )
    readme_lines = [
        "# Phase 8A Final Human Spot Checks",
        "",
        "本包包含恰好 4 项人工抽查卡。生成过程未记录任何人工决定。",
        "",
    ]
    readme_lines.extend(f"{index}. [{row['claim_id']}](cards/{row['claim_id']}.md)" for index, row in enumerate(spot_rows, 1))
    atomic_write_text(temporary / "spot_checks/README.md", "\n".join(readme_lines) + "\n")

    disposition_counts = dict(sorted(Counter(row["final_disposition"] for row in records).items()))
    corrections = [
        {
            "claim_id": row["claim_id"],
            "final_disposition": row["final_disposition"],
            "applied_fields": row["applied_correction_fields"],
        }
        for row in records
        if row["applied_correction_fields"]
    ]
    conflict_ids = [row["claim_id"] for row in records if row["final_disposition"] == "SOURCE_CONFLICT_RETAINED"]
    unresolved_ids = [row["claim_id"] for row in records if row["final_disposition"] == "HUMAN_REVIEW_REQUIRED"]
    summary = {
        "schema_version": "3.1.1-final-reconciliation-summary",
        "stage": "PREPARED_FOR_FINAL_4_HUMAN_SPOT_CHECKS",
        "claim_count": len(records),
        "disposition_counts": disposition_counts,
        "automatic_corrections": corrections,
        "retained_source_conflict_claim_ids": conflict_ids,
        "unresolved_claim_ids": unresolved_ids,
        "spot_check_claim_ids": spot_ids,
        "supported_spot_check_seed": SPOT_CHECK_SEED,
        "supported_spot_check_selection_hash": hashlib.sha256(f"{SPOT_CHECK_SEED}{deterministic_id}".encode()).hexdigest(),
        "human_budget_used_before": 6,
        "human_budget_limit": 10,
        "prepared_spot_check_count": 4,
        "human_budget_consumed_by_preparation": 0,
        "human_decisions_recorded": False,
        "layer_c_created": False,
        "phase8b_started": False,
    }
    atomic_write_json(temporary / "reconciliation/reconciliation_summary.json", summary)
    summary_md = [
        "# Phase 8A V3.1.1 Final Reconciliation Summary",
        "",
        f"- checkpoint: `{summary['stage']}`",
        f"- reconciled claims: `{summary['claim_count']}`",
        f"- disposition counts: `{json.dumps(disposition_counts, ensure_ascii=False, sort_keys=True)}`",
        f"- automatic corrections: `{len(corrections)}`",
        f"- retained source conflicts: `{len(conflict_ids)}`",
        f"- unresolved claims: `{len(unresolved_ids)}`",
        f"- prepared spot checks: `{len(spot_ids)}`",
        "- human decisions recorded: `false`",
        "- Layer C created: `false`",
        "- Phase 8B started: `false`",
        "",
    ]
    atomic_write_text(temporary / "reconciliation/reconciliation_summary.md", "\n".join(summary_md))

    frozen_after = {
        "layer_a_output": _output_tree_hashes(layer_a_workspace),
        "layer_b_output": _output_tree_hashes(layer_b_workspace),
    }
    if frozen_after != frozen_before:
        raise RuntimeError("frozen Layer A or Layer B output changed during reconciliation")
    result = {
        "schema_version": "3.1.1-final-reconciliation-run",
        "run_id": run_id,
        "run_root": str(output_parent / run_id),
        "stage": summary["stage"],
        "coordinator_repo_head": coordinator_repo_head,
        "frozen_inputs": {
            "layer_a_results_sha256": expected_layer_a_results_sha256,
            "layer_a_input_manifest_hash": expected_layer_a_input_manifest_hash,
            "layer_b_results_sha256": expected_layer_b_results_sha256,
            "layer_b_output_manifest_sha256": expected_layer_b_output_manifest_sha256,
            "layer_b_input_manifest_hash": expected_layer_b_input_manifest_hash,
            "layer_b_repo_head": expected_layer_b_repo_head,
        },
        "frozen_output_file_hashes_before": frozen_before,
        "frozen_output_file_hashes_after": frozen_after,
        "claim_count": len(records),
        "disposition_counts": disposition_counts,
        "spot_check_claim_ids": spot_ids,
        "human_decisions_recorded": False,
        "layer_c_created": False,
        "phase8b_started": False,
    }
    atomic_write_json(temporary / "coordinator/run_manifest.json", result)
    atomic_write_text(
        temporary / "coordinator/COORDINATOR_RESUME.md",
        "\n".join(
            [
                "# Phase 8A V3.1.1 Final Reconciliation Resume",
                "",
                f"- run ID: `{run_id}`",
                f"- checkpoint: `{summary['stage']}`",
                "- Layer A/B outputs: frozen and unchanged",
                "- human decisions recorded: `false`",
                "- Layer C created: `false`",
                "- Phase 8B started: `false`",
                "- review cards: `spot_checks/README.md`",
                "",
            ]
        ),
    )
    _write_hash_manifest(temporary)
    output_parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, run_root)
    return result
