"""Evidence-preserving rubric and Hard Fail projection for review releases."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from review_writer.project.manuscript_v2 import manuscript_state
from review_writer.project.source_truth import canonical_digest


REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_SCHEMA = REPO_ROOT / "schemas/quality/review_benchmark_report.v1.schema.json"
PLACEHOLDER_SCHEMA = REPO_ROOT / "schemas/figures/synthesis_figure_placeholder.v1.schema.json"
RUBRIC_DIMENSIONS = (
    ("scope_and_question_value", 10),
    ("source_set_coverage", 15),
    ("evidence_fidelity", 20),
    ("synthesis_and_critique", 20),
    ("structure_and_narrative", 15),
    ("figure_information_value", 10),
    ("citation_and_traceability", 10),
)
COMPARISON_METRICS = (
    "section_proportions",
    "comparison_and_critique_density",
    "source_figure_density",
    "caption_information_content",
    "citation_density",
    "claim_traceability",
)
COMMON_HARD_FAILS = frozenset(
    {
        "WRONG_SOURCE_BINDING",
        "SUPPORTING_SOURCE_UNREAD",
        "HIGH_RISK_CLAIM_UNAPPROVED",
        "STALE_APPROVAL",
        "FABRICATED_SCIENTIFIC_DETAIL",
        "STATE_SURFACE_DIVERGENCE",
        "UNSOURCED_SCIENTIFIC_CLAIM",
        "LEGACY_DRAFT_REPACKAGED",
        "SYSTEM_GENERATED_SYNTHESIS_FIGURE",
    }
)
EXPERT_HARD_FAILS = frozenset({"SYNTHESIS_FIGURE_PENDING"})
RELEASE_LEVELS = frozenset({"SELF_REVIEWED_DRAFT", "EXPERT_REVIEWED_RELEASE"})


class BenchmarkError(ValueError):
    """A stable benchmark input or report failure."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_json(path: Path, code: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise BenchmarkError(code)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkError(code) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_payload(release: Path, release_level: str | None) -> dict[str, Any]:
    """Read a release and bind the report to canonical, on-disk state."""
    if not isinstance(release, Path) or release.is_symlink() or not release.is_dir():
        raise BenchmarkError("BENCHMARK_RELEASE_INVALID")
    try:
        project = release.resolve(strict=True)
        snapshot = _read_json(project / "05_release/release_snapshot.json", "BENCHMARK_RELEASE_INVALID")
    except (OSError, BenchmarkError) as exc:
        raise BenchmarkError("BENCHMARK_RELEASE_INVALID") from exc
    if not isinstance(snapshot, dict):
        raise BenchmarkError("BENCHMARK_RELEASE_INVALID")
    project_id = snapshot.get("project_id", project.name)
    level = release_level or snapshot.get("release_level") or snapshot.get("status")
    if level not in RELEASE_LEVELS or not isinstance(project_id, str) or not project_id:
        raise BenchmarkError("BENCHMARK_RELEASE_INVALID")

    divergence = False
    manuscript_path = project / "04_manuscript/manuscript.md"
    lineage_path = project / "04_manuscript/manuscript_lineage.v2.json"
    state: dict[str, Any]
    try:
        state = manuscript_state(project)
    except Exception:
        state = {"workflow_can_continue": False}
        divergence = True
    if state.get("workflow_can_continue") is not True:
        divergence = True
    try:
        actual_manuscript_sha256 = _sha256_file(manuscript_path) if manuscript_path.is_file() else None
        lineage = _read_json(lineage_path, "BENCHMARK_RELEASE_INVALID")
        if not isinstance(lineage, dict):
            raise BenchmarkError("BENCHMARK_RELEASE_INVALID")
    except (OSError, BenchmarkError):
        actual_manuscript_sha256 = None
        lineage = {}
        divergence = True
    state_manuscript_sha256 = state.get("manuscript_sha256")
    state_lineage_digest = state.get("lineage_digest")
    if (
        not isinstance(actual_manuscript_sha256, str)
        or state_manuscript_sha256 != actual_manuscript_sha256
        or lineage.get("manuscript_sha256") != actual_manuscript_sha256
        or lineage.get("lineage_digest") != state_lineage_digest
    ):
        divergence = True

    docx_path: Path | None = None
    docx_sha256: str | None = None
    declared_docx_path = snapshot.get("docx_path")
    if isinstance(declared_docx_path, str) and declared_docx_path:
        candidate = project / declared_docx_path
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(project)
            if resolved.is_file() and not candidate.is_symlink():
                docx_path = resolved
                docx_sha256 = _sha256_file(resolved)
        except (OSError, ValueError):
            pass
    if (
        docx_path is None
        or snapshot.get("docx_sha256") != docx_sha256
        or snapshot.get("manuscript_sha256") != actual_manuscript_sha256
        or snapshot.get("lineage_digest") != state_lineage_digest
        or snapshot.get("project_id", project.name) != project_id
    ):
        divergence = True

    placeholders: list[dict[str, Any]] = []
    placeholder_path = project / "03_figures/synthesis_figure_placeholders.json"
    try:
        placeholder_state = _read_json(placeholder_path, "BENCHMARK_RELEASE_INVALID")
        if not isinstance(placeholder_state, dict) or not isinstance(placeholder_state.get("placeholders"), list):
            raise BenchmarkError("BENCHMARK_RELEASE_INVALID")
        placeholders = placeholder_state["placeholders"]
    except BenchmarkError:
        divergence = True
    validator = Draft202012Validator(_read_json(PLACEHOLDER_SCHEMA, "BENCHMARK_SCHEMA_INVALID"))
    if any(not isinstance(row, dict) or list(validator.iter_errors(row)) for row in placeholders):
        divergence = True
    placeholder_digest = canonical_digest(placeholders)
    if lineage.get("synthesis_figure_placeholder_digest") != placeholder_digest:
        divergence = True
    manuscript_text = ""
    if manuscript_path.is_file():
        try:
            manuscript_text = manuscript_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            divergence = True
    for row in placeholders:
        if isinstance(row, dict) and row.get("status") != "verified":
            placeholder_id = row.get("placeholder_id")
            if (
                not isinstance(placeholder_id, str)
                or f"SYNTHESIS_FIGURE_PLACEHOLDER: {placeholder_id}" not in manuscript_text
            ):
                divergence = True

    signals = snapshot.get("hard_fail_signals", [])
    if not isinstance(signals, list) or not all(isinstance(code, str) for code in signals):
        raise BenchmarkError("BENCHMARK_RELEASE_INVALID")
    signals = list(signals)
    if snapshot.get("system_generated_synthesis_figure") is True:
        signals.append("SYSTEM_GENERATED_SYNTHESIS_FIGURE")
    if divergence:
        signals.append("STATE_SURFACE_DIVERGENCE")
    return {
        "project_id": project_id,
        "release_level": level,
        "manuscript_sha256": actual_manuscript_sha256 if not divergence else None,
        "release_sha256": docx_sha256 if not divergence else None,
        "placeholders": placeholders,
        "hard_fail_signals": signals,
    }


def _rubric_rows(scores: object) -> list[dict[str, Any]]:
    if isinstance(scores, dict):
        source = scores.get("rubric", scores)
        if isinstance(source, dict):
            source = [
                {"dimension_id": dimension_id, **(value if isinstance(value, dict) else {"score": value})}
                for dimension_id, value in source.items()
            ]
    else:
        source = scores
    if not isinstance(source, list) or not all(isinstance(row, dict) for row in source):
        raise BenchmarkError("BENCHMARK_SCORES_INVALID")
    by_id = {row.get("dimension_id"): row for row in source}
    if len(by_id) != len(source) or set(by_id) != {key for key, _ in RUBRIC_DIMENSIONS}:
        raise BenchmarkError("BENCHMARK_SCORES_INVALID")
    rows: list[dict[str, Any]] = []
    for dimension_id, maximum in RUBRIC_DIMENSIONS:
        source_row = by_id[dimension_id]
        score = source_row.get("score")
        rationale = source_row.get("rationale")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or score < 0
            or score > maximum
            or not isinstance(rationale, str)
            or not rationale.strip()
            or source_row.get("max_score", maximum) != maximum
        ):
            raise BenchmarkError("BENCHMARK_SCORES_INVALID")
        rows.append(
            {
                "dimension_id": dimension_id,
                "max_score": maximum,
                "score": score,
                "rationale": rationale.strip(),
            }
        )
    return rows


def _tier(score: int | float) -> str:
    if score < 80:
        return "below_internal_threshold"
    if score < 90:
        return "acceptable_internal_revision_required"
    return "benchmark_internal"


def _expected_status(level: str, score: int | float, hard_fails: list[str]) -> str:
    if score < 80 or hard_fails:
        return "fail"
    return "pass_expert" if level == "EXPERT_REVIEWED_RELEASE" else "pass_internal"


def _schema_validator() -> Draft202012Validator:
    schema = _read_json(REPORT_SCHEMA, "BENCHMARK_SCHEMA_INVALID")
    if not isinstance(schema, dict):
        raise BenchmarkError("BENCHMARK_SCHEMA_INVALID")
    return Draft202012Validator(schema)


def validate_report(report: object) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise BenchmarkError("BENCHMARK_REPORT_INVALID")
    errors = sorted(_schema_validator().iter_errors(report), key=lambda error: list(error.path))
    if errors:
        raise BenchmarkError("BENCHMARK_REPORT_INVALID")
    rows = report["rubric"]
    expected_ids = [key for key, _ in RUBRIC_DIMENSIONS]
    if (
        [row["dimension_id"] for row in rows] != expected_ids
        or [row["max_score"] for row in rows] != [value for _, value in RUBRIC_DIMENSIONS]
        or report["score"] != sum(row["score"] for row in rows)
        or report["tier"] != _tier(report["score"])
        or report["status"]
        != _expected_status(report["release_level"], report["score"], report["hard_fails"])
        or report["comparison_metrics"] != list(COMPARISON_METRICS)
        or (
            report["release_level"] == "SELF_REVIEWED_DRAFT"
            and "SYNTHESIS_FIGURE_PENDING" in report["hard_fails"]
        )
        or (
            report["release_level"] == "EXPERT_REVIEWED_RELEASE"
            and "SYNTHESIS_FIGURE_PENDING" in report["issues"]
            and "SYNTHESIS_FIGURE_PENDING" not in report["hard_fails"]
        )
    ):
        raise BenchmarkError("BENCHMARK_REPORT_INCONSISTENT")
    expert_ready = (
        report["score"] >= 80
        and not report["hard_fails"]
        and "SYNTHESIS_FIGURE_PENDING" not in report["issues"]
    )
    if report["expert_release_ready"] is not expert_ready:
        raise BenchmarkError("BENCHMARK_REPORT_INCONSISTENT")
    return report


def evaluate_review(
    release: Path,
    rubric_scores: object,
    *,
    hard_fails: list[str] | tuple[str, ...] = (),
    release_level: str | None = None,
    standard_corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project numeric scores and explicit failure evidence into one report."""
    binding = _release_payload(release, release_level)
    rubric = _rubric_rows(rubric_scores)
    score = sum(row["score"] for row in rubric)
    pending = any(row.get("status") != "verified" for row in binding["placeholders"])
    issues = ["SYNTHESIS_FIGURE_PENDING"] if pending else []
    all_hard_fails = list(hard_fails) + binding["hard_fail_signals"]
    if binding["release_level"] == "EXPERT_REVIEWED_RELEASE" and pending:
        all_hard_fails.append("SYNTHESIS_FIGURE_PENDING")
    allowed = COMMON_HARD_FAILS | EXPERT_HARD_FAILS
    if any(code not in allowed for code in all_hard_fails):
        raise BenchmarkError("BENCHMARK_HARD_FAIL_INVALID")
    unique_hard_fails = sorted(set(all_hard_fails))
    report = {
        "schema_version": "review-benchmark-report.v1",
        "evaluated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_id": binding["project_id"],
        "release_level": binding["release_level"],
        "status": _expected_status(binding["release_level"], score, unique_hard_fails),
        "score": score,
        "tier": _tier(score),
        "expert_release_ready": score >= 80 and not unique_hard_fails and not pending,
        "rubric": rubric,
        "hard_fails": unique_hard_fails,
        "issues": issues,
        "release_binding": {
            "manuscript_sha256": binding["manuscript_sha256"],
            "release_sha256": binding["release_sha256"],
        },
        "standard_corpus": standard_corpus,
        "comparison_metrics": list(COMPARISON_METRICS),
        "human_review_required": True,
        "disclaimer": "Regression score only; not scientific correctness, expert acceptance, or publication approval.",
    }
    return validate_report(report)
