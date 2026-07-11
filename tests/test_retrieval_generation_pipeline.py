#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
FIXTURE = REPO_ROOT / "tests/fixtures/retrieval_generation/clean_3paper_retrieval_fixture.json"
OUT_ROOT = Path("/tmp/review_writer_phase7_test_offline")


def main() -> int:
    test_pipeline_builds_safe_evidence_pack()
    test_pipeline_has_no_qwen_transport_implementation()
    test_qwen_generation_invokes_provider_adapter_only()
    test_phase7_preflight_command_writes_safe_report_without_network()
    test_offline_generation_is_grounded()
    test_demo_script_offline_outputs_checkpoint()
    print("retrieval_generation_pipeline_tests: ok")
    return 0


def test_pipeline_builds_safe_evidence_pack() -> None:
    from review_writer.pipeline.retrieval_generation import build_evidence_pack, load_retrieval_fixture

    pack = build_evidence_pack(
        load_retrieval_fixture(FIXTURE),
        section_id="phase7-single-section",
        section_title="Representative strategies for asymmetric allene synthesis",
        max_evidence_items=3,
    )
    assert pack.needs_human_review is True
    assert pack.trusted_for_scientific_quality is False
    assert [item.paper_id for item in pack.items] == ["F3I", "F47A", "P403"]
    rendered = json.dumps(pack.to_safe_dict(), ensure_ascii=False)
    forbidden = ["signed", "workspace", "document_id", "pipeline_id", "file_path", "/home/", "http"]
    assert not any(token in rendered.lower() for token in forbidden)


def test_pipeline_has_no_qwen_transport_implementation() -> None:
    source = (REPO_ROOT / "review_writer/pipeline/retrieval_generation.py").read_text(encoding="utf-8")
    forbidden = [
        "urllib.request",
        "urllib.error",
        "Authorization",
        "urlopen(",
        "chat.completions.create",
        "compatible-mode/v1",
    ]
    assert not any(token in source for token in forbidden)


def test_qwen_generation_invokes_provider_adapter_only() -> None:
    from review_writer.pipeline.retrieval_generation import (
        build_evidence_pack,
        generate_grounded_section,
        load_retrieval_fixture,
    )
    from review_writer.providers.base import ProviderResult

    class FakeProvider:
        provider_name = "fake_qwen"

        def __init__(self) -> None:
            self.requests = []

        def generate_text(self, request):
            self.requests.append(request)
            return ProviderResult(
                provider_name=self.provider_name,
                status="ok",
                content=(
                    "## Representative strategies for asymmetric allene synthesis\n\n"
                    "F3I frames the topic as review/background evidence [F3I].\n\n"
                    "F47A anchors a palladium allene method signal without numerical outcomes [F47A].\n\n"
                    "P403 contributes a recent-progress allenylation signal [P403].\n"
                ),
                metadata={"network": "mocked"},
            )

    pack = build_evidence_pack(load_retrieval_fixture(FIXTURE), max_evidence_items=3)
    provider = FakeProvider()
    result = generate_grounded_section(
        pack,
        generation_provider="qwen",
        allow_qwen=True,
        text_provider=provider,
    )
    assert result.provider == "fake_qwen"
    assert provider.requests
    assert provider.requests[0].metadata["evidence_item_count"] == 3
    assert result.checkpoint == "Sections: ready_for_human_review"


def test_phase7_preflight_command_writes_safe_report_without_network() -> None:
    output_json = Path("/tmp/phase7_real_preflight_test.json")
    output_md = Path("/tmp/phase7_real_preflight_test.md")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/demo/phase7_real_preflight.py",
            "--fixture",
            str(FIXTURE),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode in {0, 1}, result.stderr + result.stdout
    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["network_calls"] == 0
    assert report["checks"]["offline_evidence_pack"]["status"] == "pass"
    assert report["checks"]["streaming_parser"]["status"] == "pass"
    assert report["checks"]["safe_failure_report"]["status"] == "pass"
    combined = result.stdout + result.stderr + output_json.read_text(encoding="utf-8") + output_md.read_text(encoding="utf-8")
    assert "fake-secret-key" not in combined
    assert "Authorization" not in combined


def test_offline_generation_is_grounded() -> None:
    from review_writer.pipeline.retrieval_generation import (
        build_evidence_pack,
        generate_grounded_section,
        load_retrieval_fixture,
    )

    pack = build_evidence_pack(
        load_retrieval_fixture(FIXTURE),
        section_id="phase7-single-section",
        section_title="Representative strategies for asymmetric allene synthesis",
        max_evidence_items=3,
    )
    result = generate_grounded_section(pack, generation_provider="offline")
    assert result.provider == "offline"
    assert result.checkpoint == "Sections: ready_for_human_review"
    assert result.needs_human_review is True
    assert "[F3I]" in result.section_text
    assert "[F47A]" in result.section_text
    assert "[P403]" in result.section_text
    assert "prompt" not in result.section_text.lower()


def test_demo_script_offline_outputs_checkpoint() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/demo/run_retrieval_generation_pilot.py",
            "--retrieval-mode",
            "offline_fixture",
            "--generation-provider",
            "offline",
            "--output-root",
            str(OUT_ROOT),
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads((OUT_ROOT / "phase7_retrieval_generation_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["checkpoint"] == "Sections: ready_for_human_review"
    assert report["claim_evidence_coverage"] == 1.0
    assert report["unsupported_claim_count"] == 0
    assert report["transport_mode"] == "bailian=not_used;qwen=not_used"
    assert report["bailian_transport_mode"] == "not_used"
    assert report["qwen_transport_mode"] == "not_used"
    assert report["bailian_proxy_env_names_set"] == []
    assert report["qwen_proxy_env_names_set"] == []
    assert report["safety"]["pdf_uploaded"] == "no"
    assert report["safety"]["full_text_uploaded"] == "no"


if __name__ == "__main__":
    raise SystemExit(main())
