#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.review.serve_phase8_evidence_review import is_allowed_read, safe_path

LOCAL_ROOT = REPO_ROOT / "local/phase8_evidence"
PUBLIC_REPORT = REPO_ROOT / "docs/phase8/phase8a_status_report.json"


def main() -> int:
    groups = {
        "preflight": [test_gitignore_boundaries, test_requirements_phase8_pinned, test_no_forbidden_public_phase8_outputs],
        "source_inventory": [test_source_inventory_shape],
        "extraction": [test_ai_extraction_statuses_and_locators, test_quote_lengths_and_mechanism_classes],
        "review_package": [test_review_queue_size_and_phase7_claims, test_no_verified_status],
        "dashboard": [test_dashboard_path_security_and_append_only_contract],
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


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
