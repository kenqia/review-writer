from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .base import ProviderResult, TextGenerationRequest

REGION_HOSTS = {
    "cn-beijing": "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "ap-northeast-1": "https://{workspace_id}.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1",
    "ap-southeast-1": "https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
}
DEFAULT_QWEN_MODEL = "qwen3.7-plus"


class OpenAICompatibleProvider:
    provider_name = "alibaba_openai_compatible"

    def __init__(
        self,
        *,
        base_url: str = "",
        model: str = DEFAULT_QWEN_MODEL,
        region: str = "cn-beijing",
        workspace_id: str = "",
        api_key: str = "",
        api_key_env: str = "DASHSCOPE_API_KEY",
        workspace_id_env: str = "BAILIAN_WORKSPACE_ID",
        base_url_env: str = "BAILIAN_OPENAI_BASE_URL",
        allow_network: bool = False,
        enabled: bool = False,
        connect_timeout_seconds: float = 10.0,
        first_byte_timeout_seconds: float = 45.0,
        total_timeout_seconds: float = 120.0,
        client_factory: Callable[..., Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.region = region
        self.workspace_id = workspace_id
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.workspace_id_env = workspace_id_env
        self.base_url_env = base_url_env
        self.allow_network = allow_network
        self.enabled = enabled
        self.connect_timeout_seconds = connect_timeout_seconds
        self.first_byte_timeout_seconds = first_byte_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.client_factory = client_factory
        self.monotonic = monotonic

    @classmethod
    def from_env(
        cls,
        *,
        allow_network: bool,
        enabled: bool = True,
        model: str | None = None,
        connect_timeout_seconds: float = 10.0,
        first_byte_timeout_seconds: float = 45.0,
        total_timeout_seconds: float = 120.0,
    ) -> "OpenAICompatibleProvider":
        return cls(
            enabled=enabled,
            allow_network=allow_network,
            model=model or os.environ.get("BAILIAN_MODEL") or os.environ.get("ALIBABA_MODEL") or DEFAULT_QWEN_MODEL,
            region=os.environ.get("BAILIAN_REGION") or os.environ.get("ALIBABA_REGION") or "cn-beijing",
            connect_timeout_seconds=connect_timeout_seconds,
            first_byte_timeout_seconds=first_byte_timeout_seconds,
            total_timeout_seconds=total_timeout_seconds,
        )

    def generate_text(self, request: TextGenerationRequest) -> ProviderResult:
        started = self.monotonic()
        if not self.enabled:
            return self._disabled("provider disabled by config", started)
        if not self.allow_network:
            return self._disabled("network calls disabled; pass allow_network=True only after explicit user approval", started)

        env = self._safe_env()
        api_key = self.api_key or os.environ.get(self.api_key_env) or ""
        if not api_key:
            return self._error("missing_env", "missing provider API key", started, env=env, network="not_used")
        try:
            endpoint = self._resolve_endpoint(env)
            client_factory = self.client_factory or _default_client_factory
            client = client_factory(api_key=api_key, base_url=endpoint["base_url"], timeout=self.connect_timeout_seconds)
            stream = client.chat.completions.create(
                model=request.model if request.model != "offline" else self.model,
                messages=request.messages,
                temperature=request.temperature,
                max_completion_tokens=request.max_output_tokens,
                stream=True,
                stream_options={"include_usage": True},
                extra_body={"enable_thinking": False, "enable_search": False},
            )
            parsed = parse_openai_stream_result(
                stream,
                first_server_timeout_seconds=self.first_byte_timeout_seconds,
                first_content_timeout_seconds=self.first_byte_timeout_seconds,
                idle_timeout_seconds=self.first_byte_timeout_seconds,
                total_timeout_seconds=self.total_timeout_seconds,
                monotonic=self.monotonic,
                started_at=started,
            )
            metadata = self._metadata(
                started,
                env=env,
                endpoint=endpoint,
                network="used_once",
                stream_started=True,
                chunks_received=parsed.telemetry["content_chunks_received"],
                error_type=None,
            )
            metadata["stream_telemetry"] = parsed.telemetry
            return ProviderResult(
                provider_name=self.provider_name,
                status="ok",
                content=parsed.content.strip(),
                metadata=metadata,
            )
        except FirstByteTimeout:
            return self._error(
                "first_byte_timeout",
                "stream did not produce a first content chunk within the configured timeout",
                started,
                env=env,
                network="attempted_once",
                stream_started=False,
                chunks_received=0,
            )
        except TotalStreamTimeout:
            return self._error(
                "total_timeout",
                "stream exceeded the configured total timeout",
                started,
                env=env,
                network="attempted_once",
                stream_started=True,
            )
        except IncompleteGeneration:
            return self._error(
                "incomplete_generation",
                "stream stopped because the provider hit the output length limit",
                started,
                env=env,
                network="attempted_once",
                stream_started=True,
                chunks_received=0,
            )
        except Exception as exc:  # noqa: BLE001 - provider must return safe reports for every failure.
            error_type = classify_exception(exc)
            return self._error(
                error_type,
                safe_exception_summary(exc, error_type),
                started,
                env=env,
                network="attempted_once" if error_type != "missing_dependency" else "not_used",
                stream_started=getattr(exc, "stream_started", False),
                chunks_received=getattr(exc, "chunks_received", 0),
            )

    def _disabled(self, reason: str, started: float) -> ProviderResult:
        return ProviderResult(
            provider_name=self.provider_name,
            status="disabled",
            warnings=[reason],
            metadata=self._metadata(started, env=self._safe_env(), endpoint=self._safe_endpoint_stub(), network="not_used"),
        )

    def _error(
        self,
        error_type: str,
        summary: str,
        started: float,
        *,
        env: dict[str, Any],
        network: str,
        stream_started: bool = False,
        chunks_received: int = 0,
    ) -> ProviderResult:
        return ProviderResult(
            provider_name=self.provider_name,
            status="error",
            warnings=[summary, "Credentials, prompt, and EvidencePack were not printed"],
            metadata=self._metadata(
                started,
                env=env,
                endpoint=self._safe_endpoint_stub(env),
                network=network,
                stream_started=stream_started,
                chunks_received=chunks_received,
                error_type=error_type,
            ),
        )

    def _metadata(
        self,
        started: float,
        *,
        env: dict[str, Any],
        endpoint: dict[str, Any],
        network: str,
        stream_started: bool = False,
        chunks_received: int = 0,
        error_type: str | None = None,
    ) -> dict[str, Any]:
        return {
            "network": network,
            "error_type": error_type,
            "model": self.model,
            "region": endpoint.get("region") or env.get("region"),
            "dedicated_endpoint_used": bool(endpoint.get("dedicated_endpoint_used")),
            "base_url_redacted": endpoint.get("base_url_redacted", "redacted"),
            "env": env["presence"],
            "streaming": True,
            "stream_started": stream_started,
            "chunks_received": chunks_received,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "first_byte_timeout_seconds": self.first_byte_timeout_seconds,
            "total_timeout_seconds": self.total_timeout_seconds,
            "elapsed_ms": int(max(0.0, self.monotonic() - started) * 1000),
            "request_id_present": False,
            "retry_count": 0,
            "cleanup_status": "not_needed",
        }

    def _safe_env(self) -> dict[str, Any]:
        workspace_id = self.workspace_id or os.environ.get(self.workspace_id_env) or os.environ.get("ALIBABA_WORKSPACE_ID") or ""
        base_url = self.base_url or os.environ.get(self.base_url_env) or os.environ.get("ALIBABA_OPENAI_BASE_URL") or ""
        region = self.region or os.environ.get("BAILIAN_REGION") or os.environ.get("ALIBABA_REGION") or "cn-beijing"
        model = self.model or os.environ.get("BAILIAN_MODEL") or DEFAULT_QWEN_MODEL
        return {
            "region": region,
            "model": model,
            "workspace_id_present": bool(workspace_id),
            "base_url_present": bool(base_url),
            "presence": {
                self.api_key_env: "SET" if (self.api_key or os.environ.get(self.api_key_env)) else "MISSING",
                self.workspace_id_env: "SET" if os.environ.get(self.workspace_id_env) else "MISSING",
                "ALIBABA_WORKSPACE_ID": "SET" if os.environ.get("ALIBABA_WORKSPACE_ID") else "MISSING",
                self.base_url_env: "SET" if os.environ.get(self.base_url_env) else "MISSING",
                "BAILIAN_REGION": "SET" if os.environ.get("BAILIAN_REGION") else "MISSING_DEFAULT_CN_BEIJING",
                "BAILIAN_MODEL": "SET" if os.environ.get("BAILIAN_MODEL") else "MISSING_DEFAULT_QWEN37_PLUS",
            },
        }

    def _resolve_endpoint(self, env: dict[str, Any]) -> dict[str, Any]:
        base_url = self.base_url or os.environ.get(self.base_url_env) or os.environ.get("ALIBABA_OPENAI_BASE_URL") or ""
        region = self.region or os.environ.get("BAILIAN_REGION") or os.environ.get("ALIBABA_REGION") or "cn-beijing"
        if base_url:
            return {
                "base_url": base_url,
                "region": region,
                "dedicated_endpoint_used": ".maas.aliyuncs.com/" in base_url,
                "base_url_redacted": "redacted",
            }
        workspace_id = self.workspace_id or os.environ.get(self.workspace_id_env) or os.environ.get("ALIBABA_WORKSPACE_ID") or ""
        if not workspace_id:
            raise MissingEndpoint("missing workspace id or OpenAI-compatible base URL")
        template = REGION_HOSTS.get(region)
        if not template:
            supported = ", ".join(sorted(REGION_HOSTS))
            raise ValueError(f"unsupported region {region!r}; supported regions: {supported}")
        return {
            "base_url": template.format(workspace_id=workspace_id),
            "region": region,
            "dedicated_endpoint_used": True,
            "base_url_redacted": "redacted",
        }

    def _safe_endpoint_stub(self, env: dict[str, Any] | None = None) -> dict[str, Any]:
        env = env or self._safe_env()
        return {
            "region": env.get("region", self.region),
            "dedicated_endpoint_used": bool(self.base_url or self.workspace_id or env.get("workspace_id_present") or env.get("base_url_present")),
            "base_url_redacted": "redacted",
        }


class MissingEndpoint(RuntimeError):
    pass


class FirstByteTimeout(TimeoutError):
    pass


class TotalStreamTimeout(TimeoutError):
    pass


class StreamFailed(RuntimeError):
    def __init__(self, message: str, *, stream_started: bool, chunks_received: int) -> None:
        super().__init__(message)
        self.stream_started = stream_started
        self.chunks_received = chunks_received


class IncompleteGeneration(RuntimeError):
    def __init__(self, finish_reason: str) -> None:
        super().__init__("stream ended before a complete generation was available")
        self.finish_reason = finish_reason


@dataclass(frozen=True)
class StreamParseResult:
    content: str
    telemetry: dict[str, Any]


def parse_openai_stream_content(
    chunks: Iterable[Any],
    *,
    first_byte_timeout_seconds: float,
    total_timeout_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    started_at: float | None = None,
) -> str:
    result = parse_openai_stream_result(
        chunks,
        first_server_timeout_seconds=first_byte_timeout_seconds,
        first_content_timeout_seconds=first_byte_timeout_seconds,
        idle_timeout_seconds=total_timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        monotonic=monotonic,
        started_at=started_at,
    )
    return result.content


def parse_openai_stream_result(
    chunks: Iterable[Any],
    *,
    first_server_timeout_seconds: float | None = None,
    first_content_timeout_seconds: float | None = None,
    idle_timeout_seconds: float | None = None,
    total_timeout_seconds: float,
    first_byte_timeout_seconds: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    started_at: float | None = None,
) -> StreamParseResult:
    started = monotonic() if started_at is None else started_at
    first_server_timeout_seconds = (
        first_server_timeout_seconds
        if first_server_timeout_seconds is not None
        else first_byte_timeout_seconds
        if first_byte_timeout_seconds is not None
        else total_timeout_seconds
    )
    first_content_timeout_seconds = (
        first_content_timeout_seconds
        if first_content_timeout_seconds is not None
        else first_byte_timeout_seconds
        if first_byte_timeout_seconds is not None
        else first_server_timeout_seconds
    )
    idle_timeout_seconds = idle_timeout_seconds if idle_timeout_seconds is not None else total_timeout_seconds
    first_server_seen = False
    first_content_seen = False
    parts: list[str] = []
    server_chunks_received = 0
    content_chunks_received = 0
    reasoning_chunks_received = 0
    usage_chunk_received = False
    finish_reason = None
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None
    first_server_chunk_ms = None
    first_content_chunk_ms = None
    last_chunk_at = started
    iterator = iter(chunks)
    while True:
        try:
            chunk = next(iterator)
        except StopIteration:
            break
        except Exception as exc:  # noqa: BLE001
            raise StreamFailed("stream failed while reading chunks", stream_started=first_content_seen, chunks_received=content_chunks_received) from exc
        now = monotonic()
        if not first_server_seen and now - started > first_server_timeout_seconds:
            raise FirstByteTimeout()
        if not first_content_seen and now - started > first_content_timeout_seconds:
            raise FirstByteTimeout()
        if first_server_seen and now - last_chunk_at > idle_timeout_seconds:
            raise TotalStreamTimeout()
        if now - started > total_timeout_seconds:
            raise TotalStreamTimeout()
        first_server_seen = True
        if first_server_chunk_ms is None:
            first_server_chunk_ms = int(max(0.0, now - started) * 1000)
        server_chunks_received += 1
        last_chunk_at = now
        if extract_reasoning_content(chunk):
            reasoning_chunks_received += 1
        usage = extract_usage(chunk)
        if usage:
            usage_chunk_received = True
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
        chunk_finish_reason = extract_finish_reason(chunk)
        if chunk_finish_reason:
            finish_reason = chunk_finish_reason
        content = extract_stream_content(chunk)
        if content:
            first_content_seen = True
            if first_content_chunk_ms is None:
                first_content_chunk_ms = int(max(0.0, now - started) * 1000)
            content_chunks_received += 1
            parts.append(content)
    if finish_reason == "length":
        raise IncompleteGeneration(finish_reason)
    return StreamParseResult(
        content="".join(parts),
        telemetry={
            "server_chunks_received": server_chunks_received,
            "content_chunks_received": content_chunks_received,
            "reasoning_chunks_received": reasoning_chunks_received,
            "usage_chunk_received": usage_chunk_received,
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "first_server_chunk_ms": first_server_chunk_ms,
            "first_content_chunk_ms": first_content_chunk_ms,
            "elapsed_ms": int(max(0.0, last_chunk_at - started) * 1000),
        },
    )


def extract_stream_content(chunk: Any) -> str:
    if isinstance(chunk, dict):
        choices = chunk.get("choices") or []
        delta = (choices[0].get("delta") or {}) if choices else {}
        return str(delta.get("content") or "")
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    return str(getattr(delta, "content", "") or "")


def extract_reasoning_content(chunk: Any) -> str:
    if isinstance(chunk, dict):
        choices = chunk.get("choices") or []
        delta = (choices[0].get("delta") or {}) if choices else {}
        return str(delta.get("reasoning_content") or "")
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    return str(getattr(delta, "reasoning_content", "") or "")


def extract_finish_reason(chunk: Any) -> str | None:
    if isinstance(chunk, dict):
        choices = chunk.get("choices") or []
        return choices[0].get("finish_reason") if choices else None
    choices = getattr(chunk, "choices", None) or []
    return getattr(choices[0], "finish_reason", None) if choices else None


def extract_usage(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        return chunk.get("usage") or {}
    usage = getattr(chunk, "usage", None)
    if not usage:
        return {}
    if isinstance(usage, dict):
        return usage
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _default_client_factory(*, api_key: str, base_url: str, timeout: float) -> Any:
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise MissingDependency("Python package 'openai' is not installed; not installing automatically") from exc
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)


class MissingDependency(RuntimeError):
    pass


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, MissingDependency):
        return "missing_dependency"
    if isinstance(exc, MissingEndpoint):
        return "missing_env"
    if isinstance(exc, StreamFailed):
        return "stream_failed"
    if isinstance(exc, IncompleteGeneration):
        return "incomplete_generation"
    status_code = getattr(exc, "status_code", None)
    if status_code == 401:
        return "auth_error_401"
    if status_code == 429:
        return "rate_limit_or_quota_429"
    if isinstance(status_code, int) and 500 <= status_code <= 599:
        return "server_error_5xx"
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return "client_timeout"
    if any(token in name or token in text for token in ("connection", "network", "dns", "ssl")):
        return "network_error"
    return "unexpected_error"


def safe_exception_summary(exc: Exception, error_type: str) -> str:
    summaries = {
        "missing_dependency": "Python package 'openai' is not installed; not installing automatically",
        "missing_env": "missing workspace id or OpenAI-compatible base URL",
        "stream_failed": "stream failed after partial or empty chunks",
        "incomplete_generation": "stream stopped because the provider hit the output length limit",
        "auth_error_401": "authentication failed with HTTP 401",
        "rate_limit_or_quota_429": "rate limit or quota error with HTTP 429",
        "server_error_5xx": "server returned a 5xx error",
        "client_timeout": "client request timed out",
        "network_error": "network error during provider request",
    }
    return summaries.get(error_type, f"unexpected error: {exc.__class__.__name__}")
