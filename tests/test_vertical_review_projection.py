from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from review_writer.project.vertical_review import (
    VerticalReviewError,
    apply_risk_decisions,
    benchmark_metrics,
    build_risk_packet,
    build_writer_packet,
    initialize_review,
    register_study,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "run_vertical_review.py"


def _evidence_ref(study_id: str) -> dict:
    return {
        "source_id": f"SOURCE-{study_id}",
        "page": 1,
        "section_or_item": "Results",
        "exact_quote": "Synthetic source observation.",
    }


def _claim(
    claim_id: str,
    *,
    text: str | None = None,
    risk_level: str = "R1",
    risk_categories: list[str] | None = None,
) -> dict:
    return {
        "claim_id": claim_id,
        "claim_text": text or f"Synthetic claim {claim_id}.",
        "risk_level": risk_level,
        "risk_categories": list(risk_categories or []),
        "evidence_refs": [_evidence_ref(claim_id)],
    }


def _candidate(study_id: str, claims: list[dict]) -> dict:
    return {
        "schema_version": "evidence-candidate.v2",
        "job_id": f"JOB-{study_id}",
        "study_id": study_id,
        "claims": claims,
    }


def _initialize(tmp_path: Path) -> Path:
    return initialize_review(tmp_path, "synthetic-review", {"topic": "Synthetic review"})


def test_r1_supported_grounded_claim_is_approved(tmp_path: Path) -> None:
    project = _initialize(tmp_path)

    card = register_study(
        project,
        _candidate("STUDY-1", [_claim("CLAIM-1")]),
        {"status": "R0_PASS", "findings": []},
        {"verdict": "SUPPORT", "review_id": "REVIEW-1"},
    )

    assert card["study_id"] == "STUDY-1"
    projection = card["claim_projection"]
    assert len(projection) == 1
    assert projection[0]["claim_id"] == "CLAIM-1"
    assert projection[0]["decision"] == "APPROVED"
    assert projection[0]["lineage"]["study_id"] == "STUDY-1"
    assert projection[0]["lineage"]["source_locators"][0]["source_id"] == "SOURCE-CLAIM-1"


def test_r3_supported_claim_requires_human_review(tmp_path: Path) -> None:
    project = _initialize(tmp_path)

    result = register_study(
        project,
        _candidate("STUDY-R3", [_claim("CLAIM-R3", risk_level="R3")]),
        {"status": "R0_PASS"},
        {"verdict": "SUPPORT"},
    )

    assert result["claim_projection"][0]["decision"] == "HUMAN_REQUIRED"


def test_ambiguous_reviewer_blocks_low_risk_claim(tmp_path: Path) -> None:
    project = _initialize(tmp_path)

    result = register_study(
        project,
        _candidate("STUDY-AMBIGUOUS", [_claim("CLAIM-AMBIGUOUS")]),
        {"status": "R0_PASS"},
        {"verdict": "AMBIGUOUS"},
    )

    assert result["claim_projection"][0]["decision"] == "BLOCKED"


def test_writer_packet_is_an_approved_only_whitelist(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    register_study(
        project,
        _candidate("STUDY-APPROVED", [_claim("CLAIM-APPROVED")]),
        {"status": "R0_PASS"},
        {"verdict": "SUPPORT"},
    )
    register_study(
        project,
        _candidate("STUDY-HUMAN", [_claim("CLAIM-HUMAN", risk_level="R3")]),
        {"status": "R0_PASS"},
        {"verdict": "SUPPORT"},
    )
    register_study(
        project,
        _candidate("STUDY-BLOCKED", [_claim("CLAIM-BLOCKED")]),
        {"status": "R0_PASS"},
        {"verdict": "AMBIGUOUS"},
    )

    packet = build_writer_packet(project)

    assert [claim["claim_id"] for claim in packet["claims"]] == ["CLAIM-APPROVED"]
    assert all(claim["decision"] == "APPROVED" for claim in packet["claims"])
    assert packet["approved_claim_count"] == 1
    assert packet["human_required_count"] == 1
    assert packet["blocked_count"] == 1
    assert packet["known_exclusions"]
    assert {row["claim_id"] for row in packet["known_exclusions"]} == {
        "CLAIM-BLOCKED",
        "CLAIM-HUMAN",
    }


@pytest.mark.parametrize(
    "consumer",
    [build_writer_packet, build_risk_packet, benchmark_metrics],
    ids=["writer", "risk", "metrics"],
)
@pytest.mark.parametrize("tamper", ["forged", "text", "lineage"])
def test_projection_consumers_reject_any_non_authoritative_projection(
    tmp_path: Path,
    consumer,
    tamper: str,
) -> None:
    project = _initialize(tmp_path)
    result = register_study(
        project,
        _candidate("STUDY-TAMPER", [_claim("CLAIM-TAMPER")]),
        {"status": "R0_PASS"},
        {"verdict": "SUPPORT"},
    )
    if tamper == "forged":
        rows = [{"claim_id": "CLAIM-TAMPER", "decision": "APPROVED"}]
    else:
        rows = copy.deepcopy(result["claim_projection"])
        if tamper == "text":
            rows[0]["text"] = "Forged consumer wording."
        else:
            rows[0]["lineage"]["study_id"] = "FORGED-STUDY"
    projection_path = project / "02_claims" / "claim_projection.jsonl"
    projection_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    tampered_bytes = projection_path.read_bytes()

    with pytest.raises(VerticalReviewError) as error:
        consumer(project)

    assert error.value.code == "PROJECTION_INVALID"
    assert projection_path.read_bytes() == tampered_bytes


def test_failed_third_study_is_queued_without_deleting_passing_cards(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    for index in (1, 2):
        register_study(
            project,
            _candidate(f"STUDY-{index}", [_claim(f"CLAIM-{index}")]),
            {"status": "R0_PASS"},
            {"verdict": "SUPPORT"},
        )
    cards_path = project / "01_evidence" / "evidence_cards.jsonl"
    passing_bytes = cards_path.read_bytes()

    with pytest.raises(VerticalReviewError) as error:
        register_study(
            project,
            _candidate("STUDY-BAD", [_claim("CLAIM-BAD")]),
            {"status": "R0_FAIL_GROUNDING_CONTRACT"},
            {"verdict": "SUPPORT"},
        )

    assert error.value.code == "R0_REJECTED"
    assert cards_path.read_bytes() == passing_bytes
    cards = [json.loads(line) for line in passing_bytes.decode("utf-8").splitlines()]
    assert [card["study_id"] for card in cards] == ["STUDY-1", "STUDY-2"]
    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert [entry["study_id"] for entry in queue["exceptions"]] == ["STUDY-BAD"]
    assert queue["exceptions"][0]["error_code"] == "R0_REJECTED"


def test_repeated_failure_upserts_one_exception_per_study(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    for _ in range(2):
        with pytest.raises(VerticalReviewError):
            register_study(
                project,
                _candidate("STUDY-RETRY", [_claim("CLAIM-RETRY")]),
                {"status": "R0_FAIL_GROUNDING_CONTRACT"},
                {"verdict": "SUPPORT"},
            )

    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert queue["exceptions"] == [
        {
            "error_code": "R0_REJECTED",
            "r0_status": "R0_FAIL_GROUNDING_CONTRACT",
            "reviewer_verdict": "SUPPORT",
            "study_id": "STUDY-RETRY",
        }
    ]
    with pytest.raises(VerticalReviewError):
        register_study(
            project,
            _candidate("STUDY-ALPHA", [_claim("CLAIM-ALPHA")]),
            {"status": "R0_FAIL_GROUNDING_CONTRACT"},
            {"verdict": "SUPPORT"},
        )
    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert [entry["study_id"] for entry in queue["exceptions"]] == [
        "STUDY-ALPHA",
        "STUDY-RETRY",
    ]


def test_successful_retry_clears_study_exception_and_metrics(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    candidate = _candidate("STUDY-RECOVERED", [_claim("CLAIM-RECOVERED")])
    with pytest.raises(VerticalReviewError):
        register_study(
            project,
            candidate,
            {"status": "R0_FAIL_GROUNDING_CONTRACT"},
            {"verdict": "SUPPORT"},
        )

    register_study(
        project,
        candidate,
        {"status": "R0_PASS"},
        {"verdict": "SUPPORT"},
    )

    queue = json.loads((project / "01_evidence" / "exception_queue.json").read_text())
    assert queue["exceptions"] == []
    assert benchmark_metrics(project)["exception_count"] == 0


def test_risk_decisions_reduce_to_consumer_text_and_status_only(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    original_text = "Original approved wording."
    register_study(
        project,
        _candidate(
            "STUDY-RISK",
            [
                _claim("CLAIM-APPROVE", text=original_text, risk_level="R3"),
                _claim("CLAIM-REWORD", risk_level="R3"),
                _claim("CLAIM-EXCLUDE", risk_level="R3"),
                _claim("CLAIM-UNRESOLVED", risk_level="R3"),
            ],
        ),
        {"status": "R0_PASS"},
        {"verdict": "SUPPORT"},
    )
    cards_path = project / "01_evidence" / "evidence_cards.jsonl"
    evidence_bytes = cards_path.read_bytes()
    build_risk_packet(project)

    projection = apply_risk_decisions(
        project,
        {
            "decisions": [
                {"claim_id": "CLAIM-APPROVE", "action": "APPROVE"},
                {
                    "claim_id": "CLAIM-REWORD",
                    "action": "REWORD",
                    "approved_text": "Human-approved wording.",
                },
                {"claim_id": "CLAIM-EXCLUDE", "action": "EXCLUDE"},
                {"claim_id": "CLAIM-UNRESOLVED", "action": "UNRESOLVED"},
            ]
        },
    )

    by_id = {row["claim_id"]: row for row in projection}
    assert by_id["CLAIM-APPROVE"]["decision"] == "APPROVED"
    assert by_id["CLAIM-APPROVE"]["text"] == original_text
    assert by_id["CLAIM-REWORD"]["decision"] == "APPROVED"
    assert by_id["CLAIM-REWORD"]["text"] == "Human-approved wording."
    assert by_id["CLAIM-REWORD"]["original_text"] == "Synthetic claim CLAIM-REWORD."
    assert by_id["CLAIM-EXCLUDE"]["decision"] == "BLOCKED"
    assert by_id["CLAIM-UNRESOLVED"]["decision"] == "HUMAN_REQUIRED"
    assert cards_path.read_bytes() == evidence_bytes


@pytest.mark.parametrize(
    ("decisions", "code"),
    [
        (
            {
                "decisions": [
                    {"claim_id": "CLAIM-RISK", "action": "APPROVE"},
                    {"claim_id": "CLAIM-RISK", "action": "EXCLUDE"},
                ]
            },
            "RISK_TARGET_DUPLICATE",
        ),
        (
            {"decisions": [{"claim_id": "CLAIM-UNKNOWN", "action": "APPROVE"}]},
            "RISK_TARGET_UNKNOWN",
        ),
        (
            {"decisions": [{"claim_id": "CLAIM-RISK", "action": "REWORD"}]},
            "APPROVED_TEXT_REQUIRED",
        ),
    ],
)
def test_invalid_risk_decisions_fail_closed(tmp_path: Path, decisions: dict, code: str) -> None:
    project = _initialize(tmp_path)
    register_study(
        project,
        _candidate("STUDY-RISK", [_claim("CLAIM-RISK", risk_level="R3")]),
        {"status": "R0_PASS"},
        {"verdict": "SUPPORT"},
    )
    projection_path = project / "02_claims" / "claim_projection.jsonl"
    projection_bytes = projection_path.read_bytes()

    with pytest.raises(VerticalReviewError) as error:
        apply_risk_decisions(project, decisions)

    assert error.value.code == code
    assert projection_path.read_bytes() == projection_bytes


def test_risk_packet_sampling_is_sha256_stable_and_deduplicated(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    low_risk_ids = [f"CLAIM-LOW-{index:02d}" for index in range(20)]
    register_study(
        project,
        _candidate(
            "STUDY-SAMPLE",
            [
                *[_claim(claim_id) for claim_id in low_risk_ids],
                _claim(
                    "CLAIM-HIGH",
                    risk_level="R1",
                    risk_categories=["STRUCTURE"],
                ),
            ],
        ),
        {"status": "R0_PASS"},
        {"verdict": "SUPPORT"},
    )

    first = build_risk_packet(project, low_risk_sample_rate=0.10)
    risk_path = project / "03_review" / "risk_packet.json"
    first_bytes = risk_path.read_bytes()
    second = build_risk_packet(project, low_risk_sample_rate=0.10)

    expected_sample = sorted(
        low_risk_ids,
        key=lambda claim_id: hashlib.sha256(claim_id.encode("utf-8")).hexdigest(),
    )[:2]
    sampled = [
        row["claim_id"]
        for row in first["targets"]
        if row["selection_reason"] == "LOW_RISK_AUDIT"
    ]
    target_ids = [row["claim_id"] for row in first["targets"]]
    assert sampled == expected_sample
    assert target_ids.count("CLAIM-HIGH") == 1
    assert len(target_ids) == len(set(target_ids))
    assert second == first
    assert risk_path.read_bytes() == first_bytes


def test_register_and_risk_application_never_mutate_input_fixtures(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    fixtures = {
        "candidate": _candidate(
            "STUDY-IMMUTABLE",
            [_claim("CLAIM-IMMUTABLE", risk_level="R3")],
        ),
        "r0": {"status": "R0_PASS", "findings": []},
        "reviewer": {"verdict": "SUPPORT", "review_id": "REVIEW-IMMUTABLE"},
    }
    fixtures["candidate"]["provider_candidate"] = {
        "provider": "synthetic-provider",
        "provider_record_id": "FIXTURE-1",
    }
    paths = {name: tmp_path / f"{name}.json" for name in fixtures}
    for name, path in paths.items():
        path.write_text(json.dumps(fixtures[name], ensure_ascii=False, indent=3) + "\n")
    fixture_bytes = {name: path.read_bytes() for name, path in paths.items()}
    loaded = {name: json.loads(path.read_text()) for name, path in paths.items()}
    loaded_before = copy.deepcopy(loaded)

    register_study(project, loaded["candidate"], loaded["r0"], loaded["reviewer"])
    build_risk_packet(project)
    apply_risk_decisions(
        project,
        {"decisions": [{"claim_id": "CLAIM-IMMUTABLE", "action": "APPROVE"}]},
    )

    assert loaded == loaded_before
    assert {name: path.read_bytes() for name, path in paths.items()} == fixture_bytes
    stored_card = json.loads(
        (project / "01_evidence" / "evidence_cards.jsonl").read_text().splitlines()[0]
    )
    assert stored_card["candidate"] == loaded_before["candidate"]


def test_benchmark_metrics_report_authoritative_projection_counts(tmp_path: Path) -> None:
    project = _initialize(tmp_path)
    register_study(
        project,
        _candidate(
            "STUDY-METRICS",
            [
                _claim("CLAIM-METRICS-APPROVED"),
                _claim("CLAIM-METRICS-HUMAN", risk_level="R3"),
            ],
        ),
        {"status": "R0_PASS"},
        {"verdict": "SUPPORT"},
    )
    with pytest.raises(VerticalReviewError):
        register_study(
            project,
            _candidate("STUDY-METRICS-BAD", [_claim("CLAIM-METRICS-BAD")]),
            {"status": "R0_FAIL_GROUNDING_CONTRACT"},
            {"verdict": "SUPPORT"},
        )

    metrics = benchmark_metrics(project)

    assert metrics == {
        "approved_claim_count": 1,
        "blocked_claim_count": 0,
        "exception_count": 1,
        "human_required_claim_count": 1,
        "project_id": "synthetic-review",
        "projected_claim_count": 2,
        "registered_study_count": 1,
    }


def test_cli_exposes_required_subcommands_and_prepare_creates_no_state(tmp_path: Path) -> None:
    help_result = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    for command in (
        "init",
        "prepare-study",
        "prepare-batch",
        "register-study",
        "build-risk-packet",
        "apply-risk-decisions",
        "build-writer-packet",
        "metrics",
    ):
        assert command in help_result.stdout

    project = _initialize(tmp_path)
    before = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    prepare = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "prepare-study",
            "--project-dir",
            str(project),
            "--study-id",
            "STUDY-NOT-DECLARED",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert prepare.returncode == 3, prepare.stderr
    summary = json.loads(prepare.stdout)
    assert summary == {
        "command": "prepare-study",
        "reason_code": "ACQUISITION_MANIFEST_MISSING",
        "status": "NOT_READY",
        "study_id": "STUDY-NOT-DECLARED",
    }
    study_ids_path = tmp_path / "study-ids.txt"
    study_ids_path.write_text("STUDY-A\nSTUDY-B\n")
    batch = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "prepare-batch",
            "--project-dir",
            str(project),
            "--study-ids-file",
            str(study_ids_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert batch.returncode == 3, batch.stderr
    batch_summary = json.loads(batch.stdout)
    assert batch_summary["status"] == "NOT_READY"
    assert batch_summary["ready_count"] == 0
    assert batch_summary["not_ready_count"] == 2
    assert [row["study_id"] for row in batch_summary["studies"]] == [
        "STUDY-A",
        "STUDY-B",
    ]
    after = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_makefile_has_focused_vertical_projection_gate() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "vertical-review-projection-check:" in makefile
    assert (
        "\t$(PYTHON) -m pytest tests/test_vertical_review_projection.py -q"
        in makefile
    )
