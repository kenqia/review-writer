from __future__ import annotations

import hashlib

from .base import JudgeResult, JudgeTask


class OfflineJudge:
    provider_name = "offline_judge"

    def judge(self, task: JudgeTask) -> JudgeResult:
        digest = hashlib.sha256((task.task_id + "\n" + task.input_text + "\n" + task.rubric).encode("utf-8")).hexdigest()[:12]
        prompt_chars = len(task.task_id) + len(task.input_text) + len(task.rubric)
        return JudgeResult(
            provider_name=self.provider_name,
            task_id=task.task_id,
            rule_id=task.rule_id,
            status="ok",
            verdict="placeholder",
            rationale="Deterministic offline placeholder; no semantic LLM judgment was performed.",
            warnings=["offline judge used; no network call was made"],
            metadata={
                "task_type": task.task_type,
                "task_metadata": task.metadata,
                "deterministic_digest": digest,
                "prompt_chars": prompt_chars,
                "input_excerpt_chars": len(task.input_text),
                "rubric_chars": len(task.rubric),
                "timeout_seconds": 0,
                "max_output_tokens": 0,
                "compact_mode": False,
                "elapsed_seconds": 0.0,
                "error_category": None,
                "network": "not_used",
                "network_attempts": 0,
                "paper_body_read": "not_read",
                "uploads": "not_used",
                "knowledge_base_created": "not_used",
                "image_api": "not_used",
            },
        )
