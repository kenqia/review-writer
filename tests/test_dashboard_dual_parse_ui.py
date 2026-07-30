from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "view" / "assets" / "dashboard"
REVIEW_HTML = DASHBOARD / "review.html"
DUAL_SCRIPT = DASHBOARD / "review-dual-parse.js"
DUAL_STYLE = DASHBOARD / "review-dual-parse.css"


class _DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.attributes: dict[str, dict[str, str]] = {}

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("id"):
            self.attributes[values["id"]] = values


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


def test_page_exposes_unified_dual_parse_workspace() -> None:
    html = REVIEW_HTML.read_text(encoding="utf-8")
    parser = _DashboardParser()
    parser.feed(html)

    for node_id in (
        "dual-parse-workspace",
        "dual-study-status",
        "chemical-import-preflight",
        "chemical-completion-queue",
        "reconciliation-list",
    ):
        assert node_id in parser.attributes

    assert parser.attributes["dual-parse-workspace"].get("aria-labelledby") == (
        "dual-parse-heading"
    )
    assert "/assets/dashboard/review-dual-parse.js" in html
    assert "/assets/dashboard/review-dual-parse.css" in html


def test_projection_model_exposes_safe_status_actor_freshness_and_one_next_action() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',",
                " next_action:{label:'确认第一篇 Chemical Paper 导入',description:'先核对预检摘要，再确认写入。'},",
                " studies:[{study_id:'internal-study-a',citation:'Core study A',tier:'core',",
                "  pdf:{status:'verified'},generic_parse:{status:'current'},",
                "  chemical:{status:'needs_import'},completion:{status:'blocked'},",
                "  reconciliation:{status:'blocked'},evidence:{status:'unavailable'},",
                "  actor_label:'模拟研究者',updated_at:'2026-07-30T09:00:00Z'}],",
                " path:'/home/private/project',source_pdf_sha256:'a'.repeat(64),raw_json:{secret:true},credits:{value:3}});",
                "if(!model.contractValid || model.status!=='ready') throw new Error(JSON.stringify(model));",
                "if(model.nextAction.label!=='确认第一篇 Chemical Paper 导入' || model.nextActions!==undefined) throw new Error(JSON.stringify(model));",
                "const study=model.studies[0];",
                "if(study.displayLabel!=='研究 1' || study.pdfLabel!=='PDF 已核验' || study.genericLabel!=='Generic Parse 当前有效') throw new Error(JSON.stringify(study));",
                "if(study.actorLabel!=='模拟研究者' || study.updatedLabel!=='2026-07-30T09:00:00Z') throw new Error(JSON.stringify(study));",
                "const encoded=JSON.stringify(model).toLowerCase();",
                "for(const forbidden of ['internal-study-a','/home/','sha256','raw_json','credit']) if(encoded.includes(forbidden)) throw new Error(`leaked ${forbidden}`);",
                "const unknown=ui.projectionModel({schema_version:'other',status:'ready',studies:[{citation:'must hide'}]});",
                "if(unknown.contractValid || unknown.status!=='unknown' || unknown.studies.length) throw new Error(JSON.stringify(unknown));",
            ]
        )
    )


def test_http_request_builders_serialize_frozen_snake_case_contracts() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const actor={actorType:'simulated_researcher_agent',actorLabel:'simulated_researcher'};",
                "const file={name:'chemical.zip'};",
                "const preflight=ui.importPreflightRequest('study-a',file);",
                "if(preflight.study_id!=='study-a' || preflight.file!==file || Object.keys(preflight).length!==2) throw new Error(JSON.stringify(preflight));",
                "const confirm=ui.importConfirmRequest('study-a','opaque-preflight',actor);",
                "if(JSON.stringify(confirm)!==JSON.stringify({study_id:'study-a',preflight_token:'opaque-preflight',actor_type:'simulated_researcher_agent',actor_label:'simulated_researcher'})) throw new Error(JSON.stringify(confirm));",
                "const completion=ui.completionBatchRequest('study-a','opaque-version',[{moleculeIndex:7,field:'smiles_expanded',value:'C=C',reason:'Scheme 2 supports the value.',pdfLocator:{page:3,figureLabel:'Scheme 2'}}],actor);",
                "if(JSON.stringify(completion)!==JSON.stringify({study_id:'study-a',version_token:'opaque-version',actor_type:'simulated_researcher_agent',actor_label:'simulated_researcher',corrections:[{molecule_index:7,field:'smiles_expanded',value:'C=C',reason:'Scheme 2 supports the value.',pdf_locator:{page:3,figure_label:'Scheme 2'}}]})) throw new Error(JSON.stringify(completion));",
                "const decision=ui.reconciliationRequest('study-a','object-a','opaque-registry',{action:'pdf_resolved',selectedLane:'chemical',note:'PDF supports this candidate.',pdfLocator:{page:4,figureLabel:'Scheme 3'}},actor);",
                "if(JSON.stringify(decision)!==JSON.stringify({study_id:'study-a',object_id:'object-a',registry_digest:'opaque-registry',action:'pdf_resolved',selected_lane:'chemical',note:'PDF supports this candidate.',pdf_locator:{page:4,figure_label:'Scheme 3'},actor_type:'simulated_researcher_agent',actor_label:'simulated_researcher'})) throw new Error(JSON.stringify(decision));",
                "const encoded=JSON.stringify({confirm,completion,decision});",
                "for(const camel of ['studyId','preflightToken','versionToken','registryDigest','objectId','actorType','actorLabel','selectedLane','pdfLocator','figureLabel','moleculeIndex']) if(encoded.includes(camel)) throw new Error(`camel body ${camel}`);",
            ]
        )
    )


def test_work_queues_project_only_researcher_safe_fields_without_default_lane() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',",
                " next_action:{label:'补全缺失 SMILES',description:'从 PDF 定位核对。'},studies:[],",
                " import_preflight:{study_id:'secret-study',preflight_token:'opaque-preflight',status:'ready_for_confirmation',page_count:6,backend:'pipeline',version:'3.4.4',file_kinds:['layout','markdown','molecule_info'],molecule_count:125,gaps:['1 个字段待补全'],actor_label:'模拟研究者',updated_at:'2026-07-30T09:10:00Z'},",
                " completion_queue:[{study_id:'secret-study',molecule_index:7,version_token:'opaque-version',field:'smiles_expanded',page:3,bbox_normalized:[0.1,0.2,0.3,0.4],pdf_page_url:'/api/project/case/pdf/study?page=3',actor_label:'模拟研究者',updated_at:'2026-07-30T09:11:00Z'}],",
                " reconciliation_items:[{study_id:'secret-study',object_id:'secret-object',registry_digest:'opaque-registry',kind:'molecule',status:'conflict',generic_candidate:'compound 3a',chemical_candidate:'compound 3b',page:4,pdf_page_url:'/api/project/case/pdf/study?page=4',actor_label:'模拟研究者',updated_at:'2026-07-30T09:12:00Z'}]});",
                "if(model.importPreflight.statusLabel!=='预检完成，等待确认导入' || !model.importPreflight.confirmAvailable || model.importPreflight.pageLabel!=='6 页') throw new Error(JSON.stringify(model.importPreflight));",
                "const completion=model.completionQueue[0];",
                "if(completion.field!=='smiles_expanded' || completion.fieldLabel!=='展开 SMILES' || completion.locatorLabel!=='第 3 页 · 页面区域已定位') throw new Error(JSON.stringify(completion));",
                "const item=model.reconciliationItems[0];",
                "if(item.statusLabel!=='两层候选冲突' || item.selectedLane!==null || item.genericCandidate!=='compound 3a' || item.chemicalCandidate!=='compound 3b') throw new Error(JSON.stringify(item));",
                "if(JSON.stringify(item.allowedActions)!==JSON.stringify(['pdf_resolved','pdf_locator_only','reject_both'])) throw new Error(JSON.stringify(item));",
                "const encoded=JSON.stringify(model).toLowerCase();",
                "for(const forbidden of ['secret-study','secret-object','opaque-preflight','opaque-version','opaque-registry']) if(encoded.includes(forbidden)) throw new Error(`leaked ${forbidden}`);",
            ]
        )
    )


def test_public_renderer_loader_and_dialog_keyboard_contract_are_present() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "for(const name of ['projectionModel','importPreflightRequest','importConfirmRequest','completionBatchRequest','reconciliationRequest','render','load']) if(typeof ui[name]!=='function') throw new Error(`missing ${name}`);",
            ]
        )
    )

    script = DUAL_SCRIPT.read_text(encoding="utf-8")
    for required in (
        'event.key === "Tab"',
        'event.key === "Escape"',
        "event.shiftKey",
        "returnFocus.focus()",
        'setAttribute("aria-live", "polite")',
        "retryable",
        "onRetry",
    ):
        assert required in script

    lowered = script.lower()
    for forbidden in (
        "archive_sha256",
        "source_pdf_sha256",
        "state_digest",
        "molblock",
        "chemical-paper-zip-only",
        "innerhtml",
        "credit",
    ):
        assert forbidden not in lowered


def test_workspace_css_defines_desktop_tablet_mobile_and_visible_focus() -> None:
    css = DUAL_STYLE.read_text(encoding="utf-8")
    assert "grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr) minmax(0, 1fr)" in css
    assert "@media (max-width: 1100px)" in css
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in css
    assert "@media (max-width: 640px)" in css
    assert "grid-template-columns: 1fr" in css
    assert ":focus-visible" in css
    assert "overflow-wrap: anywhere" in css


def test_dashboard_wires_real_dual_parse_load_retry_and_mutation_handlers() -> None:
    html = REVIEW_HTML.read_text(encoding="utf-8")
    for required in (
        "ReviewDualParseUI.load(requestedProjectId",
        "ReviewDualParseUI.render(",
        "onImportPreflight",
        "onImportConfirm",
        "onCompletionSave",
        "onReconciliationSave",
        "onRetry",
        "submitDualParseMutation('preflight'",
        "submitDualParseMutation('confirm'",
        "submitDualParseMutation('completion'",
        "submitDualParseMutation('reconciliation'",
        "application/zip",
        "chemical-completion",
        "parse-reconciliation",
    ):
        assert required in html

    assert "setInterval(submitDualParseMutation" not in html
    assert "setTimeout(submitDualParseMutation" not in html


def test_projection_redacts_raw_structure_json_paths_and_private_urls() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'failed',failure_message:'/mnt/c/private/task failed',retryable:true,studies:[],",
                " reconciliation_items:[{study_id:'s',object_id:'o',registry_digest:'r',status:'conflict',generic_candidate:'{\"secret\":true}',chemical_candidate:'candidate V2000\\nM  END',pdf_page_url:'https://private.example/task?session=secret'}]});",
                "if(model.failureMessage!=='') throw new Error(JSON.stringify(model));",
                "const item=model.reconciliationItems[0];",
                "if(item.genericCandidate!=='Generic 候选未提供' || item.chemicalCandidate!=='Chemical 候选未提供' || item.pdfPageUrl!=='') throw new Error(JSON.stringify(item));",
                "const encoded=JSON.stringify(model);",
                "for(const forbidden of ['/mnt/','secret','V2000','M  END','private.example']) if(encoded.includes(forbidden)) throw new Error(`leaked ${forbidden}`);",
            ]
        )
    )


def test_loader_uses_dual_parse_route_and_returns_retryable_failure_state() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "(async()=>{",
                " let seen='';",
                " const ready=await ui.load('case/a',async url=>{seen=url;return {ok:true,json:async()=>({schema_version:'dual-parse-projection.v1',status:'ready',next_action:{label:'继续核对',description:'只显示一项。'},studies:[]})}});",
                " if(seen!=='/api/project/case%2Fa/dual-parse' || ready.status!=='ready') throw new Error(JSON.stringify({seen,ready}));",
                " const failed=await ui.load('case/a',async()=>({ok:false,status:503,json:async()=>({})}));",
                " if(failed.status!=='failed' || failed.retryable!==true || !failed.failureMessage.includes('权威状态未更改')) throw new Error(JSON.stringify(failed));",
                "})().catch(error=>{console.error(error);process.exit(1)});",
            ]
        )
    )
