from __future__ import annotations

import json
import os
from typing import Any

from .base import JudgeResult, JudgeTask

REGION_HOSTS = {
    "cn-beijing": "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "ap-northeast-1": "https://{workspace_id}.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1",
    "ap-southeast-1": "https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
}


class QwenJudge:
    provider_name = "qwen_judge"

    def __init__(self, *, enabled: bool = False, allow_network: bool = False) -> None:
        self.enabled = enabled
        self.allow_network = allow_network

    def judge(self, task: JudgeTask) -> JudgeResult:
        if not self.enabled:
            return self._disabled(task, "Qwen judge disabled by default")
        if not self.allow_network:
            return self._disabled(task, "Qwen judge network calls require --allow-network")

        env = read_safe_env()
        missing = [key for key in ("DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID") if env["presence"][key] == "MISSING"]
        if missing:
            return self._error(task, "missing_env", f"missing required env: {', '.join(missing)}", env, network="not_used")
        try:
            base_url = build_base_url(env["workspace_id"], env["region"])
        except ValueError as exc:
            return self._error(task, "unexpected_error", str(exc), env, network="not_used")
        try:
            from openai import OpenAI  # type: ignore
        except Exception:
            return self._error(task, "missing_dependency", "Python package 'openai' is not installed; not installing automatically", env, base_url=base_url, network="not_used")

        prompt = build_judge_prompt(task)
        try:
            client = OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=base_url, timeout=30.0)
            response = client.chat.completions.create(
                model=env["model"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=220,
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
                metadata={
                    "task_type": task.task_type,
                    "task_metadata": task.metadata,
                    "model": env["model"],
                    "region": env["region"],
                    "base_url": base_url,
                    "network": "used_once",
                    "paper_body_read": "not_read",
                    "uploads": "not_used",
                    "knowledge_base_created": "not_used",
                    "image_api": "not_used",
                },
            )
        except Exception as exc:
            return self._error(task, classify_exception(exc), safe_exception_summary(exc), env, base_url=base_url, network="attempted_once")

    def _disabled(self, task: JudgeTask, reason: str) -> JudgeResult:
        return JudgeResult(
            provider_name=self.provider_name,
            task_id=task.task_id,
            rule_id=task.rule_id,
            status="disabled",
            verdict="not_judged",
            rationale=reason,
            warnings=[reason],
            metadata={
                "task_type": task.task_type,
                "task_metadata": task.metadata,
                "network": "not_used",
                "paper_body_read": "not_read",
                "uploads": "not_used",
                "knowledge_base_created": "not_used",
                "image_api": "not_used",
            },
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
    ) -> JudgeResult:
        return JudgeResult(
            provider_name=self.provider_name,
            task_id=task.task_id,
            rule_id=task.rule_id,
            status="error",
            verdict="not_judged",
            rationale=summary,
            warnings=["API key value was not printed"],
            error_type=error_type,
            metadata={
                "task_type": task.task_type,
                "task_metadata": task.metadata,
                "model": env["model"],
                "region": env["region"],
                "base_url": base_url,
                "env": env["presence"],
                "network": network,
                "paper_body_read": "not_read",
                "uploads": "not_used",
                "knowledge_base_created": "not_used",
                "image_api": "not_used",
            },
        )


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


def build_judge_prompt(task: JudgeTask) -> str:
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
            if verdict not in {"pass", "warn", "fail", "unclear"}:
                verdict = "unclear"
            return {
                "verdict": verdict,
                "rationale": str(payload.get("rationale", ""))[:500],
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
    if isinstance(status_code, int) and 500 <= status_code <= 599:
        return "server_error_5xx"
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return "timeout"
    if any(token in name or token in text for token in ("connection", "network", "dns", "ssl")):
        return "network_error"
    return "unexpected_error"


def safe_exception_summary(exc: Exception) -> str:
    error_type = classify_exception(exc)
    if error_type == "auth_error_401":
        return "authentication failed with HTTP 401"
    if error_type == "rate_limit_or_quota_429":
        return "rate limit or quota error with HTTP 429"
    if error_type == "server_error_5xx":
        return "server returned a 5xx error"
    if error_type == "timeout":
        return "request timed out"
    if error_type == "network_error":
        return "network error during the single judge request"
    return f"unexpected error: {exc.__class__.__name__}"
