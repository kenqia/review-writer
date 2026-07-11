#!/usr/bin/env python3
from __future__ import annotations

import csv
import http.client
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.review.serve_phase8_evidence_review import is_allowed_read, make_handler, render_index, safe_path
import scripts.review.serve_phase8_evidence_review as dashboard

LOCAL_ROOT = REPO_ROOT / "local/phase8_evidence"
PUBLIC_REPORT = REPO_ROOT / "docs/phase8/phase8a_status_report.json"


def main() -> int:
    groups = {
        "preflight": [test_gitignore_boundaries, test_requirements_phase8_pinned, test_no_forbidden_public_phase8_outputs],
        "source_inventory": [test_source_inventory_shape],
        "extraction": [test_ai_extraction_statuses_and_locators, test_quote_lengths_and_mechanism_classes],
        "review_package": [test_review_queue_size_and_phase7_claims, test_no_verified_status],
        "dashboard": [test_dashboard_path_security_and_append_only_contract],
        "decision_writer": [test_decision_writer_recovery_and_atomic_batch],
    }
    selected = sys.argv[1:] or list(groups)
    tests = [test for group in selected for test in groups[group]]
    for test in tests:
        test()
    print("phase8_evidence_package_tests: ok")
    return 0


def test_gitignore_boundaries() -> None:
    ignored = subprocess.run(["git", "check-ignore", "-q", "local/phase8_evidence/example.pdf"], cwd=REPO_ROOT)
    assert ignored.returncode == 0
    ignored_pdf = subprocess.run(["git", "check-ignore", "-q", "docs/phase8/example.pdf"], cwd=REPO_ROOT)
    assert ignored_pdf.returncode == 0
    tracked_code = subprocess.run(["git", "check-ignore", "-q", "review_writer/phase8/schemas.py"], cwd=REPO_ROOT)
    assert tracked_code.returncode == 1
    tracked_requirements = subprocess.run(["git", "check-ignore", "-q", "requirements-phase8.txt"], cwd=REPO_ROOT)
    assert tracked_requirements.returncode == 1


def test_requirements_phase8_pinned() -> None:
    text = (REPO_ROOT / "requirements-phase8.txt").read_text(encoding="utf-8")
    for line in [line for line in text.splitlines() if line.strip()]:
        assert "==" in line


def test_no_forbidden_public_phase8_outputs() -> None:
    forbidden = [
        "verified_bibliography.json",
        "verified_claims.jsonl",
        "gold_evidence_pack.json",
        "scientific_eval_report",
    ]
    for token in forbidden:
        assert not (REPO_ROOT / token).exists()


def test_source_inventory_shape() -> None:
    data = json.loads(PUBLIC_REPORT.read_text(encoding="utf-8"))
    assert data["status"] == "HUMAN_REVIEW_REQUIRED"
    assert len(data["source_inventory"]) == 6
    assert data["f3i_official_si_status"] == "NO_SI_PUBLISHED_ON_OFFICIAL_PAGE"
    assert data["si_identity_status"]["F47A"] == "SI_VALIDATED"
    assert data["si_identity_status"]["P403"] == "SI_VALIDATED"
    for item in data["source_inventory"]:
        assert item["source_document_id"].endswith(("_MAIN", "_SI"))
        assert "sha256" not in item
        if item["status"] in {"SOURCE_FOUND", "SI_VALIDATED"}:
            assert item["hash_prefix"] and len(item["hash_prefix"]) == 12
            assert item["page_count"] and item["page_count"] > 0
        else:
            assert item["status"] == "NO_SI_PUBLISHED_ON_OFFICIAL_PAGE"
    local_inventory = json.loads((LOCAL_ROOT / "inventories/source_inventory.local.json").read_text(encoding="utf-8"))
    f47a = next(row for row in local_inventory if row["source_document_id"] == "F47A_SI")
    p403 = next(row for row in local_inventory if row["source_document_id"] == "P403_SI")
    assert f47a["identity_match_status"] == "SI_VALIDATED"
    assert p403["identity_match_status"] == "SI_VALIDATED"
    assert len(f47a["identity_match_evidence"]) >= 3
    assert len(p403["identity_match_evidence"]) >= 3
    assert p403["doi_candidate"] == "10.1021/acscatal.5c05571.s001"


def test_ai_extraction_statuses_and_locators() -> None:
    rows = read_jsonl(LOCAL_ROOT / "ai_extraction/ai_extraction.jsonl")
    evidence_rows = read_jsonl(LOCAL_ROOT / "ai_extraction/evidence_records.jsonl")
    report = json.loads(PUBLIC_REPORT.read_text(encoding="utf-8"))
    assert len(rows) >= 72
    assert report["si_incremental_extraction_count"] == 30
    assert sum(1 for row in rows if row.get("source_role") == "SI") == 30
    assert len(evidence_rows) == len(rows)
    allowed = {"AI_EXTRACTED", "HUMAN_REVIEW_REQUIRED", "MISSING_SOURCE", "CONFLICT", "UNSUPPORTED_CANDIDATE"}
    for row in rows:
        assert row["status"] in allowed
        loc = row["source_locator"]
        assert "pdf_page_index" in loc
        assert "printed_page_label" in loc
        assert "section_heading" in loc
        assert "value_as_reported" in row
        assert "normalized_value_candidate" in row
        assert "normalization_requires_human_review" in row
    for row in evidence_rows:
        assert row["extended_excerpt_pointer"].startswith("local/phase8_evidence/")
        assert "source_hash" in row


def test_quote_lengths_and_mechanism_classes() -> None:
    rows = read_jsonl(LOCAL_ROOT / "ai_extraction/ai_extraction.jsonl")
    for row in rows:
        assert len(row["short_quote"].split()) <= 25
        assert row["mechanism_classification"] in {
            "EXPERIMENTALLY_DEMONSTRATED",
            "AUTHOR_PROPOSED",
            "REVIEWER_INFERENCE_CANDIDATE",
            "AI_INFERENCE",
        }


def test_review_queue_size_and_phase7_claims() -> None:
    report = json.loads(PUBLIC_REPORT.read_text(encoding="utf-8"))
    assert 50 <= report["core_review_queue_size"] <= 70
    assert report["extended_review_queue_size"] > report["core_review_queue_size"]
    assert report["core_atomic_mapping_count"] == report["core_review_queue_size"]
    assert report["phase7_claim_count"] > 0
    queue = read_jsonl(LOCAL_ROOT / "review_queue/core_review_queue.jsonl")
    assert any(row["field_name"] == "phase7_claim" for row in queue)
    assert any(row["field_name"] == "SI identity/status" for row in queue)
    assert all(row["blinded_first"] is True for row in queue)
    mapping = json.loads((LOCAL_ROOT / "review_queue/core_to_atomic_map.json").read_text(encoding="utf-8"))["items"]
    extended_ids = {row["review_item_id"] for row in read_jsonl(LOCAL_ROOT / "review_queue/extended_review_queue.jsonl")}
    assert len(mapping) == len(queue)
    for row in mapping:
        assert row["core_review_item_id"]
        assert row["atomic_extended_review_item_ids"]
        assert set(row["atomic_extended_review_item_ids"]).issubset(extended_ids)
    with (LOCAL_ROOT / "review_queue/core_review_queue.csv").open(encoding="utf-8", newline="") as fh:
        csv_rows = list(csv.DictReader(fh))
    assert len(csv_rows) == len(queue)


def test_no_verified_status() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            LOCAL_ROOT / "ai_extraction/ai_extraction.jsonl",
            LOCAL_ROOT / "review_queue/core_review_queue.jsonl",
            LOCAL_ROOT / "review_queue/extended_review_queue.jsonl",
            LOCAL_ROOT / "review_queue/core_to_atomic_map.json",
        ]
    )
    assert '"VERIFIED"' not in text
    assert '"REJECTED"' not in text
    assert '"EDITED"' not in text
    assert '"CANNOT_VERIFY"' not in text


def test_dashboard_path_security_and_append_only_contract() -> None:
    root = LOCAL_ROOT.resolve()
    assert hasattr(dashboard, "safe_pid_file"), "dashboard PID path guard is missing"
    assert dashboard.safe_pid_file(root, root / "reports/dashboard.pid") == root / "reports/dashboard.pid"
    assert dashboard.safe_pid_file(root, root.parent / "dashboard.pid") is None
    assert safe_path(root, "../etc/passwd") is None
    assert safe_path(root, "/etc/passwd") is None
    allowed = safe_path(root, "review_queue/core_review_queue.json")
    assert allowed is not None and is_allowed_read(root, allowed)
    forbidden = safe_path(root, "sources/F3I/F3I_MAIN.pdf")
    assert forbidden is not None and not is_allowed_read(root, forbidden)
    forbidden_si = safe_path(root, "sources/F47A/F47A_SI.pdf")
    assert forbidden_si is not None and not is_allowed_read(root, forbidden_si)
    csv_file = safe_path(root, "review_queue/core_review_queue.csv")
    assert csv_file is not None and is_allowed_read(root, csv_file)
    with tempfile.TemporaryDirectory() as tmp:
        outside = Path(tmp) / "x.json"
        outside.write_text("{}", encoding="utf-8")
        assert not is_allowed_read(root, outside)
    html = render_index(root)
    assert "guided-chat" in html
    assert "/api/decision" not in html
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
        connection.request(
            "POST",
            "/api/decision",
            body=json.dumps({"decision": "accept"}),
            headers={"content-type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 405
        assert json.loads(response.read())["error"] == "guided-chat mode is read-only"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_decision_writer_recovery_and_atomic_batch() -> None:
    writer = REPO_ROOT / "scripts/review/record_phase8_decision.py"
    assert writer.exists(), "safe Phase 8 decision writer is missing"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "phase8_evidence"
        (root / "review_queue").mkdir(parents=True)
        (root / "inventories").mkdir()
        core_item = {
            "review_item_id": "CORE-1",
            "candidate_value": "candidate",
            "ai_record_hash": "a" * 64,
            "atomic_extended_review_item_ids": ["ATOM-1"],
            "field_name": "phase7_claim",
        }
        write_json(root / "review_queue/core_review_queue.json", {"items": [core_item]})
        write_json(root / "review_queue/extended_review_queue.json", {"items": [{"review_item_id": "ATOM-1"}]})
        write_json(
            root / "review_queue/core_to_atomic_map.json",
            {"items": [{"core_review_item_id": "CORE-1", "atomic_extended_review_item_ids": ["ATOM-1"]}]},
        )
        write_json(root / "inventories/source_inventory.local.json", [{"source_document_id": "DOC-1"}])
        event = {
            "decision_id": "decision-001",
            "batch_id": "batch_001",
            "sequence_number": 1,
            "reviewer_id": "reviewer_1",
            "review_mode": "guided_chat",
            "review_item_id": "CORE-1",
            "core_review_item_id": "CORE-1",
            "atomic_review_item_ids": ["ATOM-1"],
            "original_ai_record_hash": "a" * 64,
            "preliminary_decision": "accept",
            "ai_recommendation_shown": True,
            "ai_recommendation": "accept",
            "final_decision": "accept",
            "edited_value": None,
            "reviewer_note": "source agrees",
            "evidence_opened": False,
            "evidence_document_ids": ["DOC-1"],
            "evidence_locators": [{"source_document_id": "DOC-1", "pdf_page_index": 1}],
            "created_at": "2026-07-12T00:00:00Z",
            "supersedes_decision_id": None,
            "decision_scope": "individual",
            "original_value": "candidate",
        }
        batch_file = root / "batch.json"
        write_json(batch_file, {"events": [event]})
        dry = run_writer(writer, root, batch_file, "--dry-run")
        assert dry.returncode == 0, dry.stderr
        assert json.loads(dry.stdout)["status"] == "dry_run"
        assert not (root / "review_decisions/reviewer_1.jsonl").exists()
        saved = run_writer(writer, root, batch_file)
        assert saved.returncode == 0, saved.stderr
        assert json.loads(saved.stdout)["status"] == "recorded"
        log = root / "review_decisions/reviewer_1.jsonl"
        rows = read_jsonl(log)
        assert len(rows) == 1
        assert rows[0]["package_manifest_hash"]
        assert rows[0]["source_inventory_hash"]
        for rel in [
            "reports/checkpoint.json",
            "reports/progress.md",
            "reports/session_resume.md",
        ]:
            assert (root / rel).exists()
        backup_dirs = list((root / "backups").glob("batch_001_*"))
        assert len(backup_dirs) == 1
        assert (backup_dirs[0] / "manifest.sha256").exists()
        before = log.read_bytes()
        duplicate = run_writer(writer, root, batch_file)
        assert duplicate.returncode != 0
        assert "duplicate decision_id" in duplicate.stderr
        assert log.read_bytes() == before
        recovery = subprocess.run(
            [
                sys.executable,
                str(writer),
                "audit",
                "--root",
                str(root),
                "--write-reports",
                "--dashboard-port",
                "8788",
                "--warning",
                "port 8787 is occupied",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
        )
        assert recovery.returncode == 0, recovery.stderr
        resume = (root / "reports/session_resume.md").read_text(encoding="utf-8")
        assert "--port 8788" in resume
        assert "port 8787 is occupied" in resume


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def run_writer(writer: Path, root: Path, batch_file: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(writer), "record", "--root", str(root), "--input", str(batch_file), *extra],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
