from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_SDK_MODULES = [
    "alibabacloud_bailian20231229",
    "alibabacloud_tea_openapi",
    "alibabacloud_tea_util",
    "requests",
]
REQUIRED_ENV = [
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "WORKSPACE_ID",
]
OFFICIAL_STEPS = [
    "ApplyFileUploadLease",
    "upload file to pre-signed URL",
    "AddFile",
    "DescribeFile until parse success",
    "CreateIndex",
    "SubmitIndexJob",
    "GetIndexJobStatus",
]


@dataclass(frozen=True)
class BailianOfficialConfig:
    region: str = "cn-beijing"
    category: str = "document_search"
    index_type: str = "structured_document"


class BailianOfficialClient:
    provider_name = "bailian_official_sdk"

    def __init__(self, config: BailianOfficialConfig | None = None) -> None:
        self.config = config or BailianOfficialConfig()

    def dependency_presence(self) -> dict[str, str]:
        presence: dict[str, str] = {}
        for module in REQUIRED_SDK_MODULES:
            try:
                importlib.import_module(module)
                presence[module] = "INSTALLED"
            except Exception:
                presence[module] = "MISSING"
        return presence

    def env_presence(self) -> dict[str, str]:
        presence = {name: "SET" if os.environ.get(name) else "MISSING" for name in REQUIRED_ENV}
        presence["BAILIAN_REGION"] = "SET" if os.environ.get("BAILIAN_REGION") else "MISSING_DEFAULT_CN_BEIJING"
        presence["BAILIAN_MODEL"] = "SET" if os.environ.get("BAILIAN_MODEL") else "MISSING_DEFAULT_QWEN_PLUS"
        return presence

    def run_small_kb_pilot(
        self,
        *,
        upload_file: Path,
        allow_network: bool,
        allow_upload: bool,
    ) -> dict[str, Any]:
        dependency_presence = self.dependency_presence()
        env_presence = self.env_presence()
        base = {
            "provider_name": self.provider_name,
            "region": os.environ.get("BAILIAN_REGION") or self.config.region,
            "dependency_presence": dependency_presence,
            "env_presence": env_presence,
            "official_steps": OFFICIAL_STEPS,
            "upload_file": str(upload_file),
            "kb_name_template": "review-writer-clean-3paper-pilot-<timestamp>",
            "kb_id_redacted_or_tmp_only": None,
            "network_attempted": False,
            "upload_attempted": False,
            "knowledge_base_created": False,
            "index_created": False,
            "retrieval_status": "blocked_retrieval_api_contract_required",
        }
        if not allow_network or not allow_upload:
            return {
                **base,
                "status": "dry_run",
                "error_type": None,
                "summary": "official SDK dry-run only; no network or upload was attempted",
            }
        missing_modules = [name for name, status in dependency_presence.items() if status == "MISSING"]
        if missing_modules:
            return {
                **base,
                "status": "fail",
                "error_type": "missing_dependency_or_api_contract",
                "summary": "official Bailian SDK dependencies are missing; no upload was attempted",
                "missing_modules": missing_modules,
            }
        missing_env = [name for name in REQUIRED_ENV if env_presence.get(name) == "MISSING"]
        if missing_env:
            return {
                **base,
                "status": "fail",
                "error_type": "missing_env",
                "summary": "official Bailian KB env is missing; values were not printed and no upload was attempted",
                "missing_env": missing_env,
            }
        return {
            **base,
            "status": "blocked_manual_console_required",
            "error_type": "missing_dependency_or_api_contract",
            "summary": (
                "official SDK dependency/env gates passed, but this repo does not yet implement "
                "the concrete Bailian request models; no upload was attempted"
            ),
        }

