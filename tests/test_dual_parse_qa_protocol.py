from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/qa/three-paper-dual-parse-evidence-to-release-playwright.md"


def protocol_text() -> str:
    assert PROTOCOL.is_file(), f"missing QA protocol: {PROTOCOL}"
    return PROTOCOL.read_text(encoding="utf-8")


def checkpoint_blocks() -> dict[int, str]:
    text = protocol_text()
    matches = list(re.finditer(r"(?m)^(\d+)\.\s", text))
    numbers = [int(match.group(1)) for match in matches]
    assert numbers == list(range(1, 20))
    return {
        number: text[match.start() : matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        for index, (number, match) in enumerate(zip(numbers, matches, strict=True))
    }


def assert_contains(text: str, *required: str) -> None:
    for phrase in required:
        assert phrase in text


def test_protocol_requires_fresh_simulated_researcher_and_black_box_boundary() -> None:
    text = protocol_text()
    assert_contains(
        text,
        "simulated_researcher_agent",
        "simulated_researcher",
        "brand-new browser context",
        "must not read repository",
        "must not inspect request or response bodies",
        "must not implement or repair product code",
        "must not generate candidate scientific content",
        "must not use page evaluation",
    )


def test_protocol_has_exactly_nineteen_ordered_checkpoints() -> None:
    blocks = checkpoint_blocks()
    assert list(blocks) == list(range(1, 20))


def test_checkpoints_cover_fresh_project_and_three_by_three_dual_parse() -> None:
    blocks = checkpoint_blocks()
    assert_contains(blocks[1], "brand-new browser context", "1440x1000", "before first navigation")
    assert_contains(blocks[2], "fresh bootstrap", "project", "stage", "blocker", "unique next action")
    assert_contains(
        blocks[3],
        "3/3 verified PDFs",
        "3/3 current Generic MinerU",
        "3/3 Chemical Paper",
        "preflight",
        "confirm",
        "6/11/11",
        "125/109/75",
        "309",
        "unavailable_not_provided",
    )


def test_checkpoints_cover_completion_reconciliation_and_scientific_decisions() -> None:
    blocks = checkpoint_blocks()
    assert_contains(
        blocks[4],
        "Chemical Completion",
        "name or paper-local label",
        "one authoritative `resolved_smiles`",
        "must not become two separate Completion inputs",
        "PDF locator",
        "must not guess",
    )
    assert "both expanded and unexpanded SMILES" not in blocks[4]
    assert_contains(
        blocks[5],
        "Reconciliation",
        "Generic MinerU",
        "Chemical Paper",
        "original PDF",
        "pdf_resolved",
        "object-level",
    )
    assert_contains(
        blocks[6],
        "three study-local Paper Evidence",
        "epistemic type",
        "conditions",
        "risk",
        "limitations",
        "scientific decision",
    )
    assert_contains(blocks[7], "refresh", "actor", "simulated_researcher_agent", "unique next action")
    assert_contains(
        blocks[8],
        "Comparison Protocol",
        "Coverage",
        "Synthesis",
        "counter-evidence",
        "uncertainty",
    )
    assert_contains(
        blocks[9],
        "Section Contracts",
        "5-8 figure slots",
        "Source Figure",
        "real gap",
        "Synthesis Figure Placeholder",
    )


def test_protocol_requires_content_agent_request_pause_and_resume() -> None:
    text = protocol_text()
    assert_contains(
        text,
        "CONTENT_AGENT_REQUEST",
        '"request_kind"',
        '"study_id"',
        '"surface"',
        '"visible_gap"',
        '"screenshot"',
        '"resume_checkpoint"',
        "pause immediately",
        "same Researcher Agent",
        "fresh independent Content Agent",
        "study-local",
    )


def test_protocol_requires_high_risk_edit_and_two_real_restarts() -> None:
    text = protocol_text()
    blocks = checkpoint_blocks()
    assert_contains(
        blocks[10],
        "high-risk manuscript edit",
        "section approval",
        "READY_FOR_RESTART_1",
        "must not restart",
    )
    assert_contains(
        blocks[11],
        "real server restart",
        "old and new PID",
        "local and UTC",
        "HTTP health",
        "SELF_REVIEWED_DRAFT",
        "expert release",
    )
    assert_contains(blocks[15], "READY_FOR_RESTART_2", "real server restart", "old and new PID")
    assert text.count("protocol_restart=true") >= 2
    assert_contains(text, "refresh does not count", "repair restart does not count")


def test_protocol_covers_release_benchmark_hard_fails_and_credits_scope() -> None:
    blocks = checkpoint_blocks()
    assert_contains(
        blocks[11],
        "internal DOCX",
        "SELF_REVIEWED_DRAFT",
        "awaiting_human_figure",
    )
    assert_contains(
        blocks[12],
        "benchmark",
        ">=80/100",
        "seven",
        "Hard Fail",
        "numeric score never overrides",
    )
    assert_contains(blocks[13], "credits hidden", "NOT_APPLICABLE_BY_CURRENT_SCOPE")
    assert_contains(blocks[14], "refresh", "release", "currentness", "download")


def test_protocol_covers_all_viewports_console_and_network() -> None:
    blocks = checkpoint_blocks()
    assert_contains(blocks[16], "1024x900", "mandatory")
    assert_contains(blocks[17], "390x844", "observational", "release-blocking")
    assert_contains(
        blocks[18],
        "console",
        "zero warnings or errors",
        "network",
        "4xx/5xx",
        "duplicate mutation",
        "unbounded retry",
        "must not inspect headers or bodies",
    )


def test_protocol_defines_coordinator_only_artifact_audit() -> None:
    text = protocol_text()
    assert_contains(
        text,
        "Coordinator-only Artifact Audit",
        "fresh bootstrap isolation",
        "3 Generic bindings",
        "3 Chemical bindings",
        "309 molecules",
        "study-local Content packages",
        "every DOCX page",
        "contact sheet",
        "new-versus-legacy",
        "restart ledger",
        "full regression",
        "Git safety",
    )


def test_release_blocking_finding_invalidates_run_and_requires_fresh_full_run() -> None:
    text = protocol_text()
    assert_contains(
        text,
        "P0/P1 or science-affecting P2",
        "stop the current acceptance run",
        "finding evidence only",
        "brand-new full run from checkpoint 1",
        "must not resume the repaired run",
        "must not claim PASS",
    )


def test_protocol_defines_close_and_exact_tri_state_without_owner_pass_claim() -> None:
    blocks = checkpoint_blocks()
    assert_contains(blocks[19], "final evidence", "close the browser context", "tri-state")
    text = protocol_text()
    for result in ("PASS", "BLOCKED", "ENVIRONMENT_UNDETERMINED"):
        assert re.search(rf"(?m)^- `{result}`:", text)
    assert_contains(
        text,
        "QA Protocol Owner does not run Playwright",
        "does not write the real project",
        "does not create a Content package",
        "does not claim QA PASS",
    )
