#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.config import load_provider_config
from review_writer.image.alibaba_image import AlibabaImageAdapter
from review_writer.image.base import ImageRequest
from review_writer.providers.base import TextGenerationRequest
from review_writer.providers.dashscope_provider import DashScopeProvider
from review_writer.providers.offline_provider import OfflineProvider
from review_writer.providers import openai_compatible_provider as qwen_provider
from review_writer.providers.openai_compatible_provider import OpenAICompatibleProvider
from review_writer.retrieval.bailian_retrieval import BailianRetrieval
from review_writer.retrieval.base import RetrievalQuery


def main() -> int:
    tests = [
        test_offline_provider_deterministic,
        test_disabled_openai_compatible_no_network,
        test_disabled_dashscope_no_network,
        test_disabled_bailian_no_network,
        test_disabled_alibaba_image_no_network,
        test_openai_stream_chunks_are_merged,
        test_first_byte_timeout_is_classified_without_prompt_leakage,
        test_stream_midway_failure_writes_safe_report,
        test_dedicated_endpoint_metadata_is_redacted,
        test_config_loader_reads_example,
        test_check_providers_strict_passes,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")
            print(f"FAIL {test.__name__}: {exc}")
    if failures:
        return 1
    print(f"provider adapter tests passed: {len(tests)}")
    return 0


def test_offline_provider_deterministic() -> None:
    request = TextGenerationRequest(messages=[{"role": "user", "content": "hello offline"}])
    first = OfflineProvider().generate_text(request)
    second = OfflineProvider().generate_text(request)
    assert first.status == "ok"
    assert first.content == second.content
    assert first.metadata["network"] == "not_used"


def test_disabled_openai_compatible_no_network() -> None:
    result = OpenAICompatibleProvider().generate_text(_request())
    assert result.status == "disabled"
    assert result.metadata["network"] == "not_used"


def test_openai_stream_chunks_are_merged() -> None:
    assert hasattr(qwen_provider, "parse_openai_stream_content")
    chunks = [
        {"choices": [{"delta": {"content": "Alpha "}}]},
        {"choices": [{"delta": {"content": "beta"}}]},
        {"choices": [{"delta": {}}]},
    ]
    assert qwen_provider.parse_openai_stream_content(chunks, first_byte_timeout_seconds=5, total_timeout_seconds=5) == "Alpha beta"


def test_first_byte_timeout_is_classified_without_prompt_leakage() -> None:
    provider = OpenAICompatibleProvider(
        enabled=True,
        allow_network=True,
        api_key="sk-fake-secret-key-1234567890",
        base_url="https://workspace-for-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        client_factory=FakeClientFactory([{"choices": [{"delta": {"content": "late"}}]}]),
        monotonic=FakeClock([0.0, 4.0]),
        first_byte_timeout_seconds=3.0,
    )
    result = provider.generate_text(_request("secret prompt body must not leak"))
    assert result.status == "error"
    assert result.metadata["error_type"] == "first_byte_timeout"
    assert result.metadata["stream_started"] is False
    text = str(result.to_safe_dict())
    assert "secret prompt body" not in text
    assert "fake-secret-key" not in text


def test_stream_midway_failure_writes_safe_report() -> None:
    provider = OpenAICompatibleProvider(
        enabled=True,
        allow_network=True,
        api_key="sk-fake-secret-key-1234567890",
        base_url="https://workspace-for-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        client_factory=FakeClientFactory(FailingStream()),
        monotonic=FakeClock([0.0, 0.2, 0.3]),
    )
    result = provider.generate_text(_request("do not reveal this prompt"))
    assert result.status == "error"
    assert result.metadata["error_type"] == "stream_failed"
    assert result.metadata["stream_started"] is True
    assert result.metadata["chunks_received"] == 1
    text = str(result.to_safe_dict())
    assert "do not reveal" not in text
    assert "fake-secret-key" not in text


def test_dedicated_endpoint_metadata_is_redacted() -> None:
    provider = OpenAICompatibleProvider(
        enabled=True,
        allow_network=True,
        api_key="sk-fake-secret-key-1234567890",
        workspace_id="workspace-for-test",
        region="cn-beijing",
        client_factory=FakeClientFactory([{"choices": [{"delta": {"content": "ok"}}]}]),
        monotonic=FakeClock([0.0, 0.1, 0.2]),
    )
    result = provider.generate_text(_request())
    assert result.status == "ok"
    assert result.content == "ok"
    assert result.metadata["region"] == "cn-beijing"
    assert result.metadata["dedicated_endpoint_used"] is True
    text = str(result.to_safe_dict())
    assert "workspace-for-test" not in text
    assert "fake-secret-key" not in text


def test_disabled_dashscope_no_network() -> None:
    result = DashScopeProvider().generate_text(_request())
    assert result.status == "disabled"
    assert result.metadata["network"] == "not_used"


def test_disabled_bailian_no_network() -> None:
    result = BailianRetrieval().search(RetrievalQuery(query="allene ligand"))
    assert result.status == "disabled"
    assert result.metadata["network"] == "not_used"
    assert result.metadata["uploads"] == "not_used"


def test_disabled_alibaba_image_no_network() -> None:
    result = AlibabaImageAdapter().generate(ImageRequest(prompt="draw a mechanism"))
    assert result.status == "disabled"
    assert result.metadata["network"] == "not_used"
    assert result.metadata["uploads"] == "not_used"


def test_config_loader_reads_example() -> None:
    config = load_provider_config(REPO_ROOT / "config/providers.example.yaml")
    assert config["default_provider"] == "offline"
    assert config["providers"]["offline"]["enabled"] is True
    assert config["providers"]["alibaba_openai_compatible"]["enabled"] is False
    assert config["retrieval"]["bailian"]["enabled"] is False
    assert config["image"]["alibaba_image"]["enabled"] is False


def test_check_providers_strict_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_providers.py",
            "--config",
            "config/providers.example.yaml",
            "--output-json",
            "/tmp/provider_check_test.json",
            "--output-md",
            "/tmp/provider_check_test.md",
            "--strict",
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _request(content: str = "must stay offline") -> TextGenerationRequest:
    return TextGenerationRequest(messages=[{"role": "user", "content": content}])


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> float:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


class FakeClientFactory:
    def __init__(self, chunks) -> None:
        self.chunks = chunks

    def __call__(self, *, api_key: str, base_url: str, timeout):
        return FakeClient(self.chunks)


class FakeClient:
    def __init__(self, chunks) -> None:
        self.chat = FakeChat(chunks)


class FakeChat:
    def __init__(self, chunks) -> None:
        self.completions = FakeCompletions(chunks)


class FakeCompletions:
    def __init__(self, chunks) -> None:
        self.chunks = chunks

    def create(self, **kwargs):
        assert kwargs["stream"] is True
        return self.chunks


class FailingStream:
    def __iter__(self):
        yield {"choices": [{"delta": {"content": "partial"}}]}
        raise RuntimeError("simulated stream failure with prompt hidden")


if __name__ == "__main__":
    raise SystemExit(main())
