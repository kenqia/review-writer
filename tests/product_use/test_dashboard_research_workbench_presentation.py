from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from review_writer.project.paper_evidence import apply_paper_evidence_decision, paper_evidence_state
from review_writer.project.review_figures import (
    load_source_figure_registry,
    source_figure_registry_digest,
    source_figure_workspace_revision,
    source_figure_workspace_token,
    write_source_figure_selection,
)
from review_writer.project.synthesis import apply_comparison_protocol_decision, register_comparison_protocol
from view import serve_review_dashboard as dashboard
from tests.product_use import test_prod006_source_to_release as prod006_fixture


PROJECT_ID = prod006_fixture.PROJECT_ID
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _get_text(base_url: str, path: str) -> str:
    request = Request(f"{base_url}{path}", method="GET")
    with urlopen(request, timeout=15) as response:
        assert response.status == 200
        return response.read().decode("utf-8")


def _get_json(base_url: str, path: str) -> object:
    return json.loads(_get_text(base_url, path))


def _put_json(base_url: str, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        method="PUT",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_dashboard_presents_canonical_research_workbench_shell_and_data() -> None:
    with tempfile.TemporaryDirectory(prefix="dashboard-research-workbench-") as temporary_root:
        review_root = Path(temporary_root)
        project = prod006_fixture._build_project(review_root)
        review_state_path = project / "00_brief" / "review_state.json"
        review_state = json.loads(review_state_path.read_text(encoding="utf-8"))
        review_state["brief"] = {
            "topic": "Tiny source-to-release product path",
            "project_label": "Tiny source-to-release product path",
        }
        review_state_path.write_text(
            json.dumps(review_state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        server, thread, base_url = prod006_fixture._start_dashboard(review_root)
        try:
            html = _get_text(base_url, "/review")
            assert 'aria-label="Research workflow"' in html
            for label in ("Scope", "Corpus", "Evidence", "Matrix", "Draft", "Figures", "Release"):
                assert label in html
            assert 'id="research-workbench-overview"' in html
            assert 'id="overview-next-action"' in html
            assert 'id="resume-hold"' in html

            evidence = _get_json(
                base_url,
                f"/api/project/{PROJECT_ID}/paper-evidence",
            )
            assert isinstance(evidence, dict)
            assert evidence["items"][0]["evidence_id"] == "evidence-prod006-observation"
            assert evidence["items"][0]["statement"] == (
                "The tiny source reports a bounded conversion result."
            )
            assert evidence["items"][0]["locator"]["exact_quote"] == evidence["items"][0]["statement"]

            draft_payload = _get_json(base_url, f"/api/project/{PROJECT_ID}/draft")
            assert isinstance(draft_payload, dict)
            assert draft_payload["route"] == "evidence-to-release.v1"
            assert draft_payload["sections"][0]["section_id"]
            assert draft_payload["sections"][0]["version_token"]

            draft_html = _get_text(base_url, "/draft")
            assert 'id="research-manuscript-reader"' in draft_html
            assert 'id="research-section-editor"' in draft_html
            assert 'review-manuscript.js' in draft_html

            protocol = _get_json(
                base_url,
                f"/api/project/{PROJECT_ID}/comparison-protocol",
            )
            assert isinstance(protocol, dict)
            assert protocol["route"] == "evidence-to-release.v1"
            assert protocol["protocol"]["comparison_objects"]
            matrix_html = _get_text(base_url, "/matrix")
            assert 'id="canonical-comparison-matrix"' in matrix_html
            assert 'id="matrix-next-extraction"' in matrix_html

            evidence_html = _get_text(base_url, "/review")
            assert 'id="canonical-evidence-records"' in evidence_html
            assert "当前性" in evidence_html
            assert "支持 / 反驳 / 缺口 / 冲突 / 待核对" in evidence_html

            figures = _get_json(base_url, f"/api/project/{PROJECT_ID}/review-figures")
            assert isinstance(figures, dict)
            assert figures["route"] == "evidence-to-release.v1"
            assert figures["source_figures"][0]["study_id"]
            figures_html = _get_text(base_url, "/figures")
            assert 'id="canonical-source-figures"' in figures_html
            assert "来源署名" in figures_html
            assert 'id="figure-target-binding"' in figures_html
            assert 'id="save-figure-target-binding"' in figures_html
            assert "target_binding" in figures_html
            assert "review-figures" in figures_html

            final_payload = _get_json(base_url, f"/api/project/{PROJECT_ID}/final")
            assert isinstance(final_payload, dict)
            assert "release_snapshot" in final_payload
            final_html = _get_text(base_url, "/final")
            assert 'id="current-version-state"' in final_html
            assert 'id="same-version-exports"' in final_html

            discovery_html = _get_text(base_url, "/discovery")
            discovery_lower = discovery_html.lower()
            for theme_token in ("palladium", "gold_silver", "copper", "rhodium", "nickel", "au / ag"):
                assert theme_token not in discovery_lower
            assert "驾驶舱" not in html
            assert "Research cockpit" not in html
        finally:
            prod006_fixture._stop_dashboard(server, thread)


def test_persisted_legacy_topic_remains_selectable_without_mutating_project_authority() -> None:
    """A data-ready legacy project uses its persisted topic, never its directory name."""
    with tempfile.TemporaryDirectory(prefix="dashboard-project-label-") as temporary_root:
        review_root = Path(temporary_root)
        project = prod006_fixture._build_project(review_root)
        state_path = project / "00_brief" / "review_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["topic"] == "Tiny source-to-release product path"
        assert "brief" not in state
        before = {
            path.relative_to(project): path.read_bytes()
            for path in project.rglob("*")
            if path.is_file()
        }

        for _ in range(2):
            server, thread, base_url = prod006_fixture._start_dashboard(review_root)
            try:
                projects = _get_json(base_url, "/api/projects")
                assert isinstance(projects, list)
                row = next(item for item in projects if item["project_id"] == PROJECT_ID)
                assert row["topic"] == state["topic"]
                assert row["visible_label"] == state["topic"]
                assert row["selectable"] is True
                assert row["selection_message"] == ""
            finally:
                prod006_fixture._stop_dashboard(server, thread)

        after = {
            path.relative_to(project): path.read_bytes()
            for path in project.rglob("*")
            if path.is_file()
        }
        assert after == before


def test_missing_or_corrupt_project_metadata_remains_unselectable() -> None:
    """A persisted topic is a compatibility input, not a fallback for invalid metadata."""
    with tempfile.TemporaryDirectory(prefix="dashboard-project-label-invalid-") as temporary_root:
        review_root = Path(temporary_root)
        for project_id, review_state in (
            ("missing-metadata", None),
            ("corrupt-metadata", "{not-json"),
        ):
            project = review_root / project_id
            (project / "01_evidence").mkdir(parents=True)
            (project / "01_evidence" / "evidence_cards.jsonl").write_text("", encoding="utf-8")
            if review_state is not None:
                (project / "00_brief").mkdir()
                (project / "00_brief" / "review_state.json").write_text(review_state, encoding="utf-8")

        projects = dashboard.list_review_projects(review_root)
        by_id = {item["project_id"]: item for item in projects}
        for project_id in ("missing-metadata", "corrupt-metadata"):
            assert by_id[project_id]["selectable"] is False
            assert by_id[project_id]["has_valid_label"] is False


def test_dashboard_navigation_groups_routes_and_legacy_project_urls() -> None:
    """Presentation keeps one IA, one project parameter, and hidden technical detail."""
    assets = REPOSITORY_ROOT / "view" / "assets" / "dashboard"
    shared_ui = (assets / "review-ui.js").read_text(encoding="utf-8")
    shared_css = (assets / "review-ui.css").read_text(encoding="utf-8")

    assert "const navigationGroups" in shared_ui
    for label in ("首页", "来源与证据", "正文", "图表", "发布与历史"):
        assert label in shared_ui
    assert 'aliases: ["draft", "blueprint", "sections"]' not in shared_ui
    assert "legacyProjectIdFromLocation" in shared_ui
    assert "if (params.has(\"project\") && !params.has(\"project_id\"))" in shared_ui
    assert "setProjectIdInLocation(params.get(\"project\"));" in shared_ui
    assert "function normalizeLegacyProjectLocation()" in shared_ui
    assert "function syncReviewFocus()" in shared_ui
    assert 'dataset.reviewFocus = evidenceFocused ? "evidence" : "overview"' in shared_ui
    assert 'location.hash.toLowerCase() === "#evidence"' in shared_ui
    assert "rw-overview-focus" in shared_ui
    assert "rw-evidence-focus" in shared_ui
    assert "window.addEventListener(\"hashchange\", () => { syncReviewFocus(); makeWorkflowNav(); });" in shared_ui
    assert shared_ui.rfind("normalizeLegacyProjectLocation();") < shared_ui.index(
        "if (document.readyState"
    )
    assert "--rw-canvas" in shared_css
    final_shell = shared_css.rsplit("/* Shared dashboard shell:", 1)[1]
    assert "linear-gradient" not in final_shell
    assert "background-image: none" in final_shell
    assert "body.page-review.rw-overview-focus #cockpit-workspace" in final_shell
    assert "body.page-review.rw-evidence-focus #cockpit-workspace .research-rail" in final_shell
    assert 'body.page-review[data-review-focus="overview"] #cockpit-workspace' in final_shell
    assert 'body.page-review[data-review-focus="evidence"] #research-workbench-overview' in final_shell

    for page in ("discovery", "matrix", "blueprint", "sections", "figures", "final"):
        source = (assets / f"{page}.html").read_text(encoding="utf-8")
        assert "projectIdFromLocation" in source
        assert "setProjectIdInLocation" in source

    library = (assets / "library.html").read_text(encoding="utf-8")
    assert "project_id" in library
    assert "?project=" not in library
    assert "window.ReviewPresentation?.projectIdFromLocation" in library
    assert "const requestedProjectId = window.ReviewPresentation?.projectIdFromLocation() || '';" in library
    assert "option.textContent = p.visible_label || p.topic || p.project_id;" in library
    assert "option.disabled = p.selectable !== true;" in library
    assert "els.globalProjectSelect.value = requestedProjectId;" in library

    for page in ("matrix", "blueprint", "sections", "figures"):
        source = (assets / f"{page}.html").read_text(encoding="utf-8")
        assert "技术详情" in source


def test_deferred_workspace_scripts_refresh_after_projects_load() -> None:
    """Deferred workspaces cannot miss the first project-selection event."""
    assets = REPOSITORY_ROOT / "view" / "assets" / "dashboard"
    for name in ("review-evidence.js", "review-synthesis.js"):
        source = (assets / name).read_text(encoding="utf-8")
        assert "if (document.readyState === \"loading\")" in source
        assert "document.addEventListener(\"DOMContentLoaded\", coordinator.refresh);" in source
        assert "else coordinator.refresh();" in source


def test_blank_project_evidence_surface_falls_back_without_legacy_cockpit() -> None:
    """An unprepared project keeps the canonical Evidence surface readable."""
    assets = REPOSITORY_ROOT / "view" / "assets" / "dashboard"
    evidence = (assets / "review-evidence.js").read_text(encoding="utf-8")
    synthesis = (assets / "review-synthesis.js").read_text(encoding="utf-8")
    shared_css = (assets / "review-ui.css").read_text(encoding="utf-8")
    shared_ui = (assets / "review-ui.js").read_text(encoding="utf-8")
    review_page = (assets / "review.html").read_text(encoding="utf-8")

    assert 'shell.hidden = false;' in evidence
    assert "尚未生成 Paper Evidence；来源准备完成后，研究者可在此逐项核对。" in evidence
    assert "综合判断将在 Paper Evidence 完成人工核对后显示。" in synthesis
    assert 'body.page-review[data-review-focus="evidence"] #cockpit-workspace {\n  display: contents !important;' in shared_css
    assert 'reviewState?.status === "AWAITING_BRIEF_CONFIRMATION"' in shared_ui
    assert "const awaitingBrief = nextProjectState.status === 'AWAITING_BRIEF_CONFIRMATION';" in review_page
    assert "确认综述简报后才读取解析状态。" in review_page


def test_source_handoff_remains_reachable_for_human_action_in_evidence_focus() -> None:
    """A native source-role decision stays visible on the canonical Evidence surface."""
    assets = REPOSITORY_ROOT / "view" / "assets" / "dashboard"
    shared_css = (assets / "review-ui.css").read_text(encoding="utf-8")
    review_page = (assets / "review.html").read_text(encoding="utf-8")

    evidence_rules = shared_css[shared_css.index('body.page-review.rw-evidence-focus'):]
    assert "#cockpit-workspace #source-stage-panel" not in evidence_rules
    assert "id=\"source-stage-panel\" class=\"stage-task-panel\" hidden" in review_page
    assert "preflight?.status === 'awaiting_confirmation'" in review_page
    assert "role_options || ['MAIN', 'SI']" in review_page
    assert "确认来源角色" in review_page


def test_source_figure_selection_recomputes_persisted_budget_aggregates() -> None:
    """Every accepted selection updates the canonical registry budget, not only the row."""
    with tempfile.TemporaryDirectory(prefix="dashboard-figure-budget-") as temporary_root:
        review_root = Path(temporary_root)
        project = prod006_fixture._build_project(review_root)
        registry_path = project / "03_figures" / "source_figure_registry.json"
        registry = load_source_figure_registry(project)
        original = registry["figures"][0]
        rows = []
        for index in range(4):
            row = json.loads(json.dumps(original))
            row["figure_id"] = f"{original['figure_id']}-budget-{index + 1}"
            row["selection_status"] = "selected" if index == 0 else "available"
            rows.append(row)
        registry["figures"] = rows
        registry["registry_digest"] = source_figure_registry_digest(registry)
        initial_digest = registry["registry_digest"]
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        manuscript_sha256 = __import__("hashlib").sha256(
            (project / "04_manuscript" / "manuscript.md").read_bytes()
        ).hexdigest()
        for row in rows[1:]:
            current = load_source_figure_registry(project)
            current_row = next(item for item in current["figures"] if item["figure_id"] == row["figure_id"])
            token = source_figure_workspace_token(
                row["figure_id"], source_figure_workspace_revision(current, current_row, manuscript_sha256)
            )
            write_source_figure_selection(
                project,
                figure_id=row["figure_id"],
                selection_status="selected",
                version_token=token,
            )

        final = load_source_figure_registry(project)
        assert final["registry_digest"] != initial_digest
        assert sum(row["selection_status"] == "selected" for row in final["figures"]) == 4
        assert final["selected_count"] == 4
        assert final["figure_budget"] == {
            "status": "needs_human_selection",
            "selected_count": 4,
            "required_count": 1,
            "minimum": 5,
            "maximum": 8,
            "gaps": ["Select 1 additional non-duplicative source figure(s) or register a synthesis placeholder."],
        }


def test_stage_request_gating_preserves_ready_callers() -> None:
    """Readiness gating skips stage endpoints only before the canonical stage is ready."""
    review_page = (REPOSITORY_ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(
        encoding="utf-8"
    )
    load_project = review_page[review_page.index("    async function loadProject()") :]

    assert "const awaitingBrief = nextProjectState.status === 'AWAITING_BRIEF_CONFIRMATION';" in load_project
    assert "const stageDataReady = !['review_brief', 'ready_for_discovery', 'sources', 'parsing'].includes(currentStage);" in load_project
    assert "const finalDataReady = ['final', 'complete'].includes(currentStage)" in load_project
    assert "awaitingBrief || !finalDataReady\n            ? Promise.resolve({final_draft_docx_exists:false,final_draft_docx_path:''})\n            : optionalPayload(`/api/project/${encoded}/final`" in load_project
    assert "awaitingBrief || !stageDataReady\n            ? Promise.resolve({})\n            : optionalPayload(ReviewChemicalPaperUI.routes(requestedProjectId).read" in load_project
    assert "awaitingBrief || !stageDataReady\n            ? Promise.resolve(ReviewDualParseUI.projectionModel({" in load_project
    assert ": ReviewDualParseUI.load(requestedProjectId, fetch)," in load_project


def test_parse_quality_decision_surface_is_reachable_from_sources_workspace() -> None:
    """Parse-quality review stays in the existing Evidence surface, not a hidden cockpit panel."""
    assets = REPOSITORY_ROOT / "view" / "assets" / "dashboard"
    review_page = (assets / "review.html").read_text(encoding="utf-8")
    shared_css = (assets / "review-ui.css").read_text(encoding="utf-8")
    library_page = (assets / "library.html").read_text(encoding="utf-8")

    assert "dataset.reviewStage" in review_page
    assert "? 'parse-quality'" in review_page
    assert "rw-evidence-focus[data-review-stage=\"parse-quality\"] #evidence-synthesis-workspace" in shared_css
    assert "rw-evidence-focus[data-review-stage=\"parse-quality\"] #cockpit-workspace #parse-quality-stage-panel" in shared_css
    assert 'id="parse-quality-entry"' in library_page
    assert 'id="parse-quality-entry-link"' in library_page
    assert "/parse-quality`" in library_page
    assert "status === 'needs_review'" in library_page


def test_fresh_bootstrap_gating_is_fail_closed_without_canonical_route() -> None:
    """A native bootstrap has no route until its stage authority is ready."""
    assets = REPOSITORY_ROOT / "view" / "assets" / "dashboard"
    review_page = (assets / "review.html").read_text(encoding="utf-8")
    shared_ui = (assets / "review-ui.js").read_text(encoding="utf-8")

    assert (
        "const stageDataReady = !['review_brief', 'ready_for_discovery', 'sources', "
        "'parsing'].includes(currentStage);"
    ) in review_page
    assert "const stageDataReady = !canonicalRoute" not in review_page
    assert "const finalDataReady = ['final', 'complete'].includes(currentStage)" in review_page
    assert "nextProjectState.draft?.final_draft_exists || nextProjectState.draft?.docx_exists" in review_page
    assert "const finalDataReady = [\"final\", \"complete\"].includes(reviewState?.current_stage)" in shared_ui
    assert "reviewState?.draft?.final_draft_exists || reviewState?.draft?.docx_exists" in shared_ui


def test_stale_comparison_protocol_exposes_reapproval_without_duplicate_current_action() -> None:
    source = (REPOSITORY_ROOT / "view" / "assets" / "dashboard" / "review-synthesis.js").read_text(
        encoding="utf-8"
    )

    assert 'const protocolNeedsReapproval = Boolean(p.decision)' in source
    assert 'protocol.status === "needs_review"' in source
    assert 'protocol.status === "stale"' in source
    assert 'if (!p.decision || protocolNeedsReapproval)' in source
    assert 'protocolNeedsReapproval ? "重新批准比较协议" : "批准比较协议"' in source


def test_comparison_protocol_rebuild_requires_second_human_approval_after_evidence_change() -> None:
    with tempfile.TemporaryDirectory(prefix="dashboard-comparison-rebuild-") as temporary_root:
        review_root = Path(temporary_root)
        project = prod006_fixture._build_project(review_root)
        protocol = register_comparison_protocol(
            project,
            {
                "comparison_id": "comparison-dashboard-rebuild",
                "comparison_objects": [prod006_fixture.EVIDENCE_ID],
                "axes": ["reported outcome"],
                "normalization_rules": ["Keep source-reported wording and units."],
                "missing_value_policy": "Missing values remain unknown.",
                "incomparability_rules": ["Do not compare absent studies."],
                "counterevidence_rules": ["Record unresolved counterevidence explicitly."],
                "claim_strength": "bounded",
            },
        )
        apply_comparison_protocol_decision(
            project,
            {
                "action": "approve",
                "reason": "Approved the bounded comparison protocol before the evidence update.",
            },
        )
        candidate = paper_evidence_state(project)["rows"][0]
        apply_paper_evidence_decision(
            project,
            {
                "evidence_id": candidate["evidence_id"],
                "candidate_digest": candidate["candidate_digest"],
                "bound_parse_object_digests": candidate["bound_parse_object_digests"],
                "source_pdf_sha256": candidate["source_pdf_sha256"],
                "action": "revise_and_approve",
                "replacement_statement": "The tiny source reports a revised bounded conversion result.",
                "reason": "Researcher revised the source-bound wording after rechecking the locator.",
            },
        )

        server, thread, base_url = prod006_fixture._start_dashboard(review_root)
        try:
            path = f"/api/project/{PROJECT_ID}/comparison-protocol"
            before = _get_json(base_url, path)
            assert before["status"] == "needs_review"
            old_token = before["protocol"]["version_token"]
            protocol_path = project / "02_synthesis/comparison_protocol.json"
            protocol_bytes_before_rejected_requests = protocol_path.read_bytes()
            status, _ = _put_json(
                base_url,
                path,
                {
                    "action": "not-a-decision",
                    "reason": "Invalid action must not rebuild or write.",
                    "version_token": old_token,
                },
            )
            assert status == 400
            assert protocol_path.read_bytes() == protocol_bytes_before_rejected_requests
            status, _ = _put_json(
                base_url,
                path,
                {
                    "action": "approve",
                    "reason": "Stale token must not rebuild or write.",
                    "version_token": "stale-" + old_token,
                },
            )
            assert status == 409
            assert protocol_path.read_bytes() == protocol_bytes_before_rejected_requests
            status, rebuilt = _put_json(
                base_url,
                path,
                {
                    "action": "approve",
                    "reason": "Recheck the protocol against the changed evidence projection.",
                    "version_token": old_token,
                },
            )
            assert status == 200
            assert rebuilt["status"] == "needs_review"
            assert rebuilt["workflow_can_continue"] is False
            assert rebuilt["protocol"]["decision"] is None
            assert rebuilt["protocol"]["version_token"] != old_token

            status, approved = _put_json(
                base_url,
                path,
                {
                    "action": "approve",
                    "reason": "Researcher approved the rebuilt protocol after reviewing the changed evidence.",
                    "version_token": rebuilt["protocol"]["version_token"],
                },
            )
            assert status == 200
            assert approved["status"] == "approved"
            assert approved["workflow_can_continue"] is True
            assert approved["protocol"]["decision"]["action"] == "approve"
        finally:
            prod006_fixture._stop_dashboard(server, thread)


def test_final_currentness_accepts_chemical_paper_release_markdown_binding() -> None:
    """Release Markdown may include canonical Chemical Paper limitations."""
    project_text = os.environ.get("REVIEW_WRITER_DATA_READY_PROJECT")
    if not project_text:
        pytest.skip("requires an isolated data-ready project")
    project = Path(project_text)
    state = dashboard._project_release_artifact_state(project)
    assert state["snapshot_path"].read_bytes() != state["authoritative_path"].read_bytes()
    assert dashboard.new_route_release_docx_is_current(state["docx_path"]) is True
    assert state["snapshot_matches"] is True
    assert state["integrity_valid"] is True
