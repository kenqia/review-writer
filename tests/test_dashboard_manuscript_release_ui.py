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
                "  credits:{status:'unavailable',measured:null,forecast:null},",
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


def test_dashboard_hides_all_credits_ui_and_copy() -> None:
    forbidden = ("credit", "实测消耗", "预测用量")
    for path in (
        DASHBOARD / "review.html",
        *DASHBOARD.glob("review-*.js"),
        *DASHBOARD.glob("review-*.css"),
    ):
        source = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in source, f"{path.name} exposes credits UI token: {token}"


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


def test_project_polling_preserves_loaded_project_without_full_reload() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    match = re.search(
        r"^    async function refreshProjects\(\) \{[\s\S]*?^    \}",
        html,
        flags=re.MULTILINE,
    )
    assert match is not None
    _run_node(
        "\n".join(
            [
                "const select={value:'case',append:()=>{}};",
                "const nodes={project:select,'project-waiting-message':{textContent:''},'workbench-message':{textContent:''}};",
                "const $=id=>nodes[id];",
                "const document={createElement:()=>({value:'',textContent:''})};",
                "const clear=()=>{}; const setEmptyProjectWorkspace=()=>{}; const setWorkspace=()=>{};",
                "let projectsRefreshBusy=false, projects=[], projectId='case', activeWorkspace='cockpit';",
                "let editorDirty=false, editorBusy=false, projectLoadBusy=false, exportBusy=false;",
                "let sourceUploadBusy=false, riskDecisionDirty=false;",
                "let parseQualityDirty=new Set(), parseQualityBusy=new Set();",
                "let loadCount=0; const loadProject=async()=>{loadCount+=1; return 'loaded';};",
                "const getPayload=async()=>[{project_id:'case',topic:'Case'}];",
                match.group(0),
                "refreshProjects().then(result=>{",
                "  if(result!=='unchanged') throw new Error(`unexpected result ${result}`);",
                "  if(loadCount!==0) throw new Error(`poll triggered ${loadCount} full reloads`);",
                "}).catch(error=>{console.error(error);process.exit(1);});",
            ]
        )
    )


def test_fresh_project_polling_requires_visible_researcher_selection_without_loading() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    match = re.search(
        r"^    async function refreshProjects\(\) \{[\s\S]*?^    \}",
        html,
        flags=re.MULTILINE,
    )
    assert match is not None
    _run_node(
        "\n".join(
            [
                "const select={value:'',options:[],append(option){this.options.push(option);if(option.selected)this.value=option.value;}};",
                "const nodes={project:select,'project-waiting-message':{textContent:''},'workbench-message':{textContent:''}};",
                "const $=id=>nodes[id];",
                "const document={createElement:()=>({value:'',textContent:'',disabled:false,selected:false})};",
                "const clear=node=>{node.options=[];node.value='';};",
                "let selectionWorkspaceCount=0;const setProjectSelectionWorkspace=()=>{selectionWorkspaceCount+=1;};",
                "const setEmptyProjectWorkspace=()=>{};const setWorkspace=()=>{};const setProjectLoadBusy=()=>{};",
                "let projectsRefreshBusy=false,projects=[],projectId='',projectLoadGeneration=0,activeWorkspace='cockpit';",
                "let loadCount=0;const loadProject=async()=>{loadCount+=1;return 'loaded';};",
                "const calls=[];const getPayload=async url=>{calls.push(url);return [{project_id:'regression-v1',topic:'旧项目'},{project_id:'fresh-v2',topic:'新项目'}];};",
                match.group(0),
                "refreshProjects().then(result=>{",
                " if(result!=='selection_required' || projectId!=='' || loadCount!==0) throw new Error(JSON.stringify({result,projectId,loadCount}));",
                " if(JSON.stringify(calls)!==JSON.stringify(['/api/projects'])) throw new Error(JSON.stringify(calls));",
                " if(selectionWorkspaceCount!==1 || select.value!=='' || select.options[0]?.textContent!=='请选择项目') throw new Error(JSON.stringify({selectionWorkspaceCount,select}));",
                "}).catch(error=>{console.error(error);process.exit(1);});",
            ]
        )
    )
    assert "projects[0].project_id" not in match.group(0)


def test_researcher_project_selection_loads_once_and_listener_is_bound_once() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    session_source = (DASHBOARD / "review-session.js").read_text(encoding="utf-8")
    match = re.search(
        r"^    async function selectProject\(event\) \{[\s\S]*?^    \}",
        html,
        flags=re.MULTILINE,
    )
    assert match is not None
    _run_node(
        "\n".join(
            [
                "let projectId='',activeParseStudyId='old',loadCount=0;",
                "const projects=[{project_id:'regression-v1'},{project_id:'fresh-v2'}];",
                "const confirmDiscardDraftChanges=()=>true,confirmDiscardRiskDecisions=()=>true,confirmDiscardParseQualityDecisions=()=>true;",
                "const loadProject=async()=>{loadCount+=1;return 'loaded';};",
                "const nodes={'workbench-message':{textContent:''}};const $=id=>nodes[id];",
                match.group(0),
                "(async()=>{",
                " await selectProject({target:{value:'fresh-v2'}});",
                " await selectProject({target:{value:'fresh-v2'}});",
                " if(projectId!=='fresh-v2' || activeParseStudyId!=='' || loadCount!==1) throw new Error(JSON.stringify({projectId,activeParseStudyId,loadCount}));",
                "})().catch(error=>{console.error(error);process.exit(1);});",
            ]
        )
    )
    assert html.count("$('project').addEventListener('change', selectProject)") == 1
    for storage in ("localStorage", "sessionStorage"):
        assert storage not in html
        assert storage not in session_source


def test_audit_component_keeps_closure_visible_without_internal_ids() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    parser = _DashboardParser()
    parser.feed(html)
    assert "review-audit" in parser.attributes
    assert parser.attributes["review-audit"].get("aria-labelledby") == "review-audit-heading"
    assert "/assets/dashboard/review-audit.js" in html
    assert "/assets/dashboard/review-audit.css" in html

    module_path = json.dumps(str(DASHBOARD / "review-audit.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const dimensions=Array.from({length:7},(_,index)=>({name:`维度 ${index+1}`,score:4,rationale:`理由 ${index+1}`}));",
                "const model=ui.buildAuditModel({",
                " parseQuality:{status:'approved',workflow_can_continue:true,summary:{studies:3,objects:21,needs_review:0,approved:3,pdf_locator_only:8,reparse_required:0},studies:[{study_id:'scholarly-0792992b4e71861e',objects:[{decision:{action:'pdf_locator_only'}}]}]},",
                " protocol:{status:'approved',protocol:{comparison_objects:['scholarly-0792992b4e71861e'],normalization_rules:['保留原始单位'],missing_value_policy:'缺失值不插补',incomparability_rules:['不同终点不排名'],counterevidence_rules:['保留失败结果'],claim_strength:'有边界综合',decision:{action:'approve',reason:'已核对',actor_label:'李研究员'}}},",
                " synthesis:{coverage:{corpus_kind:'calibration_corpus',axes:[{axis_id:'scope_and_limits',question:'范围如何不同',counterevidence_ids:['PE-SECRET'],incomparable_items:['终点不同'],impact_on_conclusion:'不排名'}]}},",
                " figures:{summary:{source_count:32,placeholder_count:1},source_figures:[{figure_id:'scholarly-secret:figure-1',study_id:'scholarly-secret',figure_label:'Figure 1'}],placeholders:[{placeholder_id:'placeholder-scope-v1',scientific_question:'哪些范围不可比？',reader_takeaway:'保持论文特异边界',status:'awaiting_human_figure'}]},",
                " progress:{credits:{status:'unknown',measured:null,forecast:null},credit_ledger:{status:'unavailable'}},",
                " final:{evaluation:{score:82,dimensions,hard_fails:['缺少署名'],issues:['一项待修复']}}",
                "});",
                "const encoded=JSON.stringify(model);",
                "for(const secret of ['scholarly-','calibration_corpus','placeholder-scope-v1','PE-SECRET','scope_and_limits']) if(encoded.includes(secret)) throw new Error(`leaked ${secret}: ${encoded}`);",
                "for(const label of ['解析质量','归一化规则','缺失值规则','不可比规则','反证规则','决策者：李研究员','来源署名与复用权利未提供','缺口原因未提供','Hard Fails','缺少署名','一项待修复']) if(!encoded.includes(label)) throw new Error(`missing ${label}: ${encoded}`);",
                "for(const hidden of ['credits','credit_ledger','实测消耗','预测用量']) if(encoded.toLowerCase().includes(hidden)) throw new Error(`exposed ${hidden}: ${encoded}`);",
                "if(model.evaluation.dimensions.length!==7 || model.evaluation.score!=='82') throw new Error(encoded);",
            ]
        )
    )


def test_audit_component_does_not_invent_missing_evaluation() -> None:
    module_path = json.dumps(str(DASHBOARD / "review-audit.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.buildAuditModel({final:{quality_report:{status:'SELF_REVIEWED_DRAFT',errors:[],warnings:[]}}});",
                "const encoded=JSON.stringify(model.evaluation);",
                "if(model.evaluation.available) throw new Error(encoded);",
                "if(!encoded.includes('评估数据未提供')) throw new Error(encoded);",
                "if(encoded.includes('通过') || encoded.includes('100') || encoded.includes('0分')) throw new Error(`invented verdict: ${encoded}`);",
            ]
        )
    )


def test_audit_component_consumes_evaluation_but_ignores_credits_payloads() -> None:
    module_path = json.dumps(str(DASHBOARD / "review-audit.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const rubric=Array.from({length:7},(_,index)=>({dimension_id:`dimension_${index+1}`,score:index+1,rationale:`理由 ${index+1}`}));",
                "const model=ui.buildAuditModel({",
                " progress:{credits:{measured:7,forecast:8},credit_ledger:{status:'available',measured:{before:2004,after:1351,consumed:653},forecast:650}},",
                " final:{evaluation:{schema_version:'release-evaluation.v1',benchmark:{status:'available',score:83,rubric,hard_fails:['WRONG_SOURCE_BINDING'],issues:['SYNTHESIS_FIGURE_PENDING']},credit_ledger:{status:'available',measured:{consumed:653},forecast:650}}}",
                "});",
                "const encoded=JSON.stringify(model);",
                "if(Object.prototype.hasOwnProperty.call(model,'credits')) throw new Error(`credits model exposed: ${encoded}`);",
                "if(model.evaluation.score!=='83' || model.evaluation.dimensions.length!==7) throw new Error(encoded);",
                "if(!encoded.includes('来源绑定与当前发布不一致') || !encoded.includes('综合图仍待研究者完成')) throw new Error(encoded);",
                "if(encoded.includes('WRONG_SOURCE_BINDING') || encoded.includes('SYNTHESIS_FIGURE_PENDING')) throw new Error(`exposed internal evaluation code: ${encoded}`);",
                "for(const hidden of ['credits','credit_ledger','实测消耗','预测用量']) if(encoded.toLowerCase().includes(hidden)) throw new Error(`exposed ${hidden}: ${encoded}`);",
                "if(encoded.includes('：0') || encoded.includes(':0')) throw new Error(`invented zero: ${encoded}`);",
            ]
        )
    )


def test_research_workspaces_do_not_render_opaque_identifiers() -> None:
    evidence = (DASHBOARD / "review-evidence.js").read_text(encoding="utf-8")
    synthesis = (DASHBOARD / "review-synthesis.js").read_text(encoding="utf-8")
    assert "item.study_id ||" not in evidence
    assert "coverage.corpus_kind" not in synthesis
    assert "item.placeholder_id" not in synthesis
    assert "item.section_id" not in synthesis
    assert "item.supporting_evidence_ids || []).join" not in synthesis
    for label in ("归一化规则", "缺失值规则", "不可比规则", "反证规则"):
        assert label in synthesis
