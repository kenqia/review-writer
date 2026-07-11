#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import (  # noqa: E402
    build_retrieve_request_kwargs,
    evaluate_retrieve_nodes,
    extract_retrieve_nodes,
    retrieve_request_modes,
)


def main() -> int:
    test_retrieve_nodes_with_smoke_fact_pass()
    test_retrieve_nodes_with_pascal_case_object_metadata_pass()
    test_retrieve_nodes_with_normalized_fact_pass()
    test_metadata_title_hit_does_not_count_as_fact()
    test_extract_retrieve_nodes_from_pascal_response()
    test_retrieve_request_modes_respect_supported_fields()
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
    assert report["matched_source"] == "text"
    assert report["node_text_present_count"] == 1
    assert report["metadata_content_present_count"] == 0


def test_retrieve_nodes_with_pascal_case_object_metadata_pass() -> None:
    class Node:
        Text = ""
        Score = 0.88
        Metadata = json.dumps({"content": "The expected answer is review-writer Phase 6c smoke test."})

    report = evaluate_retrieve_nodes([Node()])
    assert report["nodes_count"] == 1
    assert report["top_score"] == 0.88
    assert report["smoke_fact_found"] is True
    assert report["matched_source"] == "metadata_content"
    assert report["node_text_present_count"] == 0
    assert report["metadata_content_present_count"] == 1


def test_retrieve_nodes_with_normalized_fact_pass() -> None:
    report = evaluate_retrieve_nodes(
        [
            {
                "Text": "Review Writer phase 6c smoke-test is present after SDK normalization.",
                "Score": 0.77,
            }
        ]
    )
    assert report["smoke_fact_found"] is True
    assert report["matched_source"] == "text"


def test_metadata_title_hit_does_not_count_as_fact() -> None:
    report = evaluate_retrieve_nodes(
        [
            {
                "text": "Only a vague body is present.",
                "metadata": {
                    "title": "review-writer Phase 6c smoke test",
                    "doc_name": "review-writer Phase 6c smoke test",
                    "paper_id": "P403",
                },
            }
        ]
    )
    assert report["nodes_count"] == 1
    assert report["smoke_fact_found"] is False
    assert report["matched_source"] == "none"


def test_extract_retrieve_nodes_from_pascal_response() -> None:
    response = types.SimpleNamespace(
        body=types.SimpleNamespace(
            Data=types.SimpleNamespace(Nodes=[{"Text": "review-writer Phase 6c smoke test", "Score": 0.91}])
        )
    )
    nodes = extract_retrieve_nodes(response)
    assert len(nodes) == 1
    assert evaluate_retrieve_nodes(nodes)["smoke_fact_found"] is True


def test_retrieve_request_modes_respect_supported_fields() -> None:
    supported = {
        "query": True,
        "index_id": True,
        "dense_similarity_top_k": True,
        "sparse_similarity_top_k": True,
        "enable_reranking": True,
        "rerank_top_n": False,
    }
    modes = retrieve_request_modes(supported)
    assert [mode["mode"] for mode in modes] == [
        "official_minimal",
        "hybrid_no_rerank",
        "sparse_exact_no_rerank",
        "dense_semantic_no_rerank",
    ]
    kwargs = build_retrieve_request_kwargs(
        index_id="index-redacted",
        query="query",
        request_options={"dense_similarity_top_k": 20, "rerank_top_n": 10},
        supported_request_fields=supported,
    )
    assert kwargs == {"index_id": "index-redacted", "query": "query", "dense_similarity_top_k": 20}


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
