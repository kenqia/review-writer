#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from review_writer.retrieval.bailian_official_client import (  # noqa: E402
    BailianOfficialClient,
    BailianOfficialConfig,
    classify_parse_failure,
    summarize_describe_file_response,
)


def main() -> int:
    test_upload_artifact_is_immutable_and_telemetry_safe()
    test_upload_uses_lease_method_and_headers_only()
    test_parse_failure_diagnostics_are_classified()
    test_create_index_accepts_uppercase_response_id()
    test_txt_payload_candidate_is_allowed()
    test_cleanup_orphan_file_dry_run_redacts_ids()
    print("bailian_sdk_e2e_closure_tests: ok")
    return 0


def test_upload_artifact_is_immutable_and_telemetry_safe() -> None:
    payload = Path("/tmp/review_writer_bailian_upload_immutability.md")
    payload.write_text("review-writer Phase 6c smoke test\n", encoding="utf-8")
    client = BailianOfficialClient(BailianOfficialConfig())
    artifact = client.prepare_upload_artifact(payload)
    payload.write_text("changed after lease\n", encoding="utf-8")
    assert artifact["size"] != payload.stat().st_size
    assert artifact["bytes"].startswith(b"review-writer")
    assert len(artifact["md5_prefix"]) == 8


def test_upload_uses_lease_method_and_headers_only() -> None:
    payload = Path("/tmp/review_writer_bailian_upload_contract.txt")
    payload.write_text("review-writer Phase 6c smoke test\n", encoding="utf-8")
    client = BailianOfficialClient(BailianOfficialConfig())
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

    def fake_request(method: str, url: str, data: bytes, headers: dict[str, str], timeout: float) -> FakeResponse:
        captured.update({"method": method, "url": url, "data": data, "headers": headers, "timeout": timeout})
        return FakeResponse()

    old_requests = sys.modules.get("requests")
    sys.modules["requests"] = types.SimpleNamespace(request=fake_request)  # type: ignore[assignment]
    try:
        result = client.upload_file_to_presigned_url(
            {
                "url": "https://signed.example.invalid/upload",
                "method": "POST",
                "headers": {"Content-Type": "text/plain", "X-bailian-extra": "redacted-extra"},
            },
            payload,
        )
    finally:
        if old_requests is not None:
            sys.modules["requests"] = old_requests
        else:
            sys.modules.pop("requests", None)
    assert captured["method"] == "POST"
    assert captured["headers"] == {"Content-Type": "text/plain", "X-bailian-extra": "redacted-extra"}
    assert result["upload_method"] == "POST"
    assert result["upload_content_type_present"] is True
    assert result["upload_extra_header_present"] is True
    assert result["post_upload_md5_matches"] is True


def test_parse_failure_diagnostics_are_classified() -> None:
    class Data:
        status = "PARSE_FAILED"
        file_type = "unknown"
        parser = "DASHSCOPE_DOCMIND"
        category_type = "UNSTRUCTURED"

        def to_map(self) -> dict[str, str]:
            return {
                "status": self.status,
                "file_type": self.file_type,
                "parser": self.parser,
                "category_type": self.category_type,
                "message": "unsupported file type",
            }

    class Body:
        request_id = "request-redacted"
        data = Data()

    class Response:
        body = Body()

    diagnostics = summarize_describe_file_response(Response())
    assert diagnostics["status"] == "PARSE_FAILED"
    assert diagnostics["request_id_present"] is True
    assert classify_parse_failure(diagnostics) in {"unsupported_or_misdetected_file_type", "parser_rejected"}


def test_create_index_accepts_uppercase_response_id() -> None:
    old_sdk = sys.modules.get("alibabacloud_bailian20231229")
    old_models = sys.modules.get("alibabacloud_bailian20231229.models")
    old_tea_util = sys.modules.get("alibabacloud_tea_util")
    old_tea_util_models = sys.modules.get("alibabacloud_tea_util.models")

    class FakeCreateIndexRequest:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    fake_models = types.SimpleNamespace(CreateIndexRequest=FakeCreateIndexRequest)
    fake_util_models = types.SimpleNamespace(RuntimeOptions=lambda **kwargs: types.SimpleNamespace(**kwargs))
    sys.modules["alibabacloud_bailian20231229"] = types.SimpleNamespace(models=fake_models)  # type: ignore[assignment]
    sys.modules["alibabacloud_bailian20231229.models"] = fake_models  # type: ignore[assignment]
    sys.modules["alibabacloud_tea_util"] = types.SimpleNamespace(models=fake_util_models)  # type: ignore[assignment]
    sys.modules["alibabacloud_tea_util.models"] = fake_util_models  # type: ignore[assignment]

    class FakeBody:
        request_id = "request-redacted"
        Data = {"Id": "index-redacted"}

    class FakeResponse:
        body = FakeBody()

    class FakeClient:
        def create_index_with_options(self, *_args, **_kwargs) -> FakeResponse:
            return FakeResponse()

    try:
        result = BailianOfficialClient(BailianOfficialConfig()).create_index(FakeClient(), "workspace-redacted", "file-redacted")
        assert result["status"] == "index_created"
        assert result["index_id"] == "index-redacted"
    finally:
        if old_sdk is not None:
            sys.modules["alibabacloud_bailian20231229"] = old_sdk
        else:
            sys.modules.pop("alibabacloud_bailian20231229", None)
        if old_models is not None:
            sys.modules["alibabacloud_bailian20231229.models"] = old_models
        else:
            sys.modules.pop("alibabacloud_bailian20231229.models", None)
        if old_tea_util is not None:
            sys.modules["alibabacloud_tea_util"] = old_tea_util
        else:
            sys.modules.pop("alibabacloud_tea_util", None)
        if old_tea_util_models is not None:
            sys.modules["alibabacloud_tea_util.models"] = old_tea_util_models
        else:
            sys.modules.pop("alibabacloud_tea_util.models", None)


def test_txt_payload_candidate_is_allowed() -> None:
    build = subprocess.run(
        [
            sys.executable,
            "scripts/rag/build_bailian_small_kb_payload.py",
            "--clean-root",
            "demo_projects/clean_3paper_allene_review",
            "--output-jsonl",
            "/tmp/bailian_small_kb_payload.jsonl",
            "--output-md",
            "/tmp/bailian_small_kb_payload.md",
            "--output-manifest",
            "/tmp/bailian_small_kb_payload_manifest.json",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert build.returncode == 0, build.stderr + build.stdout
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_small_kb_pilot.py",
            "--payload-jsonl",
            "/tmp/bailian_small_kb_payload.jsonl",
            "--questions",
            "evals/fixtures/rag_expected_questions.json",
            "--upload-file",
            "/tmp/review_writer_bailian_smoke.txt",
            "--output-json",
            "/tmp/bailian_txt_candidate_dry.json",
            "--output-md",
            "/tmp/bailian_txt_candidate_dry.md",
            "--use-official-sdk",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(Path("/tmp/bailian_txt_candidate_dry.json").read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["upload_file_type"] == "txt"
    assert Path(report["official_upload_md"]).name == "review_writer_bailian_smoke.txt"


def test_cleanup_orphan_file_dry_run_redacts_ids() -> None:
    report_path = Path("/tmp/bailian_orphan_cleanup_fixture.json")
    report_path.write_text(
        json.dumps({"official_sdk_result": {"created_file_id": "file_should_not_be_printed"}}),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag/bailian_cleanup_orphan_file.py",
            "--report-json",
            str(report_path),
            "--output-json",
            "/tmp/bailian_orphan_cleanup_test.json",
            "--output-md",
            "/tmp/bailian_orphan_cleanup_test.md",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    combined = (
        result.stdout
        + Path("/tmp/bailian_orphan_cleanup_test.json").read_text(encoding="utf-8")
        + Path("/tmp/bailian_orphan_cleanup_test.md").read_text(encoding="utf-8")
    )
    assert "file_should_not_be_printed" not in combined
    assert "file_id_present=True" in result.stdout


if __name__ == "__main__":
    raise SystemExit(main())
