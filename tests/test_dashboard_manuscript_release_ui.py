from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "view" / "assets" / "dashboard"


class _DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.attributes: dict[str, dict[str, str]] = {}

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        element_id = values.get("id")
        if element_id:
            self.ids.append(element_id)
            self.attributes[element_id] = values


def _run_node(source: str) -> None:
    node = shutil.which("node")
    assert node is not None
    completed = subprocess.run(
        [node, "-e", source],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_manuscript_workspace_has_parallel_context_and_named_controls() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    parser = _DashboardParser()
    parser.feed(html)

    assert len(parser.ids) == len(set(parser.ids))
    for element_id in (
        "high-risk-review",
        "section-editor",
        "high-risk-reason",
        "approve-high-risk-edit",
        "manuscript-conflict-alert",
        "evidence-context-panel",
        "synthesis-context-panel",
        "source-figure-context-panel",
        "export-docx",
        "export-verified-release",
        "download-docx",
        "download-verified-release",
        "release-status-message",
    ):
        assert element_id in parser.attributes

    assert parser.attributes["section-editor"].get("aria-describedby")
    assert parser.attributes["high-risk-reason"].get("aria-label")
    assert parser.attributes["manuscript-conflict-alert"].get("role") == "alert"
    assert parser.attributes["release-status-message"].get("aria-live") == "polite"
    assert "/assets/dashboard/review-manuscript.js" in html
    assert "/assets/dashboard/review-release.js" in html
    assert "/assets/dashboard/review-manuscript.css" in html
    assert "/assets/dashboard/review-release.css" in html


def test_manuscript_component_filters_sensitive_fields_and_preserves_409() -> None:
    module_path = json.dumps(str(DASHBOARD / "review-manuscript.js"))
    _run_node(
        "\n".join(
            [
                f"const ui = require({module_path});",
                "const safe = ui.projectManuscript({",
                "  route:'evidence-to-release.v1', status:'needs_human_edit',",
                "  path:'/private/manuscript.md', hash:'a'.repeat(64), schema_version:'hidden',",
                "  prompt:'hidden prompt', internal_json:{secret:true},",
                "  sections:[{section_id:'s1', heading:'结果', body:'原表述', status:'needs_human_edit', version_token:'opaque-v1', high_risk_reasons:['quantitative'], claim_bindings:[{paper_evidence_ids:['e1'], synthesis_ids:['c1']}], unknown_path:'/private'}],",
                "  evidence:[{evidence_id:'e1', statement:'论文报告了该结果', epistemic_type:'experimental_observation', locator_label:'第 3 页', pdf_page_url:'/safe/pdf'}],",
                "  synthesis:[{synthesis_id:'c1', proposition:'跨研究判断', applicability_boundary:'仅限所审查条件'}],",
                "  source_figures:[{figure_id:'f1', title:'原论文图 2', caption:'实验结果', image_url:'/safe/figure', pdf_page_url:'/safe/page', evidence_ids:['e1']}]",
                "});",
                "if (safe.path || safe.hash || safe.schema_version || safe.prompt || safe.internal_json) throw new Error('sensitive top-level field leaked');",
                "if (safe.sections[0].unknown_path) throw new Error('sensitive nested field leaked');",
                "if (safe.sections[0].risk_classes[0] !== 'quantitative') throw new Error('high-risk reasons were dropped');",
                "if (safe.source_figures[0].linked_evidence_ids[0] !== 'e1') throw new Error('figure evidence binding was dropped');",
                "const request = ui.buildEditRequest(safe.sections[0], '收窄后的表述', '逐项核对原论文与综合判断。');",
                "if (request.actor_type !== 'simulated_researcher_agent' || request.version_token !== 'opaque-v1') throw new Error(JSON.stringify(request));",
                "let conflict = 0, success = 0;",
                "ui.saveEdit({",
                "  request:async () => ({ok:false,status:409,json:async()=>({})}),",
                "  url:'/api/project/case/draft', payload:request,",
                "  onConflict:() => { conflict += 1; }, onSuccess:() => { success += 1; }",
                "}).then(async result => {",
                "  if (result.status !== 'conflict' || conflict !== 1 || success !== 0) throw new Error(JSON.stringify(result));",
                "  const bound = await ui.saveEdit({request:async function () { if (this !== globalThis) throw new Error('request context lost'); return {ok:true,status:200,json:async()=>({saved:true})}; },url:'/api/project/case/draft',payload:request});",
                "  if (bound.status !== 'saved') throw new Error(JSON.stringify(bound));",
                "}).catch(error => { console.error(error); process.exit(1); });",
            ]
        )
    )


def test_release_component_separates_levels_and_hides_stale_downloads() -> None:
    module_path = json.dumps(str(DASHBOARD / "review-release.js"))
    _run_node(
        "\n".join(
            [
                f"const ui = require({module_path});",
                "const controls = ui.deriveReleaseControls({",
                "  capabilities:{internal_draft_export_ready:true,verified_release_ready:true},",
                "  figures:{placeholders:[{placeholder_id:'p1',status:'awaiting_human_figure'}]},",
                "  artifacts:{internal:{exists:true,current:false,download_url:'/file?path=stale.docx'},verified:{exists:true,current:true,download_url:'/file?path=verified.docx'}}",
                "});",
                "if (controls.internal.disabled) throw new Error('placeholder blocked internal draft');",
                "if (!controls.verified.disabled || controls.verified.reason !== 'FIGURE_PLACEHOLDER_PENDING') throw new Error(JSON.stringify(controls));",
                "if (controls.internal.downloadVisible) throw new Error('stale internal download remained visible');",
                "if (!controls.verified.downloadVisible) throw new Error('current verified download hidden');",
                "const unsafe = ui.deriveReleaseControls({capabilities:{internal_draft_export_ready:true},artifacts:{internal:{exists:true,current:true,download_url:'javascript:alert(1)'}}});",
                "if (unsafe.internal.downloadVisible || unsafe.internal.downloadUrl !== '#') throw new Error('unsafe artifact URL remained available');",
                "const internal = ui.buildExportRequest('SELF_REVIEWED_DRAFT');",
                "const verified = ui.buildExportRequest('EXPERT_REVIEWED_RELEASE');",
                "if (internal.release_level === verified.release_level) throw new Error('release levels collapsed');",
            ]
        )
    )


def test_busy_state_does_not_reenable_expert_release_with_placeholder() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    match = re.search(
        r"^    function applyWorkbenchBusyState\(busy\) \{[\s\S]*?^    \}",
        html,
        flags=re.MULTILINE,
    )
    assert match is not None
    _run_node(
        "\n".join(
            [
                "const nodes = new Proxy({}, {get:(target,id) => target[id] ||= {disabled:false}});",
                "const $ = id => nodes[id];",
                "const document = {querySelectorAll:() => []};",
                "let exportBusy=false, sourceUploadBusy=false, sourceSupplementBusy=false, sourceMappingBusy=false;",
                "let parseQualityBusy=new Set(), projectId='case', projectLoadGeneration=2;",
                "let progressCapabilityProjectId='case', progressCapabilityGeneration=2;",
                "let progressPayload={release_capabilities:{internal_draft_export_ready:true,verified_release_ready:true}};",
                "let reviewFigurePayload={placeholders:[{status:'awaiting_human_figure'}]};",
                "const parseQualityGateActive=() => false;",
                match.group(0),
                "applyWorkbenchBusyState(false);",
                "if (nodes['export-docx'].disabled) throw new Error('placeholder blocked internal draft');",
                "if (!nodes['export-verified-release'].disabled) throw new Error('busy restore bypassed placeholder');",
            ]
        )
    )


def test_synthesis_ui_does_not_render_raw_json() -> None:
    source = (DASHBOARD / "review-synthesis.js").read_text(encoding="utf-8")
    assert "JSON.stringify(axis)" not in source
    assert "JSON.stringify(item.figure_plan" not in source
