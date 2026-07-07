from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class JudgeTask:
    task_id: str
    rule_id: str
    task_type: str
    input_text: str
    rubric: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgeResult:
    provider_name: str
    task_id: str
    rule_id: str
    status: str
    verdict: str
    rationale: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "task_id": self.task_id,
            "rule_id": self.rule_id,
            "status": self.status,
            "verdict": self.verdict,
            "rationale": self.rationale,
            "warnings": self.warnings,
            "metadata": self.metadata,
            "error_type": self.error_type,
        }


class ReviewQualityJudge(Protocol):
    provider_name: str

    def judge(self, task: JudgeTask) -> JudgeResult:
        ...
