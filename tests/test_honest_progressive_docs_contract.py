from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = (
    ROOT / "docs/superpowers/specs/2026-07-30-dual-parse-evidence-to-release-design.md",
    ROOT / "docs/superpowers/plans/2026-07-30-dual-parse-evidence-to-release-complete-loop.md",
    ROOT / "docs/qa/three-paper-dual-parse-evidence-to-release-playwright.md",
    ROOT / "docs/superpowers/specs/2026-07-31-honest-progressive-route.md",
)
CONTRACT_RE = re.compile(
    r"(?ms)^## Fresh v3 Honest Progressive Contract\n\n"
    r"<!-- FRESH_V3_CONTRACT_START -->\n\n"
    r"(.*?)\n"
    r"<!-- FRESH_V3_CONTRACT_END -->"
)


def test_fresh_v3_honest_progressive_contract_is_identical_and_complete() -> None:
    contracts: list[str] = []
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        match = CONTRACT_RE.search(text)
        assert match is not None, path
        contracts.append(match.group(1).strip())

    assert len(set(contracts)) == 1
    contract = contracts[0]
    for required in (
        "CONFIRMED",
        "AI_PROVISIONAL",
        "BLOCKED",
        "value=null",
        "gap_reason",
        "PDF locator and researcher confirmation",
        "PDF locator, confidence, and provenance",
        "availability/status` is `unknown/unavailable",
        "confirmed_count",
        "ai_provisional_count",
        "blocked_count",
        "coverage_ratio",
        "coverage_sufficient",
        "gap_registry",
        "待 Chemical Paper 导入",
        "确认第一份 Chemical Paper 导入",
        "NOT_APPLICABLE_BY_CURRENT_SCOPE",
        "6/11/11",
        "125/109/75",
        "309",
        "unavailable_not_provided",
        "server_calculated",
        "client-supplied counts are untrusted",
        "formal preflight → confirm → importer",
        "v2 Generic ZIP",
        "old Generic",
        "Coordinator-only",
        "needs_more_traceable_candidates",
        "Task 10",
        "Task 11",
    ):
        assert required in contract, required
