"""Deterministic, object-level parse quality review and human decisions."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from review_writer.project.path_safety import PathSafetyError, validate_source_file
from review_writer.project.source_truth import (
    REPO_ROOT,
    SOURCE_TRUTH_ROOT,
    SourceTruthError,
    canonical_digest,
    declared_study_ids,
    load_source_truth_bundle,
)
from review_writer.project.verification_decision import (
    VerificationDecisionError,
    verification_decision,
)


PARSE_QUALITY_SCHEMA = REPO_ROOT / "schemas/evidence/parse_quality_gate.v1.schema.json"
PARSE_OBJECT_KINDS = (
    "body_order",
    "section_boundaries",
    "figure_caption_links",
    "table_structure",
    "formula_chemistry",
    "reference_boundary",
    "supplement_completeness",
)
AUTOMATIC_STATUSES = frozenset({"usable", "usable_with_review", "incomplete", "failed"})
ACTOR_TYPES = frozenset({"human_researcher", "simulated_researcher_agent"})
HUMAN_ACTIONS = frozenset(
    {"approve_candidate_extraction", "pdf_locator_only", "reparse_required"}
)
FRONT_MATTER_MARKERS = (
    "digital academic repository",
    "general rights",
    "disclaimer/complaints regulations",
)


class ParseQualityError(ValueError):
    """A stable, researcher-safe parse quality failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ParseQualityError(code) from exc


def _safe_file(project: Path, relative: str) -> Path:
    try:
        return validate_source_file(project, relative)
    except (OSError, PathSafetyError) as exc:
        raise ParseQualityError("PARSE_ASSET_INVALID") from exc


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "warning",
    page: int | None = None,
) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "page": page}


def _status(issues: list[dict[str, Any]], *, empty: str = "usable") -> str:
    if any(row["severity"] == "error" for row in issues):
        return "incomplete"
    if issues:
        return "usable_with_review"
    return empty


def _object_id(study_id: str, source_id: str, kind: str) -> str:
    return canonical_digest({"study_id": study_id, "source_id": source_id, "kind": kind})[:24]


def _object(
    study_id: str,
    source_id: str,
    kind: str,
    status: str,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "object_id": _object_id(study_id, source_id, kind),
        "source_id": source_id,
        "kind": kind,
        "status": status,
        "issues": issues,
    }
    return {
        **payload,
        "object_digest": canonical_digest(
            {
                "source_id": source_id,
                "kind": kind,
                "status": status,
                "issues": issues,
            }
        ),
        "decision": None,
    }


def _source_inputs(project: Path, source: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    markdown_path = _safe_file(project, source["canonical_markdown"]["path"])
    content_path = _safe_file(project, source["content_list"]["path"])
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ParseQualityError("PARSE_MARKDOWN_INVALID") from exc
    content = _read_json(content_path, "CONTENT_LIST_INVALID")
    if not isinstance(content, list) or not all(isinstance(row, dict) for row in content):
        raise ParseQualityError("CONTENT_LIST_INVALID")
    return markdown, content


def _body_order(
    study_id: str,
    source: dict[str, Any],
    markdown: str,
    content: list[dict[str, Any]],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not markdown.strip():
        return _object(
            study_id,
            source["source_id"],
            "body_order",
            "failed",
            [_issue("empty_markdown", "解析正文为空。", severity="error")],
        )
    pages: list[int] = []
    for row in content:
        page = row.get("page_idx")
        bbox = row.get("bbox")
        if not isinstance(page, int) or isinstance(page, bool) or page < 0:
            issues.append(_issue("invalid_page_index", "存在无效页码。", severity="error"))
            continue
        pages.append(page)
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in bbox)
        ):
            issues.append(
                _issue("invalid_bbox", "存在无效版面坐标。", severity="error", page=page + 1)
            )
    if any(right < left for left, right in zip(pages, pages[1:])):
        issues.append(_issue("reading_order_review", "检测到跨页阅读顺序回退，请核对原始 PDF。"))
    return _object(
        study_id,
        source["source_id"],
        "body_order",
        _status(issues),
        issues,
    )


def _section_boundaries(study_id: str, source: dict[str, Any], markdown: str) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    headings = re.findall(r"^#{1,6}\s+.+$", markdown, flags=re.MULTILINE)
    if not headings:
        issues.append(_issue("missing_section_headings", "未识别到章节边界，请核对正文结构。"))
    first_text = markdown[:4000].casefold()
    if any(marker in first_text for marker in FRONT_MATTER_MARKERS):
        issues.append(_issue("repository_front_matter", "正文前含仓储页或权利说明。"))
    return _object(
        study_id,
        source["source_id"],
        "section_boundaries",
        _status(issues),
        issues,
    )


def _figure_caption_links(
    project: Path,
    study_id: str,
    source: dict[str, Any],
    content: list[dict[str, Any]],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    extracted_root = Path("01_evidence/parses/extracted") / source["mineru_slug"]
    for row in content:
        if row.get("type") not in {"image", "chart"}:
            continue
        page = row.get("page_idx")
        display_page = page + 1 if isinstance(page, int) and page >= 0 else None
        asset = row.get("img_path")
        if not isinstance(asset, str) or not asset:
            issues.append(
                _issue("missing_figure_asset", "图对象缺少可核对图片。", severity="error", page=display_page)
            )
        else:
            try:
                _safe_file(project, (extracted_root / asset).as_posix())
            except ParseQualityError:
                issues.append(
                    _issue("missing_figure_asset", "图对象对应图片不存在。", severity="error", page=display_page)
                )
        caption = row.get("image_caption") if row.get("type") == "image" else row.get("chart_caption")
        if not caption:
            issues.append(_issue("caption_link_review", "图与 caption 关系需要人工核对。", page=display_page))
    return _object(
        study_id,
        source["source_id"],
        "figure_caption_links",
        _status(issues),
        issues,
    )


def _table_structure(
    study_id: str,
    source: dict[str, Any],
    content: list[dict[str, Any]],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    tables = [row for row in content if row.get("type") == "table"]
    for row in tables:
        page = row.get("page_idx")
        display_page = page + 1 if isinstance(page, int) and page >= 0 else None
        body = row.get("table_body")
        if not isinstance(body, str) or not body.strip():
            issues.append(
                _issue("table_structure_incomplete", "表格结构为空或不可读。", severity="error", page=display_page)
            )
        else:
            issues.append(_issue("table_structure_review", "表格字段必须与原始 PDF 逐项核对。", page=display_page))
    return _object(
        study_id,
        source["source_id"],
        "table_structure",
        _status(issues),
        issues,
    )


def _formula_chemistry(study_id: str, source: dict[str, Any], markdown: str) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if "\ufffd" in markdown:
        issues.append(_issue("invalid_unicode", "存在无法识别字符。", severity="error"))
    if "$" in markdown or "\\mathrm" in markdown or re.search(r"<su[bp]>", markdown, re.I):
        issues.append(_issue("chemistry_notation_review", "公式、上下标或化学符号需要回看原始 PDF。"))
    return _object(
        study_id,
        source["source_id"],
        "formula_chemistry",
        _status(issues),
        issues,
    )


def _reference_boundary(study_id: str, source: dict[str, Any], markdown: str) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    match = re.search(r"^#{1,6}\s+(?:■\s*)?(?:references|bibliography)\s*$", markdown, re.I | re.M)
    if match is None:
        issues.append(_issue("reference_boundary_review", "未可靠识别参考文献边界。"))
    else:
        tail = markdown[match.end() :]
        if re.search(r"^#{1,3}\s+(?!references|bibliography).+$", tail, re.I | re.M):
            issues.append(_issue("content_after_references", "参考文献之后仍有正文级标题。"))
    return _object(
        study_id,
        source["source_id"],
        "reference_boundary",
        _status(issues),
        issues,
    )


def _si_policy(project: Path, study_id: str) -> str:
    path = project / "00_sources/source_coverage.json"
    if not path.is_file():
        return "UNKNOWN"
    payload = _read_json(path, "SOURCE_COVERAGE_INVALID")
    if not isinstance(payload, dict) or not isinstance(payload.get("studies"), list):
        raise ParseQualityError("SOURCE_COVERAGE_INVALID")
    matches = [row for row in payload["studies"] if isinstance(row, dict) and row.get("study_id") == study_id]
    if len(matches) != 1:
        return "UNKNOWN"
    policy = matches[0].get("si_policy")
    return policy if isinstance(policy, str) else "UNKNOWN"


def _supplement_completeness(
    project: Path,
    study_id: str,
    source: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    policy = _si_policy(project, study_id)
    has_si = any(row.get("document_role") == "SI" for row in bundle["sources"])
    issues: list[dict[str, Any]] = []
    status = "usable"
    if policy == "REQUIRED" and not has_si:
        status = "usable_with_review"
        issues.append(
            _issue(
                "supplement_missing",
                "该研究要求 SI；后续只允许处理不依赖 SI 的主文内容。",
            )
        )
    elif policy not in {"NOT_REQUIRED", "REQUIRED", "RECOMMENDED"}:
        status = "usable_with_review"
        issues.append(_issue("supplement_policy_review", "无法确认 SI 完整性策略。"))
    elif policy == "RECOMMENDED" and not has_si:
        status = "usable_with_review"
        issues.append(_issue("supplement_recommended_missing", "建议补充 SI 后再提取相关证据。"))
    return _object(
        study_id,
        source["source_id"],
        "supplement_completeness",
        status,
        issues,
    )


def _assessment_digest(gate: dict[str, Any]) -> str:
    objects = [
        {key: value for key, value in row.items() if key != "decision"}
        for row in gate["objects"]
    ]
    return canonical_digest(
        {
            "schema_version": gate["schema_version"],
            "study_id": gate["study_id"],
            "bundle_digest": gate["bundle_digest"],
            "objects": objects,
        }
    )


def _project(gate: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(gate)
    pending = False
    reparse = False
    pdf_only = False
    for row in result["objects"]:
        if row["status"] == "usable":
            continue
        decision = row.get("decision")
        if (
            not isinstance(decision, dict)
            or decision.get("bound_object_digest") != row["object_digest"]
            or decision.get("bound_gate_digest") != result["gate_digest"]
            or decision.get("schema_version") != "verification-decision.v1"
            or decision.get("actor_type") not in ACTOR_TYPES
            or not isinstance(decision.get("actor_label"), str)
            or not decision["actor_label"].strip()
            or not isinstance(decision.get("reason"), str)
            or not decision["reason"].strip()
        ):
            pending = True
            continue
        action = decision.get("action")
        allowed_actions = (
            HUMAN_ACTIONS
            if row["status"] == "usable_with_review"
            else frozenset({"pdf_locator_only", "reparse_required"})
        )
        if action not in allowed_actions:
            pending = True
            continue
        reparse = reparse or action == "reparse_required"
        pdf_only = pdf_only or action == "pdf_locator_only"
    if reparse:
        status = "blocked"
    elif pending:
        status = "needs_review"
    elif pdf_only:
        status = "approved_with_pdf_locator"
    else:
        status = "approved"
    result["status"] = status
    result["workflow_can_continue"] = not pending and not reparse
    result["automatic_extraction_allowed"] = not pending and not reparse and not pdf_only
    return result


def _validate_gate(
    gate: dict[str, Any],
    *,
    allow_legacy_object_digest: bool = False,
) -> None:
    schema = _read_json(PARSE_QUALITY_SCHEMA, "PARSE_QUALITY_SCHEMA_INVALID")
    errors = sorted(Draft202012Validator(schema).iter_errors(gate), key=lambda error: list(error.path))
    if errors:
        raise ParseQualityError("PARSE_QUALITY_SCHEMA_INVALID")
    if _assessment_digest(gate) != gate.get("gate_digest"):
        raise ParseQualityError("PARSE_QUALITY_DIGEST_MISMATCH")
    for row in gate["objects"]:
        expected = canonical_digest(
            {
                "source_id": row["source_id"],
                "kind": row["kind"],
                "status": row["status"],
                "issues": row["issues"],
            }
        )
        if allow_legacy_object_digest and row.get("object_digest") is None:
            continue
        if row.get("object_digest") != expected:
            raise ParseQualityError("PARSE_OBJECT_DIGEST_MISMATCH")


def build_parse_quality_gate(project: Path, bundle: dict[str, object]) -> dict[str, object]:
    project = project.resolve(strict=True)
    study_id = bundle.get("study_id")
    if not isinstance(study_id, str) or not isinstance(bundle.get("sources"), list):
        raise ParseQualityError("SOURCE_TRUTH_INVALID")
    objects: list[dict[str, Any]] = []
    for source in bundle["sources"]:
        if not isinstance(source, dict):
            raise ParseQualityError("SOURCE_TRUTH_INVALID")
        markdown, content = _source_inputs(project, source)
        objects.extend(
            (
                _body_order(study_id, source, markdown, content),
                _section_boundaries(study_id, source, markdown),
                _figure_caption_links(project, study_id, source, content),
                _table_structure(study_id, source, content),
                _formula_chemistry(study_id, source, markdown),
                _reference_boundary(study_id, source, markdown),
                _supplement_completeness(project, study_id, source, bundle),
            )
        )
    gate: dict[str, Any] = {
        "schema_version": "parse-quality-gate.v1",
        "study_id": study_id,
        "bundle_digest": bundle["bundle_digest"],
        "objects": objects,
        "gate_digest": "",
        "status": "needs_review",
        "workflow_can_continue": False,
        "automatic_extraction_allowed": False,
    }
    gate["gate_digest"] = _assessment_digest(gate)
    gate = _project(gate)
    _validate_gate(gate)
    return gate


def _gate_path(project: Path, study_id: str) -> Path:
    if not study_id or study_id in {".", ".."} or "/" in study_id or "\\" in study_id:
        raise ParseQualityError("STUDY_ID_INVALID")
    return project / SOURCE_TRUTH_ROOT / study_id / "parse_quality.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_parse_quality_gate(project: Path, study_id: str) -> dict[str, object]:
    project = project.resolve(strict=True)
    try:
        bundle = load_source_truth_bundle(project, study_id)
    except SourceTruthError as exc:
        raise ParseQualityError(exc.code) from exc
    gate = build_parse_quality_gate(project, bundle)
    path = _gate_path(project, study_id)
    if path.is_file():
        previous = _read_json(path, "PARSE_QUALITY_INVALID")
        if not isinstance(previous, dict):
            raise ParseQualityError("PARSE_QUALITY_INVALID")
        _validate_gate(previous, allow_legacy_object_digest=True)
        if previous["gate_digest"] == gate["gate_digest"]:
            decisions = {
                (row["object_id"], row.get("object_digest")): row.get("decision")
                for row in previous["objects"]
                if isinstance(row.get("decision"), dict)
                and row.get("object_digest") is not None
                and row["decision"].get("bound_object_digest") == row["object_digest"]
            }
            for row in gate["objects"]:
                row["decision"] = decisions.get((row["object_id"], row["object_digest"]))
            gate = _project(gate)
    _validate_gate(gate)
    _atomic_json(path, gate)
    return gate


def parse_quality_state(project: Path, study_id: str) -> dict[str, object]:
    project = project.resolve(strict=True)
    try:
        bundle = load_source_truth_bundle(project, study_id)
    except SourceTruthError as exc:
        raise ParseQualityError(exc.code) from exc
    path = _gate_path(project, study_id)
    gate = _read_json(path, "PARSE_QUALITY_MISSING")
    if not isinstance(gate, dict):
        raise ParseQualityError("PARSE_QUALITY_INVALID")
    _validate_gate(gate)
    if gate["bundle_digest"] != bundle["bundle_digest"]:
        stale = copy.deepcopy(gate)
        stale["status"] = "stale"
        stale["workflow_can_continue"] = False
        stale["automatic_extraction_allowed"] = False
        return stale
    return _project(gate)


def apply_parse_quality_decision(
    project: Path,
    study_id: str,
    payload: object,
) -> dict[str, object]:
    project = project.resolve(strict=True)
    required = {"object_id", "gate_digest", "action", "note"}
    optional = {"object_digest", "actor_type", "actor_label"}
    if (
        not isinstance(payload, dict)
        or not required.issubset(payload)
        or not set(payload).issubset(required | optional)
        or (("actor_type" in payload) != ("actor_label" in payload))
    ):
        raise ParseQualityError("DECISION_INVALID")
    object_id = payload.get("object_id")
    gate_digest = payload.get("gate_digest")
    object_digest = payload.get("object_digest")
    action = payload.get("action")
    note_value = payload.get("note")
    note = note_value.strip() if isinstance(note_value, str) else ""
    actor_type = payload.get("actor_type", "human_researcher")
    actor_label_value = payload.get("actor_label", "local-researcher")
    actor_label = actor_label_value.strip() if isinstance(actor_label_value, str) else ""
    if (
        not isinstance(object_id, str)
        or not isinstance(gate_digest, str)
        or (object_digest is not None and not isinstance(object_digest, str))
        or action not in HUMAN_ACTIONS
        or not note
        or len(note) > 2000
        or actor_type not in ACTOR_TYPES
        or not actor_label
        or len(actor_label) > 200
    ):
        raise ParseQualityError("DECISION_INVALID")
    gate = parse_quality_state(project, study_id)
    if gate["status"] == "stale" or gate_digest != gate["gate_digest"]:
        raise ParseQualityError("PARSE_QUALITY_STALE")
    matches = [row for row in gate["objects"] if row["object_id"] == object_id]
    if len(matches) != 1:
        raise ParseQualityError("PARSE_OBJECT_NOT_FOUND")
    row = matches[0]
    if object_digest is not None and object_digest != row["object_digest"]:
        raise ParseQualityError("PARSE_QUALITY_STALE")
    if row["status"] == "usable":
        raise ParseQualityError("ACTION_NOT_REQUIRED")
    if row["status"] in {"incomplete", "failed"} and action == "approve_candidate_extraction":
        raise ParseQualityError("ACTION_NOT_ALLOWED")
    try:
        decision = verification_decision(
            actor_type=actor_type,
            actor_label=actor_label,
            action=str(action),
            reason=note,
            bound_object_digest=str(row["object_digest"]),
            bound_gate_digest=str(gate["gate_digest"]),
        )
    except VerificationDecisionError as exc:
        raise ParseQualityError("DECISION_INVALID") from exc
    row["decision"] = {**decision, "note": note}
    gate = _project(gate)
    _validate_gate(gate)
    _atomic_json(_gate_path(project, study_id), gate)
    return gate


def project_parse_quality_state(project: Path) -> dict[str, object]:
    project = project.resolve(strict=True)
    root = project / SOURCE_TRUTH_ROOT
    try:
        study_ids = declared_study_ids(project)
    except SourceTruthError as exc:
        return {
            "status": "needs_attention",
            "reason_code": exc.code,
            "workflow_can_continue": False,
            "automatic_extraction_allowed": False,
            "studies": [],
        }
    actual_study_ids = (
        sorted(
            path.name
            for path in root.iterdir()
            if path.is_dir() and not path.is_symlink()
        )
        if root.is_dir() and not root.is_symlink()
        else []
    )
    if actual_study_ids != study_ids:
        return {
            "status": "needs_attention",
            "reason_code": "SOURCE_TRUTH_STUDY_SET_MISMATCH",
            "workflow_can_continue": False,
            "automatic_extraction_allowed": False,
            "studies": [],
        }
    if not study_ids:
        return {
            "status": "needs_review",
            "workflow_can_continue": False,
            "automatic_extraction_allowed": False,
            "studies": [],
        }
    studies: list[dict[str, object]] = []
    for study_id in study_ids:
        try:
            studies.append(parse_quality_state(project, study_id))
        except ParseQualityError as exc:
            return {
                "status": "needs_attention",
                "reason_code": exc.code,
                "workflow_can_continue": False,
                "automatic_extraction_allowed": False,
                "studies": studies,
            }
    workflow = all(bool(row["workflow_can_continue"]) for row in studies)
    automatic = all(bool(row["automatic_extraction_allowed"]) for row in studies)
    return {
        "status": "approved" if workflow else "needs_review",
        "workflow_can_continue": workflow,
        "automatic_extraction_allowed": automatic,
        "studies": studies,
    }


def require_parse_quality_ready(project: Path, study_id: str) -> str:
    state = parse_quality_state(project, study_id)
    if state["status"] == "stale":
        raise ParseQualityError("PARSE_QUALITY_STALE")
    if state["automatic_extraction_allowed"]:
        return str(state["gate_digest"])
    actions = {
        row["decision"]["action"]
        for row in state["objects"]
        if isinstance(row.get("decision"), dict)
    }
    if "reparse_required" in actions:
        raise ParseQualityError("PARSE_REPARSE_REQUIRED")
    if "pdf_locator_only" in actions and state["workflow_can_continue"]:
        raise ParseQualityError("PARSE_PDF_LOCATOR_ONLY")
    raise ParseQualityError("PARSE_QUALITY_REVIEW_REQUIRED")
