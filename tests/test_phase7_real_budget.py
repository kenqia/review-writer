#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.phase7_budget import BudgetExceeded, Phase7BudgetLedger


def main() -> int:
    test_budget_ledger_initializes_without_secrets()
    test_budget_ledger_reserves_before_real_requests()
    test_full_e2e_can_reserve_qwen_generation_separately()
    test_budget_ledger_blocks_exhausted_budget()
    print("phase7_real_budget_tests: ok")
    return 0


def test_budget_ledger_initializes_without_secrets() -> None:
    path = Path("/tmp/review_writer_phase7_budget_test_init.json")
    path.unlink(missing_ok=True)
    ledger = Phase7BudgetLedger(path)
    state = ledger.read()
    assert state["qwen_only_attempts"] == 0
    assert state["full_e2e_attempts"] == 0
    rendered = json.dumps(state, ensure_ascii=False)
    forbidden = ["DASHSCOPE", "WORKSPACE", "endpoint", "Authorization", "file_id", "index_id", "job_id"]
    assert not any(token in rendered for token in forbidden)


def test_budget_ledger_reserves_before_real_requests() -> None:
    path = Path("/tmp/review_writer_phase7_budget_test_reserve.json")
    path.unlink(missing_ok=True)
    ledger = Phase7BudgetLedger(path)
    before, after = ledger.reserve("qwen_only", qwen_requests=1, last_operation="qwen-only smoke")
    assert before["qwen_only_attempts"] == 0
    assert after["qwen_only_attempts"] == 1
    assert after["qwen_total_requests"] == 1
    assert after["last_operation"] == "qwen-only smoke"
    ledger.record_result("pass")
    assert ledger.read()["last_result"] == "pass"


def test_budget_ledger_blocks_exhausted_budget() -> None:
    path = Path("/tmp/review_writer_phase7_budget_test_exhausted.json")
    path.unlink(missing_ok=True)
    ledger = Phase7BudgetLedger(path)
    ledger.reserve("qwen_only", qwen_requests=1, last_operation="qwen-only 1")
    ledger.reserve("qwen_only", qwen_requests=1, last_operation="qwen-only 2")
    try:
        ledger.reserve("qwen_only", qwen_requests=1, last_operation="qwen-only 3")
    except BudgetExceeded as exc:
        assert exc.operation == "qwen_only"
    else:
        raise AssertionError("expected qwen_only budget exhaustion")


def test_full_e2e_can_reserve_qwen_generation_separately() -> None:
    path = Path("/tmp/review_writer_phase7_budget_test_full_qwen.json")
    path.unlink(missing_ok=True)
    ledger = Phase7BudgetLedger(path)
    _before, after_full = ledger.reserve("full_e2e", lifecycles=1, uploads=1, last_operation="full e2e retrieval")
    assert after_full["full_e2e_attempts"] == 1
    assert after_full["qwen_total_requests"] == 0
    _before, after_qwen = ledger.reserve("qwen_generation", qwen_requests=1, last_operation="full e2e qwen")
    assert after_qwen["full_e2e_attempts"] == 1
    assert after_qwen["qwen_total_requests"] == 1


if __name__ == "__main__":
    raise SystemExit(main())
