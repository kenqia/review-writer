from __future__ import annotations

import json
import os
import time
from typing import Any

from .base import JudgeResult, JudgeTask

REGION_HOSTS = {
    "cn-beijing": "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "ap-northeast-1": "https://{workspace_id}.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1",
    "ap-southeast-1": "https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
}


class QwenJudge:
    provider_name = "qwen_judge"

    def __init__(
        self,
        *,
        enabled: bool = False,
        allow_network: bool = False,
        timeout_seconds: float = 90.0,
        max_output_tokens: int = 128,
        compact: bool = False,
    ) -> None:
        self.enabled = enabled
        self.allow_network = allow_network
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.compact = compact

    def judge(self, task: JudgeTask) -> JudgeResult:
        started = time.monotonic()
        if not self.enabled:
            return self._disabled(task, "Qwen judge disabled by default", elapsed_seconds=_elapsed(started))
        if not self.allow_network:
            return self._disabled(task, "Qwen judge network calls require --allow-network", elapsed_seconds=_elapsed(started))

        env = read_safe_env()
        missing = [key for key in ("DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID") if env["presence"][key] == "MISSING"]
        if missing:
            return self._error(task, "missing_env", f"missing required env: {', '.join(missing)}", env, network="not_used", elapsed_seconds=_elapsed(started))
        try:
            base_url = build_base_url(env["workspace_id"], env["region"])
        except ValueError as exc:
            return self._error(task, "unexpected_error", str(exc), env, network="not_used", elapsed_seconds=_elapsed(started))
        try:
            from openai import OpenAI  # type: ignore
        except Exception:
            return self._error(
                task,
                "missing_dependency",
                "Python package 'openai' is not installed; not installing automatically",
                env,
                base_url=base_url,
                network="not_used",
                elapsed_seconds=_elapsed(started),
            )

        prompt = build_judge_prompt(task, compact=self.compact)
        try:
            client = OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=base_url, timeout=self.timeout_seconds)
            response = client.chat.completions.create(
                model=env["model"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_output_tokens,
                temperature=0,
            )
            raw = (response.choices[0].message.content or "").strip()
            payload = parse_judge_payload(raw)
            return JudgeResult(
                provider_name=self.provider_name,
                task_id=task.task_id,
                rule_id=task.rule_id,
                status="ok",
                verdict=payload.get("verdict", "unclear"),
                rationale=payload.get("rationale", "Qwen judge returned a non-JSON or partial response."),
                warnings=[] if payload.get("parsed_json") else ["judge response was summarized without printing raw response"],
                metadata=self._metadata(
                    task,
                    prompt,
                    env=env,
                    base_url=base_url,
                    network="used_once",
                    network_attempts=1,
                    elapsed_seconds=_elapsed(started),
                ),
            )
        except Exception as exc:
            return self._error(
                task,
                classify_exception(exc),
                safe_exception_summary(exc),
                env,
                base_url=base_url,
                network="attempted_once",
                network_attempts=1,
                elapsed_seconds=_elapsed(started),
            )

    def _disabled(self, task: JudgeTask, reason: str, *, elapsed_seconds: float) -> JudgeResult:
        prompt = build_judge_prompt(task, compact=self.compact)
        return JudgeResult(
            provider_name=self.provider_name,
            task_id=task.task_id,
            rule_id=task.rule_id,
            status="disabled",
            verdict="not_judged",
            rationale=reason,
            warnings=[reason],
            metadata=self._metadata(task, prompt, network="not_used", network_attempts=0, elapsed_seconds=elapsed_seconds),
        )

    def _error(
        self,
        task: JudgeTask,
        error_type: str,
        summary: str,
        env: dict[str, Any],
        *,
        base_url: str = "",
        network: str,
        network_attempts: int = 0,
        elapsed_seconds: float,
    ) -> JudgeResult:
        prompt = build_judge_prompt(task, compact=self.compact)
        return JudgeResult(
            provider_name=self.provider_name,
            task_id=task.task_id,
            rule_id=task.rule_id,
            status="error",
            verdict="not_judged",
            rationale=summary,
            warnings=["API key value was not printed"],
            error_type=error_type,
            metadata=self._metadata(
                task,
                prompt,
                env=env,
                base_url=base_url,
                network=network,
                network_attempts=network_attempts,
                elapsed_seconds=elapsed_seconds,
                error_category=error_type,
            ),
        )

    def _metadata(
        self,
        task: JudgeTask,
        prompt: str,
        *,
        env: dict[str, Any] | None = None,
        base_url: str = "",
        network: str,
        network_attempts: int,
        elapsed_seconds: float,
        error_category: str | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "task_type": task.task_type,
            "task_metadata": task.metadata,
            "prompt_chars": len(prompt),
            "input_excerpt_chars": len(task.input_text),
            "rubric_chars": len(task.rubric),
            "timeout_seconds": self.timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
            "compact_mode": self.compact,
            "elapsed_seconds": elapsed_seconds,
            "error_category": error_category,
            "network": network,
            "network_attempts": network_attempts,
            "paper_body_read": "not_read",
            "uploads": "not_used",
            "knowledge_base_created": "not_used",
            "image_api": "not_used",
        }
        if env:
            metadata.update(
                {
                    "model": env["model"],
                    "region": env["region"],
                    "base_url": base_url,
                    "env": env["presence"],
                }
            )
        return metadata


def build_base_url(workspace_id: str, region: str) -> str:
    template = REGION_HOSTS.get(region)
    if not template:
        supported = ", ".join(sorted(REGION_HOSTS))
        raise ValueError(f"unsupported region {region!r}; supported regions: {supported}")
    return template.format(workspace_id=workspace_id)


def read_safe_env() -> dict[str, Any]:
    region = os.environ.get("BAILIAN_REGION") or "cn-beijing"
    model = os.environ.get("BAILIAN_MODEL") or "qwen-plus"
    workspace_id = os.environ.get("BAILIAN_WORKSPACE_ID") or ""
    return {
        "region": region,
        "model": model,
        "workspace_id": workspace_id,
        "presence": {
            "DASHSCOPE_API_KEY": "SET" if os.environ.get("DASHSCOPE_API_KEY") else "MISSING",
            "BAILIAN_WORKSPACE_ID": "SET" if workspace_id else "MISSING",
            "BAILIAN_REGION": "SET" if os.environ.get("BAILIAN_REGION") else "MISSING_DEFAULT_CN_BEIJING",
            "BAILIAN_MODEL": "SET" if os.environ.get("BAILIAN_MODEL") else "MISSING_DEFAULT_QWEN_PLUS",
        },
    }


def build_judge_prompt(task: JudgeTask, *, compact: bool = False) -> str:
    if compact:
        return "\n".join(
            [
                "Judge chemistry review quality. Return only JSON:",
                '{"verdict":"pass|fail|uncertain","reason":"one short sentence"}',
                f"type={task.task_type}; rule={task.rule_id}",
                f"rubric={task.rubric[:500]}",
                f"excerpt={task.input_text[:1200]}",
            ]
        )
    return "\n".join(
        [
            "You are a chemistry review quality judge. Do not generate manuscript prose.",
            "Return compact JSON with keys: verdict, rationale.",
            "verdict must be one of: pass, warn, fail, unclear.",
            f"Task type: {task.task_type}",
            f"Rule id: {task.rule_id}",
            "Rubric:",
            task.rubric,
            "Input excerpt:",
            task.input_text[:3000],
        ]
    )


def parse_judge_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            verdict = str(payload.get("verdict", "unclear")).lower()
            if verdict == "uncertain":
                verdict = "uncertain"
            elif verdict not in {"pass", "warn", "fail", "unclear"}:
                verdict = "unclear"
            return {
                "verdict": verdict,
                "rationale": str(payload.get("rationale") or payload.get("reason") or "")[:500],
                "parsed_json": True,
            }
    except Exception:
        pass
    return {"verdict": "unclear", "rationale": "The judge response was not valid compact JSON.", "parsed_json": False}


def classify_exception(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code == 401:
        return "auth_error_401"
    if status_code == 429:
        return "rate_limit_or_quota_429"
    if status_code == 503:
        return "server_overloaded_503"
    if isinstance(status_code, int) and 500 <= status_code <= 599:
        return "server_error_5xx"
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return "client_timeout"
    if any(token in name or token in text for token in ("connection", "network", "dns", "ssl")):
        return "network_error"
    return "unexpected_error"


def safe_exception_summary(exc: Exception) -> str:
    error_type = classify_exception(exc)
    if error_type == "auth_error_401":
        return "authentication failed with HTTP 401"
    if error_type == "rate_limit_or_quota_429":
        return "rate limit or quota error with HTTP 429"
    if error_type == "server_overloaded_503":
        return "server overloaded with HTTP 503"
    if error_type == "server_error_5xx":
        return "server returned a 5xx error"
    if error_type == "client_timeout":
        return "client request timed out"
    if error_type == "network_error":
        return "network error during the single judge request"
    return f"unexpected error: {exc.__class__.__name__}"


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 3)
