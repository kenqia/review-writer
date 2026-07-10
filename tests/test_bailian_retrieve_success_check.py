#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import evaluate_retrieve_nodes  # noqa: E402


def main() -> int:
    test_retrieve_nodes_with_smoke_fact_pass()
    test_retrieve_empty_nodes_fail_shape()
    test_retrieve_nodes_without_smoke_fact_miss()
    test_signed_url_is_detected_but_not_reported()
    print("bailian_retrieve_success_check_tests: ok")
    return 0


def test_retrieve_nodes_with_smoke_fact_pass() -> None:
    report = evaluate_retrieve_nodes(
        [
            {
                "text": "P403 contains review-writer Phase 6c smoke test and clean allene evidence.",
                "score": 0.98,
            }
        ]
    )
    assert report["nodes_count"] == 1
    assert report["top_score"] == 0.98
    assert report["smoke_fact_found"] is True


def test_retrieve_empty_nodes_fail_shape() -> None:
    report = evaluate_retrieve_nodes([])
    assert report["nodes_count"] == 0
    assert report["smoke_fact_found"] is False


def test_retrieve_nodes_without_smoke_fact_miss() -> None:
    report = evaluate_retrieve_nodes([{"text": "P403 clean allene evidence.", "score": 0.5}])
    assert report["nodes_count"] == 1
    assert report["smoke_fact_found"] is False


def test_signed_url_is_detected_but_not_reported() -> None:
    nodes = [
        {
            "text": "review-writer Phase 6c smoke test",
            "metadata": {"url": "https://example.oss-cn-beijing.aliyuncs.com/a?OSSAccessKeyId=redacted&Signature=redacted"},
        }
    ]
    report = evaluate_retrieve_nodes(nodes)
    rendered = json.dumps(report, ensure_ascii=False)
    assert report["signed_url_present"] is True
    assert report["signed_url_redacted"] is True
    assert "OSSAccessKeyId" not in rendered
    assert "Signature" not in rendered
    assert "https://example.oss-cn-beijing.aliyuncs.com" not in rendered


if __name__ == "__main__":
    raise SystemExit(main())
