#!/usr/bin/env python3
"""Thin, offline CLI for the authoritative vertical review projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.acquisition.manifest_identity import normalize_doi  # noqa: E402
from review_writer.project.vertical_review import (  # noqa: E402
    VerticalReviewError,
    apply_risk_decisions,
    benchmark_metrics,
    build_risk_packet,
    build_writer_packet,
    initialize_review,
    register_study,
)
from scripts.evidence.build_page_atom_catalog import (  # noqa: E402
    PageCatalogError,
    build_page_atom_catalog,
    validate_catalog_schema,
)
from scripts.evidence.evidence_atom_core import sha256_file  # noqa: E402


CATALOG_SCHEMA = REPO_ROOT / "schemas" / "evidence" / "evidence_atom_catalog.v1.schema.json"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _print_summary(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")),
        file=stream,
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
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
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _decision_counts(projection: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "approved_claim_count": sum(row.get("decision") == "APPROVED" for row in projection),
        "blocked_claim_count": sum(row.get("decision") == "BLOCKED" for row in projection),
        "human_required_claim_count": sum(
            row.get("decision") == "HUMAN_REQUIRED" for row in projection
        ),
    }


class _PrepareNotReady(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _prepare_block(code: str) -> None:
    raise _PrepareNotReady(code)


def _prepare_manifest(
    project: Path,
    relative: str,
    *,
    missing: str,
    invalid: str,
) -> dict[str, Any]:
    path = project / relative
    if not path.is_file():
        _prepare_block(missing)
    try:
        payload = _load_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _prepare_block(invalid)
    if not isinstance(payload, dict):
        _prepare_block(invalid)
    return payload


def _prepare_rows(payload: dict[str, Any], key: str, invalid: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        _prepare_block(invalid)
    return rows


def _bound_file(project: Path, root: Path, value: Any, code: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        _prepare_block(code)
    portable = value.strip().replace("\\", "/")
    relative = Path(portable)
    if relative.is_absolute():
        candidate = relative
    elif relative.parts and relative.parts[0] in {
        "00_sources",
        "01_evidence",
    }:
        candidate = project / relative
    else:
        candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(project.resolve())
    except (OSError, ValueError):
        _prepare_block(code)
    if not resolved.is_file():
        _prepare_block(code)
    return resolved


def _receipt_sources(project: Path, study: dict[str, Any]) -> list[dict[str, Any]]:
    main = study.get("main_pdf")
    if study.get("status") != "ACQUIRED" or not isinstance(main, dict):
        _prepare_block("ACQUISITION_MAIN_NOT_ACQUIRED")
    si_value = study.get("si_pdf")
    supplements = si_value if isinstance(si_value, list) else [si_value]
    declared = [("MAIN", main)] + [
        ("SI", row)
        for row in supplements
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    ]
    declared[1:] = sorted(declared[1:], key=lambda item: str(item[1].get("path")))
    sources: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for role, row in declared:
        path = _bound_file(project, project / "00_sources", row.get("path"), "ACQUISITION_SOURCE_MISSING")
        if path in seen_paths:
            _prepare_block("ACQUISITION_SOURCE_AMBIGUOUS")
        seen_paths.add(path)
        observed = sha256_file(path)
        expected = row.get("sha256", row.get("pdf_sha256"))
        if expected is not None and expected != observed:
            _prepare_block("ACQUISITION_SOURCE_HASH_MISMATCH")
        sources.append({"document_role": role, "path": path, "pdf_sha256": observed})
    return sources


def _verify_source_identity(project: Path, doi: str) -> None:
    audit = _prepare_manifest(
        project,
        "00_sources/source_identity_audit.json",
        missing="SOURCE_IDENTITY_AUDIT_MISSING",
        invalid="SOURCE_IDENTITY_AUDIT_INVALID",
    )
    rows = audit.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        _prepare_block("SOURCE_IDENTITY_AUDIT_INVALID")
    matches = [row for row in rows if normalize_doi(row.get("doi")) == doi]
    if not matches:
        _prepare_block("SOURCE_IDENTITY_BINDING_MISSING")
    if any(str(row.get("verdict", "")).upper() == "QUARANTINE" for row in matches):
        _prepare_block("SOURCE_IDENTITY_QUARANTINED")


def _bind_source_layers(project: Path, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mineru_root = project / "01_evidence/mineru"
    mineru = _prepare_manifest(
        project,
        "01_evidence/mineru/manifest.json",
        missing="MINERU_MANIFEST_MISSING",
        invalid="MINERU_MANIFEST_INVALID",
    )
    completed = _prepare_rows(mineru, "completed", "MINERU_MANIFEST_INVALID")
    completed_paths = [
        (_bound_file(project, project / "00_sources", row.get("relative_pdf_path"), "MINERU_MANIFEST_INVALID"), row)
        for row in completed
    ]

    layer_root = project / "01_evidence/text_layers"
    layer_manifest = _prepare_manifest(
        project,
        "01_evidence/text_layers/text_layers.manifest.json",
        missing="TEXT_LAYER_MANIFEST_MISSING",
        invalid="TEXT_LAYER_MANIFEST_INVALID",
    )
    layer_rows = _prepare_rows(layer_manifest, "sources", "TEXT_LAYER_MANIFEST_INVALID")
    bound: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    for source in sources:
        mineru_matches = [row for path, row in completed_paths if path == source["path"]]
        if len(mineru_matches) != 1:
            _prepare_block(
                "MINERU_BINDING_MISSING" if not mineru_matches else "MINERU_BINDING_AMBIGUOUS"
            )
        mineru_row = mineru_matches[0]
        slug = mineru_row.get("slug")
        markdown_value = (
            f"markdown/{slug}.md"
            if isinstance(slug, str)
            and slug
            and "/" not in slug
            and "\\" not in slug
            else mineru_row.get("markdown_copy")
        )
        _bound_file(project, mineru_root, markdown_value, "MINERU_MARKDOWN_MISSING")

        matches = [row for row in layer_rows if row.get("pdf_sha256") == source["pdf_sha256"]]
        if len(matches) != 1:
            _prepare_block(
                "TEXT_LAYER_BINDING_MISSING" if not matches else "TEXT_LAYER_BINDING_AMBIGUOUS"
            )
        row = matches[0]
        source_id = row.get("source_id")
        page_count = row.get("page_count")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in seen_source_ids
            or not isinstance(page_count, int)
            or isinstance(page_count, bool)
            or page_count < 1
        ):
            _prepare_block("TEXT_LAYER_BINDING_INVALID")
        seen_source_ids.add(source_id)
        reading = _bound_file(project, layer_root, row.get("reading_order_path"), "TEXT_LAYER_BINDING_INVALID")
        layout = _bound_file(project, layer_root, row.get("layout_path"), "TEXT_LAYER_BINDING_INVALID")
        if sha256_file(reading) != row.get("reading_order_sha256") or sha256_file(layout) != row.get("layout_sha256"):
            _prepare_block("TEXT_LAYER_HASH_MISMATCH")
        bound.append(
            {
                "document_role": source["document_role"],
                "layout_path": layout.relative_to(project.resolve()).as_posix(),
                "layout_sha256": row["layout_sha256"],
                "page_count": page_count,
                "reading_order_path": reading.relative_to(project.resolve()).as_posix(),
                "reading_order_sha256": row["reading_order_sha256"],
                "source_binary_sha256": source["pdf_sha256"],
                "source_id": source_id,
                "visual_evidence_allowed": False,
            }
        )
    return bound


def _persist_prepare_packet(project: Path, study_id: str, job: dict[str, Any]) -> None:
    evidence_root = project / "01_evidence"
    target = evidence_root / study_id
    stage: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{study_id}.prepare-", dir=evidence_root)
    )
    try:
        job_path = stage / "sealed_job.json"
        catalog_path = stage / "atom_catalog.json"
        _atomic_write_json(job_path, job)
        catalog = build_page_atom_catalog(job_path, project)
        validate_catalog_schema(catalog, _load_json(CATALOG_SCHEMA))
        _atomic_write_json(catalog_path, catalog)
        if target.exists():
            existing = (target / "sealed_job.json", target / "atom_catalog.json")
            if (
                target.is_dir()
                and not target.is_symlink()
                and all(path.is_file() for path in existing)
                and existing[0].read_bytes() == job_path.read_bytes()
                and existing[1].read_bytes() == catalog_path.read_bytes()
            ):
                return
            _prepare_block("PREPARE_OUTPUT_CONFLICT")
        stage.rename(target)
        stage = None
    finally:
        if stage is not None:
            for name in ("sealed_job.json", "atom_catalog.json"):
                (stage / name).unlink(missing_ok=True)
            stage.rmdir()


def _prepare_status(project: Path, study_id: str) -> dict[str, Any]:
    metrics = benchmark_metrics(project)
    if (
        not study_id.strip()
        or study_id != study_id.strip()
        or study_id in {".", ".."}
        or "/" in study_id
        or "\\" in study_id
    ):
        raise VerticalReviewError("STUDY_ID_INVALID", "study_id must be nonempty")
    manifest_path = project / "00_discovery" / "acquisition_manifest.json"
    if not manifest_path.is_file():
        return {
            "command": "prepare-study",
            "reason_code": "ACQUISITION_MANIFEST_MISSING",
            "status": "NOT_READY",
            "study_id": study_id,
        }
    try:
        pool = _prepare_manifest(
            project,
            "00_discovery/candidate_pool.json",
            missing="CANDIDATE_POOL_MISSING",
            invalid="CANDIDATE_POOL_INVALID",
        )
        candidates = _prepare_rows(pool, "candidates", "CANDIDATE_POOL_INVALID")
        matches = [row for row in candidates if row.get("candidate_id") == study_id]
        if len(matches) != 1:
            _prepare_block("STUDY_NOT_DECLARED" if not matches else "STUDY_ID_AMBIGUOUS")
        doi = normalize_doi(matches[0].get("doi"))
        if doi is None:
            _prepare_block("CANDIDATE_DOI_INVALID")

        screening = _prepare_manifest(
            project,
            "00_discovery/screening_decisions.json",
            missing="SCREENING_DECISIONS_MISSING",
            invalid="SCREENING_DECISIONS_INVALID",
        )
        decisions = [
            row
            for row in _prepare_rows(screening, "decisions", "SCREENING_DECISIONS_INVALID")
            if row.get("candidate_id") == study_id
        ]
        if len(decisions) != 1:
            _prepare_block(
                "SCREENING_DECISION_MISSING" if not decisions else "SCREENING_DECISION_AMBIGUOUS"
            )
        if decisions[0].get("disposition") != "INCLUDE_FOR_FULL_TEXT":
            _prepare_block("STUDY_NOT_INCLUDED")

        receipt = _prepare_manifest(
            project,
            "00_sources/acquisition_final_receipt.json",
            missing="ACQUISITION_FINAL_RECEIPT_MISSING",
            invalid="ACQUISITION_FINAL_RECEIPT_INVALID",
        )
        studies = [
            row
            for row in _prepare_rows(receipt, "studies", "ACQUISITION_FINAL_RECEIPT_INVALID")
            if normalize_doi(row.get("doi")) == doi
        ]
        if len(studies) != 1:
            _prepare_block("ACQUISITION_DOI_MISSING" if not studies else "ACQUISITION_DOI_AMBIGUOUS")
        _verify_source_identity(project, doi)
        source_files = _bind_source_layers(project, _receipt_sources(project, studies[0]))
        identity = {"doi": doi, "project_id": metrics["project_id"], "study_id": study_id}
        job = {
            "job_id": "JOB-" + hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "mode": "EVIDENCE_ATOM_SEMANTIC_DECISION_V1",
            "schema_version": "sealed-evidence-extraction-job.v2",
            "source_files": source_files,
            "study": {"doi": doi, "study_id": study_id},
            "visual_crops": [],
        }
        _persist_prepare_packet(project, study_id, job)
    except (_PrepareNotReady, PageCatalogError) as exc:
        return {
            "command": "prepare-study",
            "reason_code": exc.code,
            "status": "NOT_READY",
            "study_id": study_id,
        }
    return {
        "command": "prepare-study",
        "outputs": {
            "atom_catalog": f"01_evidence/{study_id}/atom_catalog.json",
            "sealed_job": f"01_evidence/{study_id}/sealed_job.json",
        },
        "reason_code": "PRE_PROVIDER_PACKET_READY",
        "status": "READY",
        "study_id": study_id,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline vertical review projection.")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--review-root", type=Path, required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--brief", type=Path, required=True)

    prepare = commands.add_parser("prepare-study")
    prepare.add_argument("--project-dir", type=Path, required=True)
    prepare.add_argument("--study-id", required=True)

    batch = commands.add_parser("prepare-batch")
    batch.add_argument("--project-dir", type=Path, required=True)
    batch.add_argument("--study-ids-file", type=Path, required=True)

    register = commands.add_parser("register-study")
    register.add_argument("--project-dir", type=Path, required=True)
    register.add_argument("--candidate", type=Path, required=True)
    register.add_argument("--r0-report", type=Path, required=True)
    register.add_argument("--reviewer", type=Path, required=True)

    risk = commands.add_parser("build-risk-packet")
    risk.add_argument("--project-dir", type=Path, required=True)

    apply = commands.add_parser("apply-risk-decisions")
    apply.add_argument("--project-dir", type=Path, required=True)
    apply.add_argument("--decisions", type=Path, required=True)

    writer = commands.add_parser("build-writer-packet")
    writer.add_argument("--project-dir", type=Path, required=True)

    metrics = commands.add_parser("metrics")
    metrics.add_argument("--project-dir", type=Path, required=True)
    metrics.add_argument("--output", type=Path, required=True)
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "init":
        project = initialize_review(args.review_root, args.project_id, _load_json(args.brief))
        state = _load_json(project / "00_brief" / "review_state.json")
        _print_summary(
            {"command": "init", "project_dir": str(project), "status": state["status"]}
        )
        return 0
    if args.command == "prepare-study":
        summary = _prepare_status(args.project_dir, args.study_id)
        _print_summary(summary)
        return 0 if summary["status"] == "READY" else 3
    if args.command == "prepare-batch":
        study_ids = [line.strip() for line in args.study_ids_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not study_ids or len(study_ids) != len(set(study_ids)):
            raise VerticalReviewError(
                "STUDY_IDS_INVALID",
                "study IDs must be nonempty and unique",
            )
        studies = [_prepare_status(args.project_dir, study_id) for study_id in study_ids]
        ready_count = sum(row["status"] == "READY" for row in studies)
        summary = {
            "command": "prepare-batch",
            "not_ready_count": len(studies) - ready_count,
            "ready_count": ready_count,
            "status": "READY" if ready_count == len(studies) else "NOT_READY",
            "studies": [
                {key: row[key] for key in ("outputs", "reason_code", "status", "study_id") if key in row}
                for row in studies
            ],
        }
        _print_summary(summary)
        return 0 if summary["status"] == "READY" else 3
    if args.command == "register-study":
        result = register_study(
            args.project_dir,
            _load_json(args.candidate),
            _load_json(args.r0_report),
            _load_json(args.reviewer),
        )
        summary = {
            "command": "register-study",
            "status": "REGISTERED",
            "study_id": result["study_id"],
            **_decision_counts(result["claim_projection"]),
        }
        _print_summary(summary)
        return 0
    if args.command == "build-risk-packet":
        packet = build_risk_packet(args.project_dir)
        _print_summary(
            {
                "command": "build-risk-packet",
                "human_required_count": packet["human_required_count"],
                "low_risk_sample_count": packet["low_risk_sample_count"],
                "status": "BUILT",
                "target_count": packet["target_count"],
            }
        )
        return 0
    if args.command == "apply-risk-decisions":
        projection = apply_risk_decisions(args.project_dir, _load_json(args.decisions))
        _print_summary(
            {
                "command": "apply-risk-decisions",
                "status": "APPLIED",
                **_decision_counts(projection),
            }
        )
        return 0
    if args.command == "build-writer-packet":
        packet = build_writer_packet(args.project_dir)
        _print_summary(
            {
                "approved_claim_count": packet["approved_claim_count"],
                "blocked_count": packet["blocked_count"],
                "command": "build-writer-packet",
                "human_required_count": packet["human_required_count"],
                "status": "BUILT",
            }
        )
        return 0
    if args.command == "metrics":
        project = args.project_dir.resolve()
        output = args.output.resolve()
        try:
            output.relative_to(project)
        except ValueError:
            pass
        else:
            raise VerticalReviewError(
                "METRICS_OUTPUT_INSIDE_PROJECT",
                "metrics output must remain outside project persistence",
            )
        metrics = benchmark_metrics(args.project_dir)
        _atomic_write_json(args.output, metrics)
        _print_summary({"command": "metrics", "status": "WRITTEN", **metrics})
        return 0
    raise VerticalReviewError("COMMAND_INVALID", "unsupported command")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except VerticalReviewError as exc:
        _print_summary(
            {"command": args.command, "error_code": exc.code, "status": "ERROR"},
            stream=sys.stderr,
        )
        return 2
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        _print_summary(
            {"command": args.command, "error_code": "INPUT_OR_IO_INVALID", "status": "ERROR"},
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
