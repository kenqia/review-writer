from __future__ import annotations

import hashlib
import json
import socket
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "scaled_vertical_review"
EVIDENCE_SCRIPTS = REPO_ROOT / "scripts" / "evidence"
if str(EVIDENCE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(EVIDENCE_SCRIPTS))

from assemble_evidence_candidate_from_atoms import (  # noqa: E402
    assemble,
    validate_catalog,
    validate_schema,
)
from scripts.evidence.build_page_atom_catalog import (  # noqa: E402
    build_page_atom_catalog,
    validate_catalog_schema,
)
from scripts.evidence.validate_evidence_candidate import validate as validate_grounding  # noqa: E402

from review_writer.delivery.project_release import build_project_release  # noqa: E402
from review_writer.project.vertical_review import (  # noqa: E402
    apply_risk_decisions,
    benchmark_metrics,
    build_risk_packet,
    build_writer_packet,
    initialize_review,
    register_study,
)
from view.serve_review_dashboard import (  # noqa: E402
    project_draft_payload,
    project_evidence_payload,
    project_final_payload,
    project_risk_payload,
)


BRIEF = {
    "audience": "Researchers evaluating a synthetic evidence workflow",
    "question": "Which grounded observations are safe to include in a neutral review?",
    "review_status": "AI_REVIEWED_BENCHMARK",
    "scope": "Exactly three synthetic studies with MAIN and SI text layers",
    "topic": "Neutral controlled observations",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_path(relative: str) -> Path:
    path = (FIXTURE_ROOT / relative).resolve()
    path.relative_to(FIXTURE_ROOT.resolve())
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_fixture_studies(project: Path) -> dict[str, dict[str, Any]]:
    fixture = _read_json(_fixture_path("studies.json"))
    studies = fixture["studies"]
    assert len(studies) == 3
    assert {path.name for path in FIXTURE_ROOT.glob("study-*") if path.is_dir()} == {
        "study-a",
        "study-b",
        "study-c",
    }

    catalog_schema = _read_json(
        REPO_ROOT / "schemas" / "evidence" / "evidence_atom_catalog.v1.schema.json"
    )
    semantic_schema = _read_json(
        REPO_ROOT
        / "schemas"
        / "evidence"
        / "evidence_atom_semantic_decision.v1.schema.json"
    )
    candidate_schema = _read_json(
        REPO_ROOT / "schemas" / "evidence" / "evidence_candidate.v2.schema.json"
    )

    outputs: dict[str, dict[str, Any]] = {}
    for row in studies:
        study_root = _fixture_path(row["fixture_dir"])
        job_path = study_root / "extraction_job.json"
        job = _read_json(job_path)
        expected_catalog = _read_json(study_root / "atom_catalog.json")
        semantic = _read_json(study_root / "semantic_decision.json")
        reviewer = _read_json(study_root / "adversarial_verdict.json")
        expected = _read_json(study_root / "expected_decision.json")

        assert {source["document_role"] for source in job["source_files"]} == {
            "MAIN",
            "SI",
        }
        catalog = build_page_atom_catalog(job_path, study_root)
        assert catalog == expected_catalog
        validate_catalog_schema(catalog, catalog_schema)
        validate_schema(semantic, semantic_schema, "SEMANTIC_SCHEMA_INVALID")
        atoms = validate_catalog(
            job,
            job_path,
            catalog,
            study_root,
            source_pdfs={},
            renderer=None,
        )
        candidate = assemble(job, catalog, semantic, atoms)
        validate_schema(candidate, candidate_schema, "CANDIDATE_SCHEMA_INVALID")
        r0_report = validate_grounding(job, candidate, study_root, candidate_schema)
        assert r0_report["status"] == "R0_PASS"
        assert r0_report["findings"] == []

        registration = register_study(project, candidate, r0_report, reviewer)
        projected = next(
            claim
            for claim in registration["claim_projection"]
            if claim["claim_id"] == expected["claim_id"]
        )
        assert projected["study_id"] == expected["study_id"] == row["study_id"]
        assert projected["decision"] == expected["decision"]
        if expected["exception_queued"]:
            register_study(project, candidate, r0_report, reviewer)

        outputs[row["study_id"]] = {
            "candidate": candidate,
            "expected": expected,
            "r0_report": r0_report,
            "reviewer": reviewer,
        }
    return outputs


def write_fixture_manuscript(project: Path, writer_packet: dict[str, Any]) -> Path:
    fixture = _read_json(_fixture_path("manuscript.json"))
    approved_claims = writer_packet["claims"]
    assert len(approved_claims) == 1
    claim = approved_claims[0]
    figures = writer_packet["figures"]
    assert len(figures) == 1
    figure = figures[0]
    manuscript = (
        f"# {fixture['title']}\n\n"
        f"## {fixture['section_heading']}\n\n"
        f"{claim['text']} [1]. <!-- claim_id:{claim['claim_id']} -->\n\n"
        f"![{fixture['figure_alt']}]({figure['markdown_path']})\n\n"
        f"{figure['caption']}\n\n"
        "## References\n\n"
        f"{fixture['reference']}\n"
    )
    manuscript_path = project / "04_first_draft" / "first_draft.md"
    manuscript_path.parent.mkdir(parents=True, exist_ok=True)
    manuscript_path.write_text(manuscript, encoding="utf-8")

    _write_json(
        project / "04_first_draft" / "manuscript_lineage.json",
        {
            "schema_version": "manuscript-lineage.v1",
            "manuscript_sha256": hashlib.sha256(manuscript.encode("utf-8")).hexdigest(),
            "projection_sha256": writer_packet["projection_sha256"],
            "claims": [
                {
                    "claim_id": claim["claim_id"],
                    "section_id": "accepted-evidence",
                    "text_span": claim["text"],
                }
            ],
        },
    )
    return manuscript_path


def test_synthetic_three_study_product_acceptance_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def forbid_network(*_args, **_kwargs):
        raise AssertionError("network access is forbidden in the scaled review acceptance path")

    class OfflineSocket(socket.socket):
        def connect(self, *_args, **_kwargs):
            forbid_network()

        def connect_ex(self, *_args, **_kwargs):
            forbid_network()

    monkeypatch.setattr(socket, "socket", OfflineSocket)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    fixture_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(FIXTURE_ROOT.rglob("*"))
        if path.is_file()
    ).casefold()
    for forbidden in (
        "allene",
        "katritzky",
        "doi.org",
        "/home/",
        "c:\\users\\",
    ):
        assert forbidden not in fixture_text

    review_root = tmp_path / "review-workbench"
    project = initialize_review(
        review_root / "review-projects",
        "scaled-vertical-review",
        BRIEF,
    )
    state = _read_json(project / "00_brief" / "review_state.json")
    assert state["brief"] == BRIEF

    studies = run_fixture_studies(project)
    metrics = benchmark_metrics(project)
    assert metrics == {
        "approved_claim_count": 1,
        "blocked_claim_count": 1,
        "exception_count": 1,
        "human_required_claim_count": 1,
        "project_id": "scaled-vertical-review",
        "projected_claim_count": 3,
        "registered_study_count": 3,
    }

    risk_packet = build_risk_packet(project, low_risk_sample_rate=0)
    assert risk_packet["human_required_count"] == 1
    assert [target["claim_id"] for target in risk_packet["targets"]] == ["CLAIM-B"]
    apply_risk_decisions(
        project,
        {
            "packet_digest": risk_packet["packet_digest"],
            "decisions": [
                {
                    "action": "EXCLUDE",
                    "claim_id": target["claim_id"],
                    "review_target_digest": target["review_target_digest"],
                }
                for target in risk_packet["targets"]
            ],
        },
    )
    writer_packet = build_writer_packet(project)
    assert writer_packet["approved_claim_count"] == 1
    assert writer_packet["human_required_count"] == 0
    assert writer_packet["blocked_count"] == 2
    assert [claim["study_id"] for claim in writer_packet["claims"]] == ["STUDY-A"]
    assert [claim["claim_id"] for claim in writer_packet["claims"]] == ["CLAIM-A"]
    assert {row["claim_id"] for row in writer_packet["known_exclusions"]} == {
        "CLAIM-B",
        "CLAIM-C",
    }

    risk_surface = project_risk_payload(review_root, "scaled-vertical-review")
    assert risk_surface["coverage"] == {
        "targets": 1,
        "human_required": 1,
        "low_risk_audit": 0,
    }
    assert [target["target_id"] for target in risk_surface["targets"]] == ["CLAIM-B"]

    exception_queue = _read_json(project / "01_evidence" / "exception_queue.json")
    assert exception_queue["exceptions"] == [
        {
            "error_code": "REVIEWER_NOT_SUPPORT",
            "r0_status": "R0_PASS",
            "reviewer_verdict": "AMBIGUOUS",
            "study_id": "STUDY-C",
        }
    ]
    assert all(claim["study_id"] != "STUDY-C" for claim in writer_packet["claims"])

    evidence = project_evidence_payload(review_root, "scaled-vertical-review")
    assert evidence["coverage"] == {
        "studies": 3,
        "processable": 1,
        "blocked": 2,
        "claims": 3,
    }
    assert [card["study_id"] for card in evidence["cards"]] == [
        "STUDY-A",
        "STUDY-B",
        "STUDY-C",
    ]
    assert all(card["locators"] for card in evidence["cards"])
    assert all(
        locator["href"] == "" and "p. 1" in locator["label"]
        for card in evidence["cards"]
        for locator in card["locators"]
    )
    visible_evidence = json.dumps(evidence, ensure_ascii=False).casefold()
    for hidden in ("job_id", "sha256", "self_check", str(FIXTURE_ROOT).casefold(), "/home/"):
        assert hidden not in visible_evidence

    manuscript_path = write_fixture_manuscript(project, writer_packet)
    manuscript = manuscript_path.read_text(encoding="utf-8")
    approved_text = studies["STUDY-A"]["candidate"]["claims"][0]["claim_text"]
    human_text = studies["STUDY-B"]["candidate"]["claims"][0]["claim_text"]
    blocked_text = studies["STUDY-C"]["candidate"]["claims"][0]["claim_text"]
    assert manuscript.count(approved_text) == 1
    assert human_text not in manuscript
    assert blocked_text not in manuscript

    draft = project_draft_payload(review_root, "scaled-vertical-review")
    draft_text = "\n".join(section["body"] for section in draft["sections"])
    assert approved_text in draft_text
    assert human_text not in draft_text
    assert blocked_text not in draft_text

    release = build_project_release(project)
    assert release["release_status"] == "AI_REVIEWED_BENCHMARK"
    snapshot = project / "05_final_audit" / "final_draft.md"
    docx = project / "05_final_audit" / "final_draft.docx"
    assert snapshot.read_bytes() == manuscript_path.read_bytes()
    assert docx.is_file() and docx.stat().st_size > 0

    final = project_final_payload(review_root, "scaled-vertical-review")
    assert final["release_status"] == "AI_REVIEWED_BENCHMARK"
    assert final["manuscript_source"] == "release_snapshot"
    assert final["release_snapshot"] == {
        "exists": True,
        "matches_authoritative": True,
        "integrity_valid": True,
        "docx_exists": True,
    }
    assert final["final_draft_docx_exists"] is True
