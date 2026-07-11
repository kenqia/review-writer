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


def _request() -> TextGenerationRequest:
    return TextGenerationRequest(messages=[{"role": "user", "content": "must stay offline"}])


if __name__ == "__main__":
    raise SystemExit(main())
