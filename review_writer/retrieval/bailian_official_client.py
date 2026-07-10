from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

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
DEFAULT_REGION = "cn-beijing"
DEFAULT_CATEGORY_ID = "default"
DEFAULT_CATEGORY_TYPE = "UNSTRUCTURED"
ALLOWED_RERANK_MODES = {"qa", "similar", "custom"}
SMOKE_FACT = "review-writer Phase 6c smoke test"
TRANSPORT_MODES = ["inherited_proxy", "no_proxy", "explicit_proxy"]
PROXY_ENV_NAMES = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]
OFFICIAL_UPLOAD_MD = Path("/tmp/bailian_small_kb_upload_payload.md")
MINIMAL_LEASE_PROBE_MD = Path("/tmp/review-writer-lease-probe.md")
OFFICIAL_STEPS = [
    "ApplyFileUploadLease",
    "upload file to pre-signed URL",
    "AddFile",
    "DescribeFile until parse success",
    "CreateIndex",
    "SubmitIndexJob",
    "GetIndexJobStatus",
    "Retrieve",
]
SENSITIVE_RE = re.compile(
    r"(LTAI[A-Za-z0-9]+|sk-[A-Za-z0-9_-]+|AKIA[A-Za-z0-9]+|"
    r"(?i:access[_-]?key|secret|token|authorization|x-bailian-extra|signature)"
    r"\s*[:=]\s*['\"]?[^'\"\\s,}]+)"
)


@dataclass(frozen=True)
class BailianOfficialConfig:
    region: str = DEFAULT_REGION
    endpoint: str = "bailian.cn-beijing.aliyuncs.com"
    category_id: str = DEFAULT_CATEGORY_ID
    endpoint_source: str = "official_default"
    region_source: str = "default"
    category_type: str = DEFAULT_CATEGORY_TYPE
    use_internal_endpoint: bool = False
    parser: str = "DASHSCOPE_DOCMIND"
    structure_type: str = "unstructured"
    source_type: str = "DATA_CENTER_FILE"
    sink_type: str = "DEFAULT"
    rerank_mode: str | None = None
    rerank_instruct: str | None = None
    parse_timeout_seconds: float = 300.0
    index_timeout_seconds: float = 300.0
    poll_interval_seconds: float = 5.0
    request_timeout_seconds: float = 60.0
    transport_mode: str = "inherited_proxy"
    connect_timeout_ms: int = 10000
    read_timeout_ms: int = 20000
    proxy_url_env: str = "HTTPS_PROXY"


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

    def config_report(self) -> dict[str, Any]:
        warnings: list[str] = []
        env_region = os.environ.get("BAILIAN_REGION")
        if env_region and env_region != self.config.region:
            warnings.append(
                "BAILIAN_REGION differs from official KB API default; using explicit endpoint if provided."
            )
        return {
            "region": self.config.region,
            "endpoint": self.config.endpoint,
            "category_id": self.config.category_id,
            "category_type": self.config.category_type,
            "use_internal_endpoint": self.config.use_internal_endpoint,
            "parser": self.config.parser,
            "rerank_mode": self.config.rerank_mode,
            "rerank_instruct_present": bool(self.config.rerank_instruct),
            "endpoint_source": self.config.endpoint_source,
            "region_source": self.config.region_source,
            "warnings": warnings,
        }

    def create_client(self) -> Any:
        self._ensure_runtime_ready()
        from alibabacloud_bailian20231229.client import Client as BailianClient
        from alibabacloud_tea_openapi import models as open_api_models

        config = open_api_models.Config(
            access_key_id=os.environ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
            access_key_secret=os.environ["ALIBABA_CLOUD_ACCESS_KEY_SECRET"],
        )
        config.endpoint = self.config.endpoint
        self._apply_transport_to_config(config)
        return BailianClient(config)

    def calculate_md5(self, file_path: Path) -> str:
        return calculate_md5(file_path)

    def get_file_size(self, file_path: Path) -> int:
        return get_file_size(file_path)

    def apply_file_upload_lease(self, client: Any, workspace_id: str, file_path: Path) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        request = models.ApplyFileUploadLeaseRequest(
            category_type=self.config.category_type,
            file_name=file_path.name,
            md_5=calculate_md5(file_path),
            size_in_bytes=str(get_file_size(file_path)),
            use_internal_endpoint=self.config.use_internal_endpoint,
        )
        response = client.apply_file_upload_lease_with_options(
            self.config.category_id,
            workspace_id,
            request,
            {},
            self._runtime_options(),
        )
        data = _safe_get(response, "body", "data")
        lease_id = _safe_get(data, "file_upload_lease_id")
        param = _safe_get(data, "param")
        url = _safe_get(param, "url")
        headers = _safe_get(param, "headers") or {}
        if not lease_id or not url:
            raise BailianPilotError("upload_rejected", "missing upload lease id or presigned url")
        return {
            "lease_id": lease_id,
            "url": url,
            "headers": headers,
            "status": "lease_granted",
        }

    def list_categories(self, client: Any, workspace_id: str, category_type: str | None = None) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        categories: list[dict[str, Any]] = []
        next_token: str | None = None
        attempts = 0
        while True:
            attempts += 1
            request = models.ListCategoryRequest(max_results=100, next_token=next_token, category_type=category_type)
            response = client.list_category_with_options(workspace_id, request, {}, self._runtime_options())
            body = _safe_get(response, "body")
            data = _safe_get(body, "data")
            raw_categories = (
                _safe_get(data, "category_list")
                or _safe_get(data, "categoryList")
                or _safe_get(data, "categories")
                or []
            )
            for item in raw_categories if isinstance(raw_categories, list) else []:
                categories.append(safe_category_summary(item))
            next_token = _safe_get(data, "next_token") or _safe_get(data, "nextToken")
            if not next_token or attempts >= 10:
                return {
                    "status": "ok",
                    "categories": categories,
                    "categories_count": len(categories),
                    "request_id": _safe_get(body, "request_id") or _safe_get(body, "requestId"),
                    "attempts": attempts,
                }

    def upload_file_to_presigned_url(self, lease: dict[str, Any], file_path: Path) -> dict[str, Any]:
        import requests

        raw_headers = lease.get("headers") or {}
        headers = {
            "Content-Type": raw_headers.get("Content-Type", "text/markdown; charset=utf-8"),
        }
        if raw_headers.get("X-bailian-extra"):
            headers["X-bailian-extra"] = raw_headers["X-bailian-extra"]
        with file_path.open("rb") as handle:
            response = requests.put(
                lease["url"],
                data=handle,
                headers=headers,
                timeout=self.config.request_timeout_seconds,
            )
        if response.status_code >= 400:
            raise BailianPilotError(_classify_status_code(response.status_code), f"upload status {response.status_code}")
        return {"status": "uploaded", "http_status": response.status_code}

    def add_file(self, client: Any, workspace_id: str, lease_id: str) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        request = models.AddFileRequest(
            category_id=self.config.category_id,
            category_type=self.config.category_type,
            lease_id=lease_id,
            parser=self.config.parser,
        )
        response = client.add_file_with_options(workspace_id, request, {}, self._runtime_options())
        file_id = _safe_get(response, "body", "data", "file_id")
        if not file_id:
            raise BailianPilotError("upload_rejected", "missing file id")
        return {"status": "file_added", "file_id": file_id}

    def describe_file_until_parsed(self, client: Any, workspace_id: str, file_id: str) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        deadline = time.monotonic() + self.config.parse_timeout_seconds
        last_status = "UNKNOWN"
        attempts = 0
        while time.monotonic() <= deadline:
            attempts += 1
            response = client.describe_file_with_options(
                workspace_id,
                file_id,
                models.DescribeFileRequest(),
                {},
                self._runtime_options(),
            )
            data = _safe_get(response, "body", "data")
            last_status = _safe_get(data, "status") or last_status
            if last_status == "PARSE_SUCCESS":
                return {"status": "PARSE_SUCCESS", "attempts": attempts}
            if last_status in {"PARSE_FAIL", "PARSE_FAILED", "FAIL", "FAILED"}:
                raise BailianPilotError(
                    "parse_failed",
                    f"parse status {last_status}",
                    {"parse_status": last_status, "parse_error_present": True},
                )
            if last_status not in {"INIT", "PARSING", "PARSE_INIT", "PENDING", "RUNNING", "UNKNOWN"}:
                raise BailianPilotError(
                    "parse_failed",
                    f"parse status {last_status}",
                    {"parse_status": last_status, "parse_error_present": True},
                )
            time.sleep(self.config.poll_interval_seconds)
        raise BailianPilotError(
            "timeout",
            f"parse timeout; last status {last_status}",
            {"parse_status": last_status, "parse_error_present": bool(last_status and last_status != "UNKNOWN")},
        )

    def create_index(self, client: Any, workspace_id: str, file_id: str) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        kwargs = self.create_index_request_kwargs(file_id)
        request = models.CreateIndexRequest(**kwargs)
        response = client.create_index_with_options(workspace_id, request, {}, self._runtime_options())
        index_id = _safe_get(response, "body", "data", "id") or _safe_get(response, "body", "data", "index_id")
        if not index_id:
            raise BailianPilotError("index_id_missing", "missing index id")
        return {"status": "index_created", "index_id": index_id}

    def create_index_request_kwargs(self, file_id: str) -> dict[str, Any]:
        rerank_error = validate_rerank_config(self.config.rerank_mode, self.config.rerank_instruct)
        if rerank_error:
            raise BailianPilotError(rerank_error["error_type"], rerank_error["summary"])
        timestamp = time.strftime("%Y%m%d%H%M%S")
        kwargs: dict[str, Any] = {
            "document_ids": [file_id],
            "name": f"review-writer-clean-3paper-pilot-{timestamp}",
            "source_type": self.config.source_type,
            "sink_type": self.config.sink_type,
            "structure_type": self.config.structure_type,
        }
        if self.config.rerank_mode:
            kwargs["rerank_mode"] = self.config.rerank_mode
        if self.config.rerank_mode == "custom" and self.config.rerank_instruct:
            kwargs["rerank_instruct"] = self.config.rerank_instruct
        return kwargs

    def submit_index_job(self, client: Any, workspace_id: str, index_id: str) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        request = models.SubmitIndexJobRequest(index_id=index_id)
        response = client.submit_index_job_with_options(workspace_id, request, {}, self._runtime_options())
        job_id = _safe_get(response, "body", "data", "id")
        if not job_id:
            raise BailianPilotError("index_failed", "missing index job id")
        return {"status": "index_job_submitted", "job_id": job_id}

    def wait_index_completed(self, client: Any, workspace_id: str, index_id: str, job_id: str) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        deadline = time.monotonic() + self.config.index_timeout_seconds
        last_status = "UNKNOWN"
        attempts = 0
        while time.monotonic() <= deadline:
            attempts += 1
            request = models.GetIndexJobStatusRequest(index_id=index_id, job_id=job_id)
            response = client.get_index_job_status_with_options(workspace_id, request, {}, self._runtime_options())
            last_status = _safe_get(response, "body", "data", "status") or last_status
            if last_status == "COMPLETED":
                return {"status": "COMPLETED", "attempts": attempts}
            if last_status in {"FAILED", "FAIL", "ERROR"}:
                raise BailianPilotError("index_failed", f"index job status {last_status}")
            time.sleep(self.config.poll_interval_seconds)
        raise BailianPilotError("timeout", f"index timeout; last status {last_status}")

    def retrieve_index(
        self,
        client: Any,
        workspace_id: str,
        index_id: str,
        query: str,
        *,
        require_smoke_fact: bool = False,
    ) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        request = models.RetrieveRequest(index_id=index_id, query=query, dense_similarity_top_k=3)
        response = client.retrieve_with_options(workspace_id, request, {}, self._runtime_options())
        nodes = _safe_get(response, "body", "data", "nodes") or []
        evaluation = evaluate_retrieve_nodes(nodes)
        if not evaluation["nodes_count"]:
            raise BailianPilotError("retrieve_empty_nodes", "retrieve returned no nodes")
        if require_smoke_fact and not evaluation["smoke_fact_found"]:
            raise BailianPilotError("retrieve_fact_miss", "retrieve nodes did not contain smoke fact")
        return {"status": "ok", "items": evaluation["items"], **evaluation}

    def delete_index(self, client: Any, workspace_id: str, index_id: str) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        request = models.DeleteIndexRequest(index_id=index_id)
        client.delete_index_with_options(workspace_id, request, {}, self._runtime_options())
        return {"status": "delete_requested", "index_id": index_id}

    def delete_file(self, client: Any, workspace_id: str, file_id: str) -> dict[str, Any]:
        from alibabacloud_bailian20231229 import models

        request = models.DeleteFileRequest()
        client.delete_file_with_options(file_id, workspace_id, request, {}, self._runtime_options())
        return {"status": "delete_requested", "file_id": file_id}

    def cleanup_created_resources(
        self,
        client: Any,
        workspace_id: str,
        *,
        index_id: str | None = None,
        file_id: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "cleanup_attempted": bool(index_id or file_id),
            "cleanup_status": "not_needed",
            "index_cleanup": "not_created",
            "file_cleanup": "not_created",
            "cleanup_error_type": None,
            "created_resource_ids_cleaned": "not_created",
            "cleanup_errors": [],
        }
        if not index_id and not file_id:
            return result
        result["cleanup_status"] = "pass"
        if index_id:
            try:
                self.delete_index(client, workspace_id, index_id)
                result["index_cleanup"] = "pass"
            except Exception as exc:  # noqa: BLE001 - cleanup must be best-effort and reported safely.
                result["cleanup_status"] = "fail"
                result["index_cleanup"] = "fail"
                result["cleanup_error_type"] = result["cleanup_error_type"] or "index_cleanup_failed"
                result["cleanup_errors"].append(
                    safe_error_from_exception(
                        exc,
                        operation_name="DeleteIndex",
                        phase="cleanup_index",
                        endpoint=self.config.endpoint,
                    )
                )
        if file_id:
            try:
                self.delete_file(client, workspace_id, file_id)
                result["file_cleanup"] = "pass"
            except Exception as exc:  # noqa: BLE001 - cleanup must be best-effort and reported safely.
                result["cleanup_status"] = "fail"
                result["file_cleanup"] = "fail"
                result["cleanup_error_type"] = result["cleanup_error_type"] or "file_cleanup_failed"
                result["cleanup_errors"].append(
                    safe_error_from_exception(
                        exc,
                        operation_name="DeleteFile",
                        phase="cleanup_file",
                        endpoint=self.config.endpoint,
                    )
                )
        if result["cleanup_status"] == "pass":
            result["created_resource_ids_cleaned"] = "yes"
        elif result["cleanup_status"] == "fail":
            result["created_resource_ids_cleaned"] = "no"
        return result

    def run_lease_probe(
        self,
        *,
        payload_md: Path,
        allow_network: bool,
        use_official_sdk: bool,
    ) -> dict[str, Any]:
        base = {
            "provider_name": self.provider_name,
            "region": self.config.region,
            "endpoint": self.config.endpoint,
            "category_id": self.config.category_id,
            "config": self.config_report(),
            "operation_name": "ApplyFileUploadLease",
            "first_failed_phase": None,
            "dependency_presence": self.dependency_presence(),
            "env_presence": self.env_presence(),
            "payload_md": str(payload_md),
            "file_name": payload_md.name,
            "file_size": get_file_size(payload_md) if payload_md.exists() else 0,
            "md5_prefix": calculate_md5(payload_md)[:8] if payload_md.exists() else None,
            "lease_obtained": False,
            "lease_id_present": False,
            "upload_url_present": False,
            "headers_present": False,
            "network_attempted": False,
            "upload_attempted": False,
            "knowledge_base_created": False,
            "safe_error": None,
            "recommended_fix": None,
        }
        if not allow_network or not use_official_sdk:
            return {
                **base,
                "status": "dry_run",
                "error_type": None,
                "summary": "lease probe dry-run only; no network call was made",
            }
        readiness = self._readiness_error(base)
        if readiness:
            return {
                **readiness,
                "operation_name": "ApplyFileUploadLease",
                "first_failed_phase": "readiness",
                "recommended_fix": recommended_fix(readiness.get("error_type")),
            }
        allowed_payloads = {OFFICIAL_UPLOAD_MD.resolve(), MINIMAL_LEASE_PROBE_MD.resolve()}
        if payload_md.resolve() not in allowed_payloads:
            return {
                **base,
                "status": "fail",
                "error_type": "upload_rejected",
                "summary": "lease probe only allows approved /tmp payload paths",
                "first_failed_phase": "payload_guard",
                "recommended_fix": recommended_fix("upload_rejected"),
            }
        if not payload_md.exists():
            return {
                **base,
                "status": "fail",
                "error_type": "upload_rejected",
                "summary": "lease probe payload markdown is missing",
                "first_failed_phase": "payload_guard",
                "recommended_fix": recommended_fix("upload_rejected"),
            }
        phase = "create_client"
        try:
            with self.transport_environment():
                client = self.create_client()
                workspace_id = os.environ["WORKSPACE_ID"]
                phase = "apply_file_upload_lease"
                lease = self.apply_file_upload_lease(client, workspace_id, payload_md)
            headers = lease.get("headers") or {}
            return {
                **base,
                "status": "pass",
                "error_type": None,
                "summary": "ApplyFileUploadLease succeeded; no upload was attempted",
                "lease_obtained": True,
                "lease_id_present": bool(lease.get("lease_id")),
                "upload_url_present": bool(lease.get("url")),
                "headers_present": bool(headers),
                "network_attempted": True,
                "upload_attempted": False,
                "knowledge_base_created": False,
            }
        except Exception as exc:  # noqa: BLE001 - forensic report must classify SDK exceptions.
            safe_error = safe_error_from_exception(
                exc,
                operation_name="ApplyFileUploadLease",
                phase=phase,
                endpoint=self.config.endpoint,
            )
            return {
                **base,
                "status": "fail",
                "error_type": safe_error["error_type"],
                "summary": safe_error["message_redacted"] or safe_error["exception_class"],
                "first_failed_phase": phase,
                "operation_name": "ApplyFileUploadLease",
                "safe_error": safe_error,
                "recommended_fix": recommended_fix(safe_error["error_type"]),
                "network_attempted": phase != "create_client",
                "upload_attempted": False,
                "knowledge_base_created": False,
            }

    def run_small_kb_pilot(
        self,
        *,
        upload_file: Path,
        questions: list[dict[str, Any]],
        allow_network: bool,
        allow_upload: bool,
        cleanup: bool = False,
        cleanup_index_id: str | None = None,
    ) -> dict[str, Any]:
        dependency_presence = self.dependency_presence()
        env_presence = self.env_presence()
        base: dict[str, Any] = {
            "provider_name": self.provider_name,
            "region": self.config.region,
            "endpoint": self.config.endpoint,
            "category_id": self.config.category_id,
            "config": self.config_report(),
            "dependency_presence": dependency_presence,
            "env_presence": env_presence,
            "official_steps": OFFICIAL_STEPS,
            "upload_file": str(upload_file),
            "upload_file_size": get_file_size(upload_file) if upload_file.exists() else 0,
            "kb_name_template": "review-writer-clean-3paper-pilot-<timestamp>",
            "kb_id_redacted_or_tmp_only": None,
            "file_id": None,
            "index_id": None,
            "job_id": None,
            "network_attempted": False,
            "upload_attempted": False,
            "knowledge_base_created": False,
            "index_created": False,
            "cleanup_requested": cleanup,
            "cleanup_index_id_provided": bool(cleanup_index_id),
            "cleanup_attempted": False,
            "cleanup_status": "not_needed",
            "index_cleanup": "not_created",
            "file_cleanup": "not_created",
            "cleanup_error_type": None,
            "created_resource_ids_cleaned": "not_created",
            "cleanup_errors": [],
            "file_id_present": False,
            "index_id_present": False,
            "job_id_present": False,
            "manual_cleanup_required": False,
            "parse_status": None,
            "parse_error_present": False,
            "skipped_because_upstream_parse_failed": False,
            "retrieval_status": "not_run",
            "nodes_count": 0,
            "top_score": None,
            "smoke_fact_found": False,
            "signed_url_present": False,
            "signed_url_redacted": True,
            "recall_at_1": None,
            "recall_at_3": None,
            "citation_coverage": None,
            "per_question_results": [],
        }
        if not allow_network or (not allow_upload and not cleanup):
            return {
                **base,
                "status": "dry_run",
                "error_type": None,
                "summary": "official SDK dry-run only; no network or upload was attempted",
            }
        readiness = self._readiness_error(base)
        if readiness:
            return readiness
        state = {
            "network_attempted": False,
            "upload_attempted": False,
            "knowledge_base_created": False,
            "index_created": False,
            "created_file_id": None,
            "created_index_id": None,
            "created_job_id": None,
        }
        phase = "create_client"
        operation_name = "create_client"
        client = None
        workspace_id = None
        try:
            with self.transport_environment():
                client = self.create_client()
                workspace_id = os.environ["WORKSPACE_ID"]
                if cleanup and cleanup_index_id:
                    result = self.delete_index(client, workspace_id, cleanup_index_id)
                    return {
                        **base,
                        "status": "pass",
                        "error_type": None,
                        "summary": "cleanup delete request completed",
                        "network_attempted": True,
                        "cleanup_result": result,
                        "cleanup_attempted": True,
                        "cleanup_status": "pass",
                        "index_cleanup": "pass",
                        "created_resource_ids_cleaned": "yes",
                    }
                if upload_file.resolve() != OFFICIAL_UPLOAD_MD.resolve():
                    return {
                        **base,
                        "status": "fail",
                        "error_type": "upload_rejected",
                        "summary": "real pilot only allows /tmp/bailian_small_kb_upload_payload.md",
                    }
                if not upload_file.exists():
                    return {
                        **base,
                        "status": "fail",
                        "error_type": "upload_rejected",
                        "summary": "upload markdown is missing",
                    }
                state["network_attempted"] = True
                phase = "apply_file_upload_lease"
                operation_name = "ApplyFileUploadLease"
                lease = self.apply_file_upload_lease(client, workspace_id, upload_file)
                state["upload_attempted"] = True
                phase = "upload_file_to_presigned_url"
                operation_name = "PUT pre-signed upload URL"
                upload_result = self.upload_file_to_presigned_url(lease, upload_file)
                phase = "add_file"
                operation_name = "AddFile"
                add_result = self.add_file(client, workspace_id, lease["lease_id"])
                state["created_file_id"] = add_result["file_id"]
                phase = "describe_file_until_parsed"
                operation_name = "DescribeFile"
                parse_result = self.describe_file_until_parsed(client, workspace_id, add_result["file_id"])
                phase = "create_index"
                operation_name = "CreateIndex"
                index_result = self.create_index(client, workspace_id, add_result["file_id"])
                state["created_index_id"] = index_result["index_id"]
                state["knowledge_base_created"] = True
                state["index_created"] = True
                phase = "submit_index_job"
                operation_name = "SubmitIndexJob"
                submit_result = self.submit_index_job(client, workspace_id, index_result["index_id"])
                state["created_job_id"] = submit_result["job_id"]
                phase = "wait_index_completed"
                operation_name = "GetIndexJobStatus"
                index_status = self.wait_index_completed(
                    client,
                    workspace_id,
                    index_result["index_id"],
                    submit_result["job_id"],
                )
                phase = "retrieve_index"
                operation_name = "Retrieve"
                retrieval = self._run_retrieval(client, workspace_id, index_result["index_id"], questions)
                cleanup_result = self.cleanup_created_resources(
                    client,
                    workspace_id,
                    index_id=index_result["index_id"] if cleanup else None,
                    file_id=add_result["file_id"] if cleanup else None,
                )
            cleanup_failed = cleanup_result.get("cleanup_status") == "fail"
            return {
                **base,
                "status": "fail" if cleanup_failed else "pass",
                "error_type": "cleanup_failed" if cleanup_failed else None,
                "summary": (
                    "official Bailian small-KB pilot completed but cleanup failed"
                    if cleanup_failed
                    else "official Bailian small-KB pilot completed"
                ),
                "network_attempted": state["network_attempted"],
                "upload_attempted": state["upload_attempted"],
                "knowledge_base_created": state["knowledge_base_created"],
                "index_created": state["index_created"],
                **cleanup_result,
                "file_id": add_result["file_id"],
                "index_id": index_result["index_id"],
                "job_id": submit_result["job_id"],
                "file_id_present": bool(add_result.get("file_id")),
                "index_id_present": bool(index_result.get("index_id")),
                "job_id_present": bool(submit_result.get("job_id")),
                "manual_cleanup_required": cleanup_result.get("created_resource_ids_cleaned") == "no",
                "kb_id_redacted_or_tmp_only": index_result["index_id"],
                "upload_status": upload_result["status"],
                "parse_status": parse_result["status"],
                "parse_error_present": False,
                "skipped_because_upstream_parse_failed": False,
                "index_status": index_status["status"],
                "retrieval_status": retrieval["status"],
                "nodes_count": retrieval["nodes_count"],
                "top_score": retrieval["top_score"],
                "smoke_fact_found": retrieval["smoke_fact_found"],
                "signed_url_present": retrieval["signed_url_present"],
                "signed_url_redacted": True,
                "recall_at_1": retrieval["recall_at_1"],
                "recall_at_3": retrieval["recall_at_3"],
                "citation_coverage": retrieval["citation_coverage"],
                "per_question_results": retrieval["per_question_results"],
                "cleanup_recommendation": (
                    "Temporary resources were cleaned up automatically."
                    if cleanup_result.get("cleanup_status") == "pass"
                    else "Temporary resources may remain; inspect cleanup_errors and delete manually in console."
                ),
            }
        except BailianPilotError as exc:
            cleanup_result = self.cleanup_created_resources(
                client,
                workspace_id,
                index_id=state.get("created_index_id") if cleanup and client and workspace_id else None,
                file_id=state.get("created_file_id") if cleanup and client and workspace_id else None,
            )
            safe_error = safe_error_from_exception(
                exc,
                operation_name=operation_name,
                phase=phase,
                endpoint=self.config.endpoint,
                error_type=exc.error_type,
            )
            return {
                **base,
                **state,
                **cleanup_result,
                "status": "fail",
                "error_type": exc.error_type,
                "summary": exc.safe_summary,
                "first_failed_phase": phase,
                "operation_name": operation_name,
                "safe_error": safe_error,
                "recommended_fix": recommended_fix(exc.error_type),
                "file_id_present": bool(state.get("created_file_id")),
                "index_id_present": bool(state.get("created_index_id")),
                "job_id_present": bool(state.get("created_job_id")),
                "manual_cleanup_required": bool(state.get("created_file_id") and cleanup_result.get("file_cleanup") == "fail"),
                "parse_status": exc.details.get("parse_status"),
                "parse_error_present": bool(exc.details.get("parse_error_present")),
                "skipped_because_upstream_parse_failed": exc.error_type == "parse_failed",
            }
        except Exception as exc:  # noqa: BLE001 - report a safe error category without leaking values.
            cleanup_result = self.cleanup_created_resources(
                client,
                workspace_id,
                index_id=state.get("created_index_id") if cleanup and client and workspace_id else None,
                file_id=state.get("created_file_id") if cleanup and client and workspace_id else None,
            )
            safe_error = safe_error_from_exception(
                exc,
                operation_name=operation_name,
                phase=phase,
                endpoint=self.config.endpoint,
            )
            return {
                **base,
                **state,
                **cleanup_result,
                "status": "fail",
                "error_type": safe_error["error_type"],
                "summary": safe_error["message_redacted"] or safe_error["exception_class"],
                "first_failed_phase": phase,
                "operation_name": operation_name,
                "safe_error": safe_error,
                "recommended_fix": recommended_fix(safe_error["error_type"]),
                "file_id_present": bool(state.get("created_file_id")),
                "index_id_present": bool(state.get("created_index_id")),
                "job_id_present": bool(state.get("created_job_id")),
                "manual_cleanup_required": bool(state.get("created_file_id") and cleanup_result.get("file_cleanup") == "fail"),
                "parse_status": None,
                "parse_error_present": False,
                "skipped_because_upstream_parse_failed": False,
            }

    def _run_retrieval(
        self,
        client: Any,
        workspace_id: str,
        index_id: str,
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        hit_at_1 = 0
        hit_at_3 = 0
        citation_hits = 0
        total = len(questions)
        nodes_count_total = 0
        top_score: float | None = None
        signed_url_present = False
        for question in questions:
            query = str(question.get("question") or question.get("query") or "")
            expected = _expected_ids(question)
            retrieved = self.retrieve_index(client, workspace_id, index_id, query)
            items = retrieved["items"]
            nodes_count_total += int(retrieved.get("nodes_count") or 0)
            if top_score is None and retrieved.get("top_score") is not None:
                top_score = retrieved.get("top_score")
            signed_url_present = signed_url_present or bool(retrieved.get("signed_url_present"))
            top_ids = [item["paper_id"] for item in items if item.get("paper_id")]
            hit1 = bool(expected and top_ids[:1] and top_ids[0] in expected)
            hit3 = bool(expected and any(paper_id in expected for paper_id in top_ids[:3]))
            if hit1:
                hit_at_1 += 1
            if hit3:
                hit_at_3 += 1
            if top_ids:
                citation_hits += 1
            results.append(
                {
                    "question_id": question.get("id") or question.get("question_id"),
                    "expected_paper_ids": sorted(expected),
                    "retrieved_paper_ids_top3": top_ids[:3],
                    "hit_at_1": hit1,
                    "hit_at_3": hit3,
                }
            )
        smoke_retrieval = self.retrieve_index(
            client,
            workspace_id,
            index_id,
            SMOKE_FACT,
            require_smoke_fact=True,
        )
        return {
            "status": "ok",
            "recall_at_1": round(hit_at_1 / total, 4) if total else None,
            "recall_at_3": round(hit_at_3 / total, 4) if total else None,
            "citation_coverage": round(citation_hits / total, 4) if total else None,
            "per_question_results": results,
            "nodes_count": nodes_count_total + int(smoke_retrieval.get("nodes_count") or 0),
            "top_score": top_score if top_score is not None else smoke_retrieval.get("top_score"),
            "smoke_fact_found": bool(smoke_retrieval.get("smoke_fact_found")),
            "signed_url_present": signed_url_present or bool(smoke_retrieval.get("signed_url_present")),
            "signed_url_redacted": True,
        }

    def _runtime_options(self) -> Any:
        from alibabacloud_tea_util import models as util_models

        runtime = util_models.RuntimeOptions(
            connect_timeout=int(self.config.request_timeout_seconds * 1000),
            read_timeout=int(self.config.request_timeout_seconds * 1000),
        )
        self._apply_transport_to_runtime(runtime)
        return runtime

    @contextmanager
    def transport_environment(self) -> Iterator[None]:
        if self.config.transport_mode != "no_proxy":
            yield
            return
        saved = {name: os.environ.get(name) for name in PROXY_ENV_NAMES}
        try:
            for name in PROXY_ENV_NAMES:
                os.environ.pop(name, None)
            yield
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def transport_report(self) -> dict[str, Any]:
        capabilities = sdk_transport_capabilities()
        return {
            "transport_mode": self.config.transport_mode,
            "connect_timeout_ms": self.config.connect_timeout_ms,
            "read_timeout_ms": self.config.read_timeout_ms,
            "proxy_url_env": self.config.proxy_url_env,
            "proxy_url_env_set": bool(os.environ.get(self.config.proxy_url_env)),
            "proxy_env_set_names": proxy_env_set_names(),
            "capabilities": capabilities,
        }

    def _apply_transport_to_config(self, config: Any) -> None:
        _set_supported_field(config, "connect_timeout", self.config.connect_timeout_ms)
        _set_supported_field(config, "read_timeout", self.config.read_timeout_ms)
        if self.config.transport_mode != "explicit_proxy":
            return
        proxy_url = os.environ.get(self.config.proxy_url_env)
        if not proxy_url:
            raise BailianPilotError("explicit_proxy_missing", "explicit proxy env is missing")
        applied = False
        for field in ("proxy", "http_proxy", "https_proxy"):
            if _field_supported(config, field):
                setattr(config, field, proxy_url)
                applied = True
        if not applied:
            caps = sdk_transport_capabilities()
            runtime_supports_proxy = any(caps["runtime_options"].get(name) for name in ("proxy", "http_proxy", "https_proxy"))
            if not runtime_supports_proxy:
                raise BailianPilotError("explicit_proxy_unsupported", "SDK Config/RuntimeOptions do not expose proxy fields")

    def _apply_transport_to_runtime(self, runtime: Any) -> None:
        _set_supported_field(runtime, "connect_timeout", self.config.connect_timeout_ms)
        _set_supported_field(runtime, "read_timeout", self.config.read_timeout_ms)
        if self.config.transport_mode != "explicit_proxy":
            return
        proxy_url = os.environ.get(self.config.proxy_url_env)
        if not proxy_url:
            raise BailianPilotError("explicit_proxy_missing", "explicit proxy env is missing")
        applied = False
        for field in ("proxy", "http_proxy", "https_proxy"):
            if _field_supported(runtime, field):
                setattr(runtime, field, proxy_url)
                applied = True
        if not applied:
            caps = sdk_transport_capabilities()
            config_supports_proxy = any(caps["config"].get(name) for name in ("proxy", "http_proxy", "https_proxy"))
            if not config_supports_proxy:
                raise BailianPilotError("explicit_proxy_unsupported", "SDK Config/RuntimeOptions do not expose proxy fields")

    def _ensure_runtime_ready(self) -> None:
        missing_modules = [name for name, status in self.dependency_presence().items() if status == "MISSING"]
        if missing_modules:
            raise BailianPilotError("missing_dependency_or_api_contract", "official Bailian SDK modules are missing")
        missing_env = [name for name, status in self.env_presence().items() if name in REQUIRED_ENV and status == "MISSING"]
        if missing_env:
            raise BailianPilotError("missing_env", "official Bailian SDK env is missing")

    def _readiness_error(self, base: dict[str, Any]) -> dict[str, Any] | None:
        rerank_error = validate_rerank_config(self.config.rerank_mode, self.config.rerank_instruct)
        if rerank_error:
            return {
                **base,
                "status": "fail",
                "error_type": rerank_error["error_type"],
                "summary": rerank_error["summary"],
            }
        missing_modules = [name for name, status in base["dependency_presence"].items() if status == "MISSING"]
        if missing_modules:
            return {
                **base,
                "status": "fail",
                "error_type": "missing_dependency_or_api_contract",
                "summary": "official Bailian SDK dependencies are missing; no upload was attempted",
                "missing_modules": missing_modules,
            }
        missing_env = [name for name in REQUIRED_ENV if base["env_presence"].get(name) == "MISSING"]
        if missing_env:
            return {
                **base,
                "status": "fail",
                "error_type": "missing_env",
                "summary": "official Bailian KB env is missing; values were not printed and no upload was attempted",
                "missing_env": missing_env,
            }
        return None


class BailianPilotError(RuntimeError):
    def __init__(self, error_type: str, safe_summary: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(safe_summary)
        self.error_type = error_type
        self.safe_summary = safe_summary
        self.details = details or {}


def validate_rerank_config(rerank_mode: str | None, rerank_instruct: str | None) -> dict[str, str] | None:
    if rerank_mode and rerank_mode not in ALLOWED_RERANK_MODES:
        return {
            "error_type": "invalid_rerank_mode",
            "summary": "rerank_mode must be one of qa, similar, custom",
        }
    if rerank_instruct and rerank_mode != "custom":
        return {
            "error_type": "invalid_rerank_instruct",
            "summary": "rerank_instruct is allowed only when rerank_mode=custom",
        }
    return None


def evaluate_retrieve_nodes(nodes: Any, smoke_fact: str = SMOKE_FACT) -> dict[str, Any]:
    items = _normalize_retrieval_nodes(nodes)
    top_score = next((item.get("score") for item in items if item.get("score") is not None), None)
    node_text = " ".join(item.get("text_excerpt", "") for item in items)
    return {
        "nodes_count": len(items),
        "top_score": top_score,
        "smoke_fact_found": smoke_fact in node_text,
        "signed_url_present": _contains_signed_url(nodes),
        "signed_url_redacted": True,
        "items": [{key: value for key, value in item.items() if key != "text_excerpt"} for item in items],
    }


def calculate_md5(file_path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - required by Bailian upload lease API.
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_file_size(file_path: Path) -> int:
    return file_path.stat().st_size


def classify_exception(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    request_id = _first_present(exc, ["request_id", "requestId", "RequestId"])
    text = _exception_chain_text(exc).lower()
    error_code = str(_first_present(exc, ["error_code", "code", "errorCode"]) or "").lower()
    combined = f"{error_code} {text}"
    if "missingcategorytype" in combined or "missing category type" in combined:
        return "category_type_required"
    if "invalidcategory" in combined or "invalid category" in combined:
        return "invalid_category"
    if "category" in combined and ("invalid" in combined or "not found" in combined):
        return "category_error"
    if isinstance(status_code, int):
        return _classify_status_code(status_code)
    if not request_id and _has_transport_signal(text):
        return "transport_error"
    if "invalidaccesskey" in text or "invalid access key" in text:
        return "auth_or_permission_error"
    if "forbidden" in text or "401" in text or "unauthorized" in text:
        return "auth_or_permission_error"
    if "accessdenied" in text or "access denied" in text:
        return "workspace_or_permission_error"
    if "workspace" in text and ("invalid" in text or "not found" in text):
        return "workspace_or_permission_error"
    if "endpoint" in text or "region" in text or "host" in text or "name or service not known" in text:
        return "endpoint_or_region_error"
    if "model" in text or "parameter" in text or "argument" in text or "request" in text:
        return "invalid_request_model"
    if "429" in text or "quota" in text or "rate" in text:
        return "quota_or_rate_limit_429"
    if "503" in text or "server" in text:
        return "server_error_5xx"
    return "unexpected_error"


def safe_error_from_exception(
    exc: Exception,
    *,
    operation_name: str,
    phase: str,
    endpoint: str,
    error_type: str | None = None,
) -> dict[str, Any]:
    data = _safe_get(exc, "data")
    if data is None:
        data = _safe_get(exc, "body", "data")
    cause = getattr(exc, "__cause__", None)
    context = getattr(exc, "__context__", None)
    return {
        "error_type": error_type or classify_exception(exc),
        "exception_class": type(exc).__name__,
        "exception_module": type(exc).__module__,
        "repr_redacted": redact_sensitive(repr(exc)),
        "str_redacted": redact_sensitive(str(exc)),
        "cause_class": type(cause).__name__ if cause else None,
        "cause_message_redacted": redact_sensitive(str(cause)) if cause else None,
        "context_class": type(context).__name__ if context else None,
        "context_message_redacted": redact_sensitive(str(context)) if context else None,
        "args_count": len(getattr(exc, "args", []) or []),
        "has_code_attr": hasattr(exc, "code"),
        "has_status_code_attr": hasattr(exc, "status_code"),
        "has_request_id_attr": any(hasattr(exc, name) for name in ["request_id", "requestId", "RequestId"]),
        "error_code": _first_present(exc, ["error_code", "code", "errorCode"]),
        "status_code": _first_present(exc, ["status_code", "statusCode", "status"]),
        "request_id": _first_present(exc, ["request_id", "requestId", "RequestId"]),
        "message_redacted": redact_sensitive(
            str(_first_present(exc, ["message", "description"]) or str(exc) or type(exc).__name__)
        ),
        "data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "endpoint": endpoint,
        "operation_name": operation_name,
        "phase": phase,
    }


def redact_sensitive(text: str) -> str:
    for name in PROXY_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "[REDACTED_PROXY]")
    text = SENSITIVE_RE.sub("[REDACTED]", text)
    text = re.sub(r"https://[^\\s]+", "[REDACTED_URL]", text)
    return text[:500]


def recommended_fix(error_type: str | None) -> str:
    mapping = {
        "transport_error": "Check WSL/conda DNS, proxy, TCP/TLS reachability, and endpoint connectivity before changing request fields.",
        "auth_or_permission_error": "Verify Alibaba Cloud AccessKey status, RAM permissions, and workspace access; do not paste key values into logs.",
        "auth_error_401": "Verify Alibaba Cloud AccessKey permissions and that the key is active; do not paste key values into logs.",
        "workspace_or_permission_error": "Check WORKSPACE_ID, RAM permissions, and whether the principal has joined the Bailian workspace.",
        "access_denied_workspace": "Grant the AccessKey principal Bailian workspace permissions for the target WORKSPACE_ID.",
        "invalid_workspace": "Check WORKSPACE_ID and region; the workspace must exist in the selected Bailian endpoint region.",
        "category_error": "Check whether the requested category_id exists and whether category_type is accepted by this workspace.",
        "invalid_category": "Check category_id/category_type; create or select a valid category before full upload.",
        "category_type_required": "ListCategory requires an explicit category_type for this workspace/API version; confirm valid values before retry.",
        "invalid_request_model": "Compare SDK request fields with the installed SDK version and official API contract.",
        "index_failed": "Inspect CreateIndex request fields, category id/type, document parse state, and workspace index permissions before another full pilot.",
        "index_id_missing": "CreateIndex returned without a parsed index id; inspect response shape and manual success parameters before retry.",
        "parse_failed": "Inspect DescribeFile parse status and parser configuration before creating an index.",
        "cleanup_failed": "Inspect cleanup_errors and delete any temporary resources manually in the Bailian console if needed.",
        "invalid_rerank_mode": "Use no rerank mode by default, or explicitly choose qa, similar, or custom.",
        "invalid_rerank_instruct": "Only provide rerank_instruct when rerank_mode=custom.",
        "retrieve_empty_nodes": "Retrieve returned no nodes; inspect index job status and payload ingestion before retry.",
        "retrieve_fact_miss": "Retrieve returned nodes but missed the Phase 6c smoke fact; inspect payload indexing and query routing.",
        "endpoint_or_region_error": "Verify endpoint and BAILIAN_REGION alignment, especially cn-beijing versus other regions.",
        "missing_env": "Set required env only in a temporary shell or isolated manual bridge; do not commit secrets.",
        "missing_dependency_or_api_contract": "Run inside the isolated conda env with official Bailian SDK packages installed.",
        "explicit_proxy_missing": "Set a temporary proxy env for the selected proxy-url-env or use inherited_proxy/no_proxy mode.",
        "explicit_proxy_unsupported": "Installed SDK does not expose proxy fields; use inherited_proxy/no_proxy or manual console pilot.",
        "upload_rejected": "Regenerate the sanitized /tmp payload and ensure only the allowed markdown path is used.",
        "timeout": "Check network/proxy reachability and consider a lease-only retry only after review.",
        "unexpected_error": "Inspect safe_error fields, then decide whether endpoint, workspace, category, or request model needs adjustment.",
    }
    return mapping.get(error_type or "", "Inspect safe_error fields and avoid retrying full upload until the cause is clear.")


def _exception_chain_text(exc: Exception) -> str:
    parts = [type(exc).__name__, str(exc), repr(exc)]
    for chained in [getattr(exc, "__cause__", None), getattr(exc, "__context__", None)]:
        if chained:
            parts.extend([type(chained).__name__, str(chained), repr(chained)])
    return " ".join(parts)


def _has_transport_signal(text: str) -> bool:
    signals = [
        "dns",
        "name or service not known",
        "temporary failure in name resolution",
        "connection refused",
        "connection reset",
        "connect timeout",
        "read timed out",
        "timeout",
        "proxy",
        "ssl",
        "tls",
        "certificate",
        "network is unreachable",
    ]
    return any(signal in text for signal in signals)


def endpoint_for_region(region: str) -> str:
    return f"bailian.{region}.aliyuncs.com"


def make_bailian_config(
    *,
    endpoint: str | None = None,
    region: str | None = None,
    category_id: str | None = None,
    category_type: str = DEFAULT_CATEGORY_TYPE,
    transport_mode: str = "inherited_proxy",
    connect_timeout_ms: int = 10000,
    read_timeout_ms: int = 20000,
    proxy_url_env: str = "HTTPS_PROXY",
    rerank_mode: str | None = None,
    rerank_instruct: str | None = None,
) -> BailianOfficialConfig:
    if transport_mode not in TRANSPORT_MODES:
        raise ValueError(f"unsupported transport mode: {transport_mode}")
    resolved_region = region or DEFAULT_REGION
    resolved_endpoint = endpoint or endpoint_for_region(resolved_region)
    return BailianOfficialConfig(
        region=resolved_region,
        endpoint=resolved_endpoint,
        category_id=category_id or DEFAULT_CATEGORY_ID,
        category_type=category_type,
        endpoint_source="explicit" if endpoint else ("region" if region else "official_default"),
        region_source="explicit" if region else "default",
        transport_mode=transport_mode,
        connect_timeout_ms=connect_timeout_ms,
        read_timeout_ms=read_timeout_ms,
        proxy_url_env=proxy_url_env,
        rerank_mode=rerank_mode,
        rerank_instruct=rerank_instruct,
    )


def category_sdk_capabilities() -> dict[str, Any]:
    request_models = [
        "ListCategoryRequest",
        "ListCategoryResponseBodyDataCategoryList",
        "AddCategoryRequest",
        "DeleteCategoryRequest",
    ]
    client_methods = [
        "list_category_with_options",
        "list_category",
        "add_category_with_options",
        "delete_category_with_options",
    ]
    return {
        "modules": {module: _module_status(module) for module in REQUIRED_SDK_MODULES},
        "request_models": {name: _sdk_model_fields(name) for name in request_models},
        "client_methods": {name: _client_method_signature(name) for name in client_methods},
        "has_list_category_request": _sdk_model_exists("ListCategoryRequest"),
        "has_list_category_with_options": _client_method_exists("list_category_with_options"),
        "has_create_category_request": _sdk_model_exists("AddCategoryRequest"),
    }


def _sdk_model_exists(class_name: str) -> bool:
    try:
        mod = importlib.import_module("alibabacloud_bailian20231229.models")
        return hasattr(mod, class_name)
    except Exception:
        return False


def _client_method_exists(method_name: str) -> bool:
    try:
        mod = importlib.import_module("alibabacloud_bailian20231229.client")
        return hasattr(getattr(mod, "Client"), method_name)
    except Exception:
        return False


def _sdk_model_fields(class_name: str) -> dict[str, Any]:
    try:
        mod = importlib.import_module("alibabacloud_bailian20231229.models")
        cls = getattr(mod, class_name)
        signature = inspect.signature(cls.__init__)
        parameters = [name for name in signature.parameters if name != "self"]
        try:
            instance_fields = [name for name in vars(cls()).keys() if not name.startswith("_")]
        except Exception:
            instance_fields = []
        return {
            "exists": True,
            "signature_fields": parameters,
            "instance_fields": sorted(set(instance_fields)),
        }
    except Exception as exc:  # noqa: BLE001 - offline introspection must tolerate missing SDK.
        return {"exists": False, "error_class": type(exc).__name__, "signature_fields": [], "instance_fields": []}


def _client_method_signature(method_name: str) -> dict[str, Any]:
    try:
        mod = importlib.import_module("alibabacloud_bailian20231229.client")
        method = getattr(getattr(mod, "Client"), method_name)
        return {"exists": True, "signature": str(inspect.signature(method))}
    except Exception as exc:  # noqa: BLE001
        return {"exists": False, "error_class": type(exc).__name__, "signature": None}


def proxy_env_set_names() -> list[str]:
    return [name for name in PROXY_ENV_NAMES if os.environ.get(name)]


def safe_category_summary(category: Any) -> dict[str, Any]:
    category_id = _safe_get(category, "category_id") or _safe_get(category, "categoryId")
    category_name = _safe_get(category, "category_name") or _safe_get(category, "categoryName")
    category_type = _safe_get(category, "category_type") or _safe_get(category, "categoryType")
    parent_id = _safe_get(category, "parent_category_id") or _safe_get(category, "parentCategoryId")
    is_default = bool(_safe_get(category, "is_default") or _safe_get(category, "isDefault"))
    status = _safe_get(category, "status")
    return {
        "category_id": str(category_id) if category_id is not None else None,
        "name_redacted_or_plain_if_safe": safe_category_name(category_name),
        "type": str(category_type) if category_type is not None else None,
        "parent_id_present": bool(parent_id),
        "status": str(status) if status is not None else None,
        "is_default_candidate": is_default or str(category_id or "").lower() == "default",
    }


def safe_category_name(name: Any) -> str | None:
    if name is None:
        return None
    text = str(name).strip()
    if not text:
        return None
    if SENSITIVE_RE.search(text) or len(text) > 120:
        return "[REDACTED_CATEGORY_NAME]"
    return text


def recommend_category(categories: list[dict[str, Any]]) -> dict[str, Any]:
    if not categories:
        return {
            "recommended_category_id": None,
            "recommended_category_type": None,
            "recommended_reason": "no categories returned; category discovery or workspace permissions need review",
        }
    preferred = [
        item
        for item in categories
        if item.get("is_default_candidate") and item.get("category_id") and item.get("type")
    ]
    if not preferred:
        preferred = [item for item in categories if item.get("category_id") and item.get("type")]
    if not preferred:
        preferred = [item for item in categories if item.get("category_id")]
    chosen = preferred[0] if preferred else {}
    return {
        "recommended_category_id": chosen.get("category_id"),
        "recommended_category_type": chosen.get("type"),
        "recommended_reason": (
            "selected default candidate from ListCategory"
            if chosen.get("is_default_candidate")
            else "selected first category with id/type from ListCategory"
        ),
    }


def sdk_transport_capabilities() -> dict[str, Any]:
    return {
        "modules": {module: _module_status(module) for module in REQUIRED_SDK_MODULES},
        "config": _class_field_support("alibabacloud_tea_openapi.models", "Config"),
        "runtime_options": _class_field_support("alibabacloud_tea_util.models", "RuntimeOptions"),
    }


def _module_status(module: str) -> str:
    try:
        importlib.import_module(module)
        return "INSTALLED"
    except Exception:
        return "MISSING"


def _class_field_support(module: str, class_name: str) -> dict[str, Any]:
    target_fields = [
        "proxy",
        "http_proxy",
        "https_proxy",
        "connect_timeout",
        "read_timeout",
        "autoretry",
        "ignore_ssl",
    ]
    try:
        mod = importlib.import_module(module)
        cls = getattr(mod, class_name)
        signature = inspect.signature(cls.__init__)
        parameters = [name for name in signature.parameters if name != "self"]
        try:
            instance = cls()
            instance_fields = [name for name in vars(instance).keys() if not name.startswith("_")]
        except Exception:
            instance_fields = []
        return {
            "status": "ok",
            "fields": sorted(set(parameters + instance_fields)),
            **{field: field in parameters or field in instance_fields for field in target_fields},
        }
    except Exception as exc:  # noqa: BLE001 - introspection must be safe when SDK is absent.
        return {
            "status": "missing_or_uninspectable",
            "error_class": type(exc).__name__,
            "fields": [],
            **{field: False for field in target_fields},
        }


def _field_supported(obj: Any, field: str) -> bool:
    if hasattr(obj, field):
        return True
    try:
        parameters = inspect.signature(type(obj).__init__).parameters
        return field in parameters
    except Exception:
        return False


def _set_supported_field(obj: Any, field: str, value: Any) -> bool:
    if _field_supported(obj, field):
        setattr(obj, field, value)
        return True
    return False


def _first_present(obj: Any, names: list[str]) -> Any:
    for name in names:
        if isinstance(obj, dict) and obj.get(name) is not None:
            return obj.get(name)
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _classify_status_code(status_code: int) -> str:
    if status_code == 401 or status_code == 403:
        return "auth_error_401"
    if status_code == 429:
        return "quota_or_rate_limit_429"
    if 500 <= status_code <= 599:
        return "server_error_5xx"
    return "unexpected_error"


def _safe_get(obj: Any, *path: str) -> Any:
    current = obj
    for part in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _normalize_retrieval_nodes(nodes: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node in nodes if isinstance(nodes, list) else []:
        payload = _to_jsonable(node)
        text = str(payload.get("text") or payload.get("content") or json.dumps(payload, ensure_ascii=False))
        paper_id = _extract_paper_id(text)
        items.append(
            {
                "paper_id": paper_id,
                "score": payload.get("score") or payload.get("similarity") or payload.get("rerank_score"),
                "text_excerpt": redact_sensitive(text)[:240],
            }
        )
    return items


def _contains_signed_url(value: Any) -> bool:
    text = json.dumps(_jsonable_recursive(value), ensure_ascii=False).lower()
    return any(marker in text for marker in ["ossaccesskeyid", "signature=", "x-oss-signature", "expires=", "signedurl"])


def _jsonable_recursive(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable_recursive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable_recursive(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable_recursive(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return _to_jsonable(value)


def _to_jsonable(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_map"):
        mapped = obj.to_map()
        return mapped if isinstance(mapped, dict) else {}
    if hasattr(obj, "__dict__"):
        return {key: value for key, value in vars(obj).items() if not key.startswith("_")}
    return {}


def _extract_paper_id(text: str) -> str | None:
    import re

    match = re.search(r"\b(?:P\d{3,}|F\d+[A-Z])\b", text)
    return match.group(0) if match else None


def _expected_ids(question: dict[str, Any]) -> set[str]:
    for key in ("expected_paper_ids", "expected_ids", "paper_ids"):
        value = question.get(key)
        if isinstance(value, list):
            return {str(item) for item in value}
        if isinstance(value, str):
            return {value}
    value = question.get("expected_paper_id") or question.get("paper_id")
    return {str(value)} if value else set()
