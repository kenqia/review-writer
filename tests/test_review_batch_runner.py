from __future__ import annotations

import json
import multiprocessing
import shutil
from pathlib import Path
from typing import Any

import pytest

from review_writer.project.batch_runner import BatchRunnerError, run_batch
from review_writer.project.vertical_review import initialize_review
from scripts.evidence.build_page_atom_catalog import build_page_atom_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/scaled_vertical_review"


def _expected_sealed_job_id(job: dict[str, Any]) -> str:
    import hashlib

    source_files = [
        {
            key: source[key]
            for key in (
                "document_role",
                "layout_sha256",
                "reading_order_sha256",
                "source_binary_sha256",
                "source_id",
            )
        }
        for source in job["source_files"]
    ]
    source_files.sort(key=lambda row: (row["document_role"], row["source_id"]))
    payload = {
        "mode": job["mode"],
        "schema_version": job["schema_version"],
        "semantic_target_contract": job["semantic_target_contract"],
        "source_files": source_files,
        "study": job["study"],
        "target_namespace": job.get("target_namespace"),
    }
    return "JOB-" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepared_project(
    tmp_path: Path,
    fixture_name: str = "study-a",
    *,
    project_id: str = "batch-review",
) -> tuple[Path, str]:
    project = initialize_review(tmp_path, project_id, {"topic": "Batch review"})
    fixture = FIXTURE_ROOT / fixture_name
    job = _read_json(fixture / "extraction_job.json")
    study_id = job["study"]["study_id"]
    study_root = project / "01_evidence" / study_id
    shutil.copytree(fixture / "sources", study_root / "sources")
    for source in job["source_files"]:
        for field in ("reading_order_path", "layout_path"):
            source[field] = f"01_evidence/{study_id}/{source[field]}"
    job_path = study_root / "sealed_job.json"
    _write_json(job_path, job)
    _write_json(study_root / "atom_catalog.json", build_page_atom_catalog(job_path, project))
    return project, study_id


def _copy_provider_outputs(
    project: Path,
    study_id: str,
    fixture_name: str = "study-a",
    *,
    semantic: bool = True,
    reviewer: bool = True,
) -> tuple[Path | None, Path | None]:
    fixture = FIXTURE_ROOT / fixture_name
    study_root = project / "01_evidence" / study_id
    semantic_path = study_root / "semantic_decisions.json"
    reviewer_path = study_root / "adversarial_verdict.json"
    if semantic:
        shutil.copyfile(fixture / "semantic_decision.json", semantic_path)
    if reviewer:
        payload = _read_json(fixture / "adversarial_verdict.json")
        semantic_payload = _read_json(fixture / "semantic_decision.json")
        payload["findings"] = [
            {
                "reason": "The atom-bound evidence supports this target.",
                "target_id": row["target_id"],
                "verdict": "SUPPORT",
            }
            for row in semantic_payload["decisions"]
            if row["target_kind"] != "ELIGIBILITY"
        ]
        candidate_path = study_root / "evidence_candidate.json"
        if candidate_path.is_file():
            payload["candidate_sha256"] = _sha256(candidate_path)
        _write_json(reviewer_path, payload)
    return (semantic_path if semantic else None, reviewer_path if reviewer else None)


def _prepare_ready(study_id: str) -> dict[str, str]:
    return {
        "reason_code": "PRE_PROVIDER_PACKET_READY",
        "status": "READY",
        "study_id": study_id,
    }


def _hold_batch_run(
    project: str,
    study_id: str,
    entered: Any,
    release: Any,
) -> None:
    def hold_prepare(value: str) -> dict[str, str]:
        entered.set()
        if not release.wait(timeout=10):
            raise TimeoutError("batch lock contention test was not released")
        return _prepare_ready(value)

    run_batch(Path(project), [study_id], prepare_study=hold_prepare)


def _project_bytes(project: Path) -> dict[str, bytes]:
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_missing_semantic_output_waits_without_fabricating_provider_or_usage_data(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)

    summary = run_batch(
        project,
        [study_id],
        prepare_study=_prepare_ready,
        forecast_credits=120,
    )

    study = summary["studies"][0]
    study_root = project / "01_evidence" / study_id
    assert summary["status"] == "WAITING_FOR_PROVIDER"
    assert (study["stage"], study["reason_code"]) == (
        "WAITING_FOR_PROVIDER",
        "SEMANTIC_OUTPUT_MISSING",
    )
    assert study["last_completed_stage"] == "PREPARED"
    assert study["sealed_job_sha256"] == _sha256(study_root / "sealed_job.json")
    assert study["atom_catalog_sha256"] == _sha256(study_root / "atom_catalog.json")
    assert summary["credits"] == {
        "forecast": {"estimated_credits": 120},
        "measured": None,
    }
    assert not (study_root / "semantic_decisions.json").exists()
    assert not (study_root / "adversarial_verdict.json").exists()
    assert not (study_root / "evidence_candidate.json").exists()
    assert not (study_root / "r0_report.json").exists()
    assert _read_json(study_root / "batch_state.json") == study
    assert _read_json(project / "01_evidence/batch_progress.json") == summary


def test_project_lock_rejects_real_cross_process_batch_contention(tmp_path: Path) -> None:
    project, study_id = _prepared_project(tmp_path)
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_batch_run,
        args=(str(project), study_id, entered, release),
    )
    process.start()
    try:
        assert entered.wait(timeout=10), "first batch process did not enter prepare"
        with pytest.raises(BatchRunnerError) as raised:
            run_batch(project, [study_id], prepare_study=_prepare_ready)
        assert raised.value.code == "BATCH_ALREADY_RUNNING"
    finally:
        release.set()
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0


def test_separate_batch_calls_merge_studies_deterministically_in_progress(
    tmp_path: Path,
) -> None:
    project, first_study_id = _prepared_project(tmp_path, "study-a")
    first = run_batch(project, [first_study_id], prepare_study=_prepare_ready)
    first_state = first["studies"][0]

    fixture = FIXTURE_ROOT / "study-b"
    job = _read_json(fixture / "extraction_job.json")
    second_study_id = job["study"]["study_id"]
    second_root = project / "01_evidence" / second_study_id
    shutil.copytree(fixture / "sources", second_root / "sources")
    for source in job["source_files"]:
        for field in ("reading_order_path", "layout_path"):
            source[field] = f"01_evidence/{second_study_id}/{source[field]}"
    second_job_path = second_root / "sealed_job.json"
    _write_json(second_job_path, job)
    _write_json(
        second_root / "atom_catalog.json",
        build_page_atom_catalog(second_job_path, project),
    )

    second = run_batch(project, [second_study_id], prepare_study=_prepare_ready)

    assert [row["study_id"] for row in second["studies"]] == sorted(
        [first_study_id, second_study_id]
    )
    assert next(
        row for row in second["studies"] if row["study_id"] == first_study_id
    ) == first_state
    assert _read_json(project / "01_evidence/batch_progress.json") == second


def test_resume_from_semantic_wait_skips_prepare_when_prepared_inputs_are_unchanged(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    first = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert first["studies"][0]["reason_code"] == "SEMANTIC_OUTPUT_MISSING"
    prepare_calls: list[str] = []

    second = run_batch(
        project,
        [study_id],
        prepare_study=lambda value: prepare_calls.append(value) or _prepare_ready(value),
    )

    assert second["studies"][0] == first["studies"][0]
    assert prepare_calls == []


def test_resume_from_semantic_wait_fails_closed_when_prepared_inputs_drift(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    first = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert first["studies"][0]["reason_code"] == "SEMANTIC_OUTPUT_MISSING"
    study_root = project / "01_evidence" / study_id
    catalog_path = study_root / "atom_catalog.json"
    catalog_bytes = catalog_path.read_bytes()
    catalog = _read_json(catalog_path)
    catalog["study_id"] = "DRIFTED-STUDY"
    _write_json(catalog_path, catalog)
    prepare_calls: list[str] = []

    second = run_batch(
        project,
        [study_id],
        prepare_study=lambda value: prepare_calls.append(value) or _prepare_ready(value),
    )

    assert second["status"] == "BLOCKED"
    assert second["studies"][0]["reason_code"] == "RESUME_BINDING_INVALID"
    assert second["studies"][0]["last_completed_stage"] == "PREPARED"
    assert prepare_calls == []
    assert catalog_path.read_bytes() != catalog_bytes
    assert not (study_root / "evidence_candidate.json").exists()
    assert not (study_root / "r0_report.json").exists()


def test_persisted_state_rejects_cross_project_and_cross_study_copy(
    tmp_path: Path,
) -> None:
    source_project, study_id = _prepared_project(tmp_path / "source", project_id="source-review")
    source = run_batch(source_project, [study_id], prepare_study=_prepare_ready)
    assert source["studies"][0]["project_id"] == "source-review"
    source_root = source_project / "01_evidence" / study_id

    target_project, target_study_id = _prepared_project(
        tmp_path / "target", project_id="target-review"
    )
    target_root = target_project / "01_evidence" / target_study_id
    shutil.copyfile(source_root / "batch_state.json", target_root / "batch_state.json")
    project_calls: list[str] = []

    cross_project = run_batch(
        target_project,
        [target_study_id],
        prepare_study=lambda value: project_calls.append(value) or _prepare_ready(value),
    )

    assert cross_project["studies"][0]["reason_code"] == "RESUME_BINDING_INVALID"
    assert project_calls == []

    copied_study_id = "COPIED-STUDY"
    copied_root = source_project / "01_evidence" / copied_study_id
    shutil.copytree(source_root, copied_root)
    study_calls: list[str] = []

    cross_study = run_batch(
        source_project,
        [copied_study_id],
        prepare_study=lambda value: study_calls.append(value) or _prepare_ready(value),
    )

    assert cross_study["studies"][0]["reason_code"] == "RESUME_BINDING_INVALID"
    assert study_calls == []


def test_resume_without_credit_arguments_preserves_existing_measurement_and_forecast(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    first = run_batch(
        project,
        [study_id],
        prepare_study=_prepare_ready,
        credits_before=400,
        credits_after=373,
        forecast_credits=80,
    )

    second = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert second["credits"] == first["credits"] == {
        "forecast": {"estimated_credits": 80},
        "measured": {"after": 373, "before": 400, "consumed": 27},
    }
    assert _read_json(project / "01_evidence/batch_progress.json")["credits"] == first["credits"]


def test_resume_updates_only_the_credit_value_explicitly_provided(tmp_path: Path) -> None:
    project, study_id = _prepared_project(tmp_path)
    run_batch(
        project,
        [study_id],
        prepare_study=_prepare_ready,
        credits_before=400,
        credits_after=373,
        forecast_credits=80,
    )

    forecast_updated = run_batch(
        project,
        [study_id],
        prepare_study=_prepare_ready,
        forecast_credits=90,
    )
    measured_updated = run_batch(
        project,
        [study_id],
        prepare_study=_prepare_ready,
        credits_before=373,
        credits_after=360,
    )

    assert forecast_updated["credits"] == {
        "forecast": {"estimated_credits": 90},
        "measured": {"after": 373, "before": 400, "consumed": 27},
    }
    assert measured_updated["credits"] == {
        "forecast": {"estimated_credits": 90},
        "measured": {"after": 360, "before": 400, "consumed": 40},
    }


@pytest.mark.parametrize(
    ("credits_before", "credits_after"),
    ((372, 360), (373, 374)),
)
def test_measured_credits_reject_non_monotonic_resume_without_changing_progress(
    tmp_path: Path,
    credits_before: int,
    credits_after: int,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    first = run_batch(
        project,
        [study_id],
        prepare_study=_prepare_ready,
        credits_before=400,
        credits_after=373,
    )
    progress_path = project / "01_evidence/batch_progress.json"
    progress_bytes = progress_path.read_bytes()

    with pytest.raises(BatchRunnerError) as raised:
        run_batch(
            project,
            [study_id],
            prepare_study=_prepare_ready,
            credits_before=credits_before,
            credits_after=credits_after,
        )

    assert raised.value.code == "MEASURED_CREDITS_INVALID"
    assert progress_path.read_bytes() == progress_bytes
    assert first["credits"]["measured"] == {
        "after": 373,
        "before": 400,
        "consumed": 27,
    }


@pytest.mark.parametrize("invalid_forecast", (float("nan"), float("inf"), float("-inf")))
def test_forecast_credits_must_be_finite_before_any_study_is_advanced(
    tmp_path: Path,
    invalid_forecast: float,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    prepare_calls: list[str] = []

    with pytest.raises(BatchRunnerError) as raised:
        run_batch(
            project,
            [study_id],
            prepare_study=lambda value: prepare_calls.append(value) or _prepare_ready(value),
            forecast_credits=invalid_forecast,
        )

    assert raised.value.code == "FORECAST_CREDITS_INVALID"
    assert prepare_calls == []
    assert not (project / "01_evidence/batch_progress.json").exists()


def test_semantic_output_is_assembled_and_freshly_validated_before_reviewer_wait(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    semantic_bytes = semantic_path.read_bytes()

    summary = run_batch(project, [study_id], prepare_study=_prepare_ready)

    study = summary["studies"][0]
    assert (study["stage"], study["reason_code"]) == (
        "WAITING_FOR_PROVIDER",
        "REVIEWER_OUTPUT_MISSING",
    )
    assert study["last_completed_stage"] == "R0_PASS"
    study_root = project / "01_evidence" / study_id
    assert _read_json(study_root / "r0_report.json")["status"] == "R0_PASS"
    assert (study_root / "evidence_candidate.json").is_file()
    assert semantic_path.read_bytes() == semantic_bytes
    assert not (study_root / "adversarial_verdict.json").exists()
    assert summary["credits"] == {"forecast": None, "measured": None}


def test_candidate_stage_and_r0_failure_resume_from_bound_prepared_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.batch_runner as batch_runner

    project, study_id = _prepared_project(tmp_path)
    _copy_provider_outputs(project, study_id, reviewer=False)
    original_validate = batch_runner.validate_evidence_candidate

    def interrupted(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic interruption after candidate assembly")

    monkeypatch.setattr(batch_runner, "validate_evidence_candidate", interrupted)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        run_batch(project, [study_id], prepare_study=_prepare_ready)
    study_root = project / "01_evidence" / study_id
    interrupted_state = _read_json(study_root / "batch_state.json")
    assert interrupted_state["last_completed_stage"] == "CANDIDATE_ASSEMBLED"
    assert interrupted_state["sealed_job_sha256"] == _sha256(study_root / "sealed_job.json")
    assert interrupted_state["atom_catalog_sha256"] == _sha256(study_root / "atom_catalog.json")

    monkeypatch.setattr(batch_runner, "validate_evidence_candidate", original_validate)
    resumed = run_batch(
        project,
        [study_id],
        prepare_study=lambda value: (_ for _ in ()).throw(
            AssertionError(f"prepare repeated for {value}")
        ),
    )
    assert resumed["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"

    fail_project, fail_study_id = _prepared_project(tmp_path / "r0-fail")
    _copy_provider_outputs(fail_project, fail_study_id, reviewer=False)

    def fail_r0(*args: object, **kwargs: object) -> object:
        report = original_validate(*args, **kwargs)
        report["status"] = "R0_FAIL"
        return report

    monkeypatch.setattr(batch_runner, "validate_evidence_candidate", fail_r0)
    failed = run_batch(fail_project, [fail_study_id], prepare_study=_prepare_ready)
    fail_root = fail_project / "01_evidence" / fail_study_id
    assert failed["studies"][0]["last_completed_stage"] == "CANDIDATE_ASSEMBLED"
    assert failed["studies"][0]["sealed_job_sha256"] == _sha256(fail_root / "sealed_job.json")
    assert failed["studies"][0]["atom_catalog_sha256"] == _sha256(fail_root / "atom_catalog.json")
    prepare_calls: list[str] = []

    failed_again = run_batch(
        fail_project,
        [fail_study_id],
        prepare_study=lambda value: prepare_calls.append(value) or _prepare_ready(value),
    )

    assert failed_again["studies"][0]["last_completed_stage"] == "CANDIDATE_ASSEMBLED"
    assert prepare_calls == []


def test_provider_cannot_select_a_claim_denied_by_required_si_contract(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    semantic = _read_json(semantic_path)
    blocked = next(
        row["target_id"] for row in semantic["decisions"] if row["target_kind"] == "CLAIM"
    )
    job_path = project / f"01_evidence/{study_id}/sealed_job.json"
    job = _read_json(job_path)
    job["semantic_target_contract"] = {
        "allowed_target_kinds": ["ELIGIBILITY", "REACTION_UNIT", "CLAIM"],
        "denied_claim_ids": [blocked],
        "policy": "ALLOW_EXCEPT_DECLARED_SI_DEPENDENT_CLAIMS",
    }
    job["job_id"] = _expected_sealed_job_id(job)
    semantic["job_id"] = job["job_id"]
    _write_json(job_path, job)
    _write_json(semantic_path, semantic)
    _write_json(
        project / f"01_evidence/{study_id}/atom_catalog.json",
        build_page_atom_catalog(job_path, project),
    )
    semantic_bytes = semantic_path.read_bytes()

    summary = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert summary["status"] == "BLOCKED"
    study_root = project / "01_evidence" / study_id
    assert summary["studies"] == [
        {
            "atom_catalog_sha256": _sha256(study_root / "atom_catalog.json"),
            "last_completed_stage": "PREPARED",
            "project_id": "batch-review",
            "reason_code": "BLOCKED_CLAIM_SELECTED",
            "sealed_job_sha256": _sha256(study_root / "sealed_job.json"),
            "stage": "BLOCKED",
            "study_id": study_id,
        }
    ]
    assert semantic_path.read_bytes() == semantic_bytes
    assert not (study_root / "evidence_candidate.json").exists()
    assert not (study_root / "r0_report.json").exists()


def test_v2_job_without_semantic_target_contract_is_rejected_before_assembly(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    job_path = project / f"01_evidence/{study_id}/sealed_job.json"
    job = _read_json(job_path)
    job.pop("semantic_target_contract", None)
    _write_json(job_path, job)
    _write_json(
        project / f"01_evidence/{study_id}/atom_catalog.json",
        build_page_atom_catalog(job_path, project),
    )

    summary = run_batch(project, [study_id], prepare_study=_prepare_ready)
    study_root = project / "01_evidence" / study_id

    assert summary["studies"] == [
        {
            "atom_catalog_sha256": _sha256(study_root / "atom_catalog.json"),
            "last_completed_stage": "PREPARED",
            "project_id": "batch-review",
            "reason_code": "SEMANTIC_TARGET_CONTRACT_INVALID",
            "sealed_job_sha256": _sha256(study_root / "sealed_job.json"),
            "stage": "BLOCKED",
            "study_id": study_id,
        }
    ]
    assert not (project / f"01_evidence/{study_id}/evidence_candidate.json").exists()
    prepare_calls: list[str] = []

    retried = run_batch(
        project,
        [study_id],
        prepare_study=lambda value: prepare_calls.append(value) or _prepare_ready(value),
    )

    assert retried["studies"][0]["reason_code"] == "SEMANTIC_TARGET_CONTRACT_INVALID"
    assert prepare_calls == []


def test_old_semantic_job_id_is_rejected_after_the_sealed_binding_changes(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    old_semantic_bytes = semantic_path.read_bytes()
    job_path = project / f"01_evidence/{study_id}/sealed_job.json"
    job = _read_json(job_path)
    job["semantic_target_contract"]["denied_claim_ids"] = ["CLAIM-NEWLY-DENIED"]
    job["job_id"] = _expected_sealed_job_id(job)
    _write_json(job_path, job)
    _write_json(
        project / f"01_evidence/{study_id}/atom_catalog.json",
        build_page_atom_catalog(job_path, project),
    )

    summary = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert summary["studies"][0]["reason_code"] == "SEMANTIC_JOB_MISMATCH"
    assert semantic_path.read_bytes() == old_semantic_bytes
    assert not (project / f"01_evidence/{study_id}/evidence_candidate.json").exists()


@pytest.mark.parametrize("binding", ("source", "contract"))
def test_assembly_rejects_tampered_sealed_bindings_with_the_old_job_id(
    tmp_path: Path,
    binding: str,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    job_path = project / f"01_evidence/{study_id}/sealed_job.json"
    job = _read_json(job_path)
    if binding == "source":
        job["source_files"][0]["source_binary_sha256"] = "0" * 64
    else:
        job["semantic_target_contract"]["denied_claim_ids"] = ["CLAIM-NOT-SELECTED"]
    _write_json(job_path, job)
    _write_json(
        project / f"01_evidence/{study_id}/atom_catalog.json",
        build_page_atom_catalog(job_path, project),
    )

    summary = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert summary["studies"][0]["reason_code"] == "JOB_BINDING_INVALID"
    assert not (project / f"01_evidence/{study_id}/evidence_candidate.json").exists()


def test_complete_provider_outputs_register_once_and_resume_idempotently(tmp_path: Path) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    waiting = run_batch(
        project,
        [study_id],
        prepare_study=_prepare_ready,
        credits_before=400,
        credits_after=373,
        forecast_credits=80,
    )
    assert waiting["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"
    _, reviewer_path = _copy_provider_outputs(project, study_id, semantic=False, reviewer=True)
    assert reviewer_path is not None
    provider_bytes = (semantic_path.read_bytes(), reviewer_path.read_bytes())

    first = run_batch(
        project,
        [study_id],
        prepare_study=_prepare_ready,
    )

    assert first["status"] == "COMPLETE"
    assert first["studies"][0]["stage"] == "REGISTERED"
    assert first["credits"] == {
        "forecast": {"estimated_credits": 80},
        "measured": {"after": 373, "before": 400, "consumed": 27},
    }
    stable = _project_bytes(project)
    prepare_calls: list[str] = []

    second = run_batch(
        project,
        [study_id],
        prepare_study=lambda value: prepare_calls.append(value) or _prepare_ready(value),
    )

    assert second == first
    assert prepare_calls == []
    assert _project_bytes(project) == stable
    assert (semantic_path.read_bytes(), reviewer_path.read_bytes()) == provider_bytes
    cards = [
        json.loads(line)
        for line in (project / "01_evidence/evidence_cards.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert [row["study_id"] for row in cards] == [study_id]


def test_resume_from_reviewer_wait_skips_prepare_and_assembly_but_revalidates_r0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.batch_runner as batch_runner

    project, study_id = _prepared_project(tmp_path)
    _copy_provider_outputs(project, study_id, reviewer=False)
    first = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert first["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"
    study_root = project / "01_evidence" / study_id
    deterministic_bytes = (
        (study_root / "evidence_candidate.json").read_bytes(),
        (study_root / "r0_report.json").read_bytes(),
    )
    _copy_provider_outputs(project, study_id, semantic=False, reviewer=True)
    original_validate = batch_runner.validate_evidence_candidate
    validation_calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("completed deterministic stage was repeated")

    def recording_validate(*args: object, **kwargs: object) -> object:
        validation_calls.append("fresh-r0")
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(batch_runner, "_assemble_candidate", forbidden)
    monkeypatch.setattr(batch_runner, "validate_evidence_candidate", recording_validate)

    second = run_batch(
        project,
        [study_id],
        prepare_study=lambda value: forbidden(value),
    )

    assert second["status"] == "COMPLETE"
    assert second["studies"][0]["stage"] == "REGISTERED"
    assert validation_calls == ["fresh-r0"]
    assert (
        (study_root / "evidence_candidate.json").read_bytes(),
        (study_root / "r0_report.json").read_bytes(),
    ) == deterministic_bytes


def test_r0_resume_fails_closed_when_fresh_read_only_validation_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.batch_runner as batch_runner

    project, study_id = _prepared_project(tmp_path)
    _copy_provider_outputs(project, study_id, reviewer=False)
    first = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert first["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"
    study_root = project / "01_evidence" / study_id
    deterministic_bytes = (
        (study_root / "evidence_candidate.json").read_bytes(),
        (study_root / "r0_report.json").read_bytes(),
    )
    changed = _read_json(study_root / "r0_report.json")
    changed["validation_summary"] = "fresh validation differs"
    monkeypatch.setattr(batch_runner, "validate_evidence_candidate", lambda *args: changed)
    monkeypatch.setattr(
        batch_runner,
        "_assemble_candidate",
        lambda *args: (_ for _ in ()).throw(AssertionError("candidate was reassembled")),
    )

    resumed = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert resumed["studies"][0]["reason_code"] == "RESUME_BINDING_INVALID"
    assert (
        (study_root / "evidence_candidate.json").read_bytes(),
        (study_root / "r0_report.json").read_bytes(),
    ) == deterministic_bytes


def test_r0_resume_fails_closed_when_bound_atom_catalog_drifts(tmp_path: Path) -> None:
    project, study_id = _prepared_project(tmp_path)
    _copy_provider_outputs(project, study_id, reviewer=False)
    first = run_batch(project, [study_id], prepare_study=_prepare_ready)
    study_root = project / "01_evidence" / study_id
    catalog_path = study_root / "atom_catalog.json"
    assert first["studies"][0]["atom_catalog_sha256"] == _sha256(catalog_path)
    deterministic_bytes = (
        (study_root / "evidence_candidate.json").read_bytes(),
        (study_root / "r0_report.json").read_bytes(),
    )
    catalog = _read_json(catalog_path)
    catalog["study_id"] = "DRIFTED-AFTER-R0"
    _write_json(catalog_path, catalog)

    resumed = run_batch(
        project,
        [study_id],
        prepare_study=lambda value: (_ for _ in ()).throw(
            AssertionError(f"prepare repeated for {value}")
        ),
    )

    assert resumed["studies"][0]["reason_code"] == "RESUME_BINDING_INVALID"
    assert resumed["studies"][0]["last_completed_stage"] == "R0_PASS"
    assert (
        (study_root / "evidence_candidate.json").read_bytes(),
        (study_root / "r0_report.json").read_bytes(),
    ) == deterministic_bytes


def test_reviewer_must_bind_the_current_candidate_content_before_registration(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    first = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert first["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"
    _, reviewer_path = _copy_provider_outputs(project, study_id, semantic=False, reviewer=True)
    assert reviewer_path is not None
    reviewer = _read_json(reviewer_path)
    reviewer["candidate_sha256"] = "0" * 64
    _write_json(reviewer_path, reviewer)
    provider_bytes = (semantic_path.read_bytes(), reviewer_path.read_bytes())

    summary = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert summary["status"] == "BLOCKED"
    assert summary["studies"][0]["reason_code"] == "REVIEWER_CANDIDATE_BINDING_INVALID"
    assert not (project / "01_evidence/evidence_cards.jsonl").read_text().strip()
    assert (semantic_path.read_bytes(), reviewer_path.read_bytes()) == provider_bytes


def test_corrected_invalid_reviewer_resumes_from_r0_without_repeating_completed_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import review_writer.project.batch_runner as batch_runner

    project, study_id = _prepared_project(tmp_path)
    _copy_provider_outputs(project, study_id, reviewer=False)
    first = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert first["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"
    _, reviewer_path = _copy_provider_outputs(project, study_id, semantic=False, reviewer=True)
    assert reviewer_path is not None
    reviewer = _read_json(reviewer_path)
    reviewer["verdict"] = "ACCEPT_WITH_NOTES"
    _write_json(reviewer_path, reviewer)

    second = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert second["studies"][0]["reason_code"] == "REVIEWER_VERDICT_INVALID"
    assert second["studies"][0]["last_completed_stage"] == "R0_PASS"

    reviewer["verdict"] = "SUPPORT"
    _write_json(reviewer_path, reviewer)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("completed prepare, assembly, or R0 stage was repeated")

    monkeypatch.setattr(batch_runner, "_assemble_candidate", forbidden)
    third = run_batch(
        project,
        [study_id],
        prepare_study=lambda value: forbidden(value),
    )

    assert third["status"] == "COMPLETE"
    assert third["studies"][0]["stage"] == "REGISTERED"


def test_resume_rejects_candidate_drift_before_consuming_bound_reviewer_output(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    first = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert first["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"
    _, reviewer_path = _copy_provider_outputs(project, study_id, semantic=False, reviewer=True)
    assert reviewer_path is not None
    reviewer_bytes = reviewer_path.read_bytes()
    study_root = project / "01_evidence" / study_id
    candidate_path = study_root / "evidence_candidate.json"
    candidate = _read_json(candidate_path)
    candidate["claims"][0]["claim_text"] += " Drifted after review."
    _write_json(candidate_path, candidate)

    summary = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert summary["status"] == "BLOCKED"
    assert summary["studies"][0]["reason_code"] == "RESUME_BINDING_INVALID"
    assert summary["studies"][0]["last_completed_stage"] == "R0_PASS"
    assert reviewer_path.read_bytes() == reviewer_bytes
    assert not (project / "01_evidence/evidence_cards.jsonl").read_text().strip()


def test_resume_rejects_semantic_drift_without_overwriting_deterministic_outputs(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    first = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert first["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"
    study_root = project / "01_evidence" / study_id
    deterministic_bytes = (
        (study_root / "evidence_candidate.json").read_bytes(),
        (study_root / "r0_report.json").read_bytes(),
    )
    semantic = _read_json(semantic_path)
    semantic["decisions"][0]["statement"] += " Drifted after R0."
    _write_json(semantic_path, semantic)

    second = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert second["status"] == "BLOCKED"
    assert second["studies"][0]["reason_code"] == "RESUME_BINDING_INVALID"
    assert (
        (study_root / "evidence_candidate.json").read_bytes(),
        (study_root / "r0_report.json").read_bytes(),
    ) == deterministic_bytes


def test_reviewer_target_ids_must_exactly_cover_candidate_without_registration(
    tmp_path: Path,
) -> None:
    project, study_id = _prepared_project(tmp_path)
    semantic_path, _ = _copy_provider_outputs(project, study_id, reviewer=False)
    assert semantic_path is not None
    waiting = run_batch(project, [study_id], prepare_study=_prepare_ready)
    assert waiting["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"
    _, reviewer_path = _copy_provider_outputs(project, study_id, semantic=False, reviewer=True)
    assert reviewer_path is not None
    reviewer = _read_json(reviewer_path)
    reviewer["findings"][0]["target_id"] = "UNKNOWN-TARGET"
    _write_json(reviewer_path, reviewer)
    provider_bytes = (semantic_path.read_bytes(), reviewer_path.read_bytes())

    summary = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert summary["status"] == "BLOCKED"
    assert (summary["studies"][0]["stage"], summary["studies"][0]["reason_code"]) == (
        "BLOCKED",
        "REVIEWER_TARGETS_INVALID",
    )
    assert not (project / "01_evidence/evidence_cards.jsonl").read_text().strip()
    assert (semantic_path.read_bytes(), reviewer_path.read_bytes()) == provider_bytes


def test_each_deterministic_stage_reloads_the_canonical_project_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import review_writer.project.batch_runner as batch_runner

    project, study_id = _prepared_project(tmp_path)
    _copy_provider_outputs(project, study_id, reviewer=False)
    observed: list[str] = []
    original = batch_runner._load_project_snapshot

    def recording_loader(project_path: Path) -> dict[str, Any]:
        snapshot = original(project_path)
        observed.append(snapshot["project_id"])
        return snapshot

    monkeypatch.setattr(batch_runner, "_load_project_snapshot", recording_loader)

    waiting = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert waiting["studies"][0]["reason_code"] == "REVIEWER_OUTPUT_MISSING"
    assert observed == ["batch-review"] * 3
    observed.clear()
    _copy_provider_outputs(project, study_id, semantic=False, reviewer=True)
    summary = run_batch(project, [study_id], prepare_study=_prepare_ready)

    assert summary["status"] == "COMPLETE"
    assert observed == ["batch-review"] * 3
