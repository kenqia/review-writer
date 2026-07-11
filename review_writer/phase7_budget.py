from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_BUDGET_PATH = Path("/tmp/review_writer_phase7_budget.json")

DEFAULT_STATE = {
    "qwen_only_attempts": 0,
    "full_e2e_attempts": 0,
    "qwen_total_requests": 0,
    "bailian_lifecycles": 0,
    "uploads": 0,
    "last_operation": None,
    "last_result": None,
}

LIMITS = {
    "qwen_only_attempts": 2,
    "full_e2e_attempts": 2,
    "qwen_total_requests": 4,
    "bailian_lifecycles": 2,
    "uploads": 2,
}


class BudgetExceeded(RuntimeError):
    def __init__(self, operation: str) -> None:
        super().__init__(f"phase7 real-call budget exhausted: {operation}")
        self.operation = operation


class Phase7BudgetLedger:
    def __init__(self, path: Path = DEFAULT_BUDGET_PATH) -> None:
        self.path = path

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULT_STATE)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return {**DEFAULT_STATE, **{key: payload.get(key) for key in DEFAULT_STATE}}

    def reserve(
        self,
        operation: str,
        *,
        qwen_requests: int = 0,
        lifecycles: int = 0,
        uploads: int = 0,
        last_operation: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        before = self.read()
        after = dict(before)
        if operation == "qwen_only":
            after["qwen_only_attempts"] += 1
        elif operation == "full_e2e":
            after["full_e2e_attempts"] += 1
        elif operation == "qwen_generation":
            pass
        after["qwen_total_requests"] += qwen_requests
        after["bailian_lifecycles"] += lifecycles
        after["uploads"] += uploads
        after["last_operation"] = last_operation
        after["last_result"] = "reserved"
        self._check_limits(operation, after)
        self._atomic_write(after)
        return before, after

    def record_result(self, result: str) -> dict[str, Any]:
        state = self.read()
        state["last_result"] = result
        self._atomic_write(state)
        return state

    def _check_limits(self, operation: str, state: dict[str, Any]) -> None:
        for key, limit in LIMITS.items():
            if int(state[key]) > limit:
                raise BudgetExceeded(operation)

    def _atomic_write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
