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
FRESH_V2_FIXTURE = ROOT / "tests" / "fixtures" / "dashboard" / "fresh_v2_authoritative_surface.json"


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
                "  pdf_status:'verified',generic_parse_status:'current',paper_evidence_status:'blocked',",
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


def test_fresh_v2_fixture_renders_explicit_pdf_generic_and_fail_closed_later_gates() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    fixture_path = json.dumps(str(FRESH_V2_FIXTURE))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                f"const fixture=require({fixture_path});",
                "class Node {",
                " constructor(tag,id=''){this.tag=tag;this.id=id;this.children=[];this.attributes={};this.className='';this.textContent='';}",
                " append(...nodes){this.children.push(...nodes);}",
                " replaceChildren(...nodes){this.children=[...nodes];}",
                " setAttribute(name,value){this.attributes[name]=String(value);if(name==='id')this.id=String(value);}",
                " addEventListener(){}",
                " querySelector(selector){",
                "  const id=selector.startsWith('#')?selector.slice(1):'';",
                "  if(id && this.id===id)return this;",
                "  for(const child of this.children){if(child && typeof child.querySelector==='function'){const found=child.querySelector(selector);if(found)return found;}}",
                "  return null;",
                " }",
                "}",
                "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const node=new Node('#text');node.textContent=String(value);return node;},body:new Node('body')};",
                "const mount=new Node('main');",
                "for(const id of ['dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list']) mount.append(new Node('section',id));",
                "const model=ui.projectionModel(fixture.dual_parse);",
                "ui.render(document,mount,model,{});",
                "const visibleText=node=>[node.textContent,...node.children.map(visibleText)].join(' ');",
                "const rendered=visibleText(mount);",
                "for(const expected of ['完成 11 项 Generic Parse 决定','PDF 已核验','Generic Parse 当前有效','Chemical Paper 待确认导入','Chemical Completion 尚未开放','Reconciliation 尚未开放','Paper Evidence 尚不可用']) if(!rendered.includes(expected)) throw new Error(`missing ${expected}: ${rendered}`);",
                "for(const expected of ['PDF 已核验','Generic Parse 当前有效','Chemical Paper 待确认导入','Chemical Completion 尚未开放','Reconciliation 尚未开放','Paper Evidence 尚不可用']) if(rendered.split(expected).length-1!==3) throw new Error(`wrong count ${expected}: ${rendered}`);",
                "for(const forbidden of ['PDF 核验已失效','Generic Parse 待启动','Evidence 可用','internal-study-one','internal-study-two','internal-study-three']) if(rendered.includes(forbidden)) throw new Error(`leaked or false ${forbidden}: ${rendered}`);",
            ]
        )
    )


def test_fresh_v2_fixture_declares_only_the_new_flat_authority_contract() -> None:
    payload = json.loads(FRESH_V2_FIXTURE.read_text(encoding="utf-8"))["dual_parse"]
    assert payload["schema_version"] == "dual-parse-projection.v1"
    assert payload["studies"]
    for study in payload["studies"]:
        assert {
            "pdf_status",
            "generic_parse_status",
            "paper_evidence_status",
        }.issubset(study)
        assert not {"pdf", "generic_parse", "evidence", "evidence_status"}.intersection(study)


def test_absent_pdf_generic_states_remain_unknown_and_never_infer_evidence() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const absent=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[{source_tier:'core',chemical_import_status:'missing',completion_status:'blocked',reconciliation_status:'blocked'}]}).studies[0];",
                "if(absent.pdfLabel!=='PDF 状态未知' || absent.genericLabel!=='Generic Parse 状态未知' || absent.evidenceLabel!=='Paper Evidence 状态未知') throw new Error(JSON.stringify(absent));",
                "const genericOnly=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[{source_tier:'core',generic_parse_status:'current',chemical_import_status:'current',completion_status:'current',reconciliation_status:'current'}]}).studies[0];",
                "if(genericOnly.pdfLabel!=='PDF 状态未知' || genericOnly.evidenceLabel!=='Paper Evidence 状态未知') throw new Error(JSON.stringify(genericOnly));",
                "const approved=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[{source_tier:'core',pdf_status:'verified',generic_parse_status:'current',chemical_import_status:'current',completion_status:'current',reconciliation_status:'current',paper_evidence_status:'available'}]}).studies[0];",
                "if(approved.evidenceLabel!=='Paper Evidence 可用') throw new Error(JSON.stringify(approved));",
                "const conflict=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[{source_tier:'core',pdf_status:'verified',generic_parse_status:'current',paper_evidence_status:'blocked',pdf:{status:'failed'},generic_parse:{status:'stale'},evidence:{status:'available'},evidence_status:'available'}]}).studies[0];",
                "if(conflict.pdfLabel!=='PDF 已核验' || conflict.genericLabel!=='Generic Parse 当前有效' || conflict.evidenceLabel!=='Paper Evidence 尚不可用') throw new Error(JSON.stringify(conflict));",
                "const legacyOnly=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[{source_tier:'core',pdf:{status:'verified'},generic_parse:{status:'current'},evidence:{status:'available'},evidence_status:'available'}]}).studies[0];",
                "if(legacyOnly.pdfLabel!=='PDF 状态未知' || legacyOnly.genericLabel!=='Generic Parse 状态未知' || legacyOnly.evidenceLabel!=='Paper Evidence 状态未知') throw new Error(JSON.stringify(legacyOnly));",
            ]
        )
    )


def test_needs_review_chemical_import_renders_safe_confirmed_facts_without_opening_gates() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const rows=[[6,125],[11,109],[11,75]].map(([page_count,molecule_count],index)=>({",
                " source_tier:'core',pdf_status:'verified',generic_parse_status:'current',",
                " chemical_import_status:'needs_review',completion_status:'blocked',reconciliation_status:'blocked',paper_evidence_status:'blocked',",
                " missing_name_count:index+1,missing_smiles_expanded_count:1,missing_smiles_unexpanded_count:1,",
                " page_count,molecule_count,backend:'pipeline',version:'3.4.4',imported_at:`2026-07-30T08:0${index}:00Z`,",
                " reaction_data_status:'unavailable_not_provided'}));",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:rows});",
                "class Node {",
                " constructor(tag,id=''){this.tag=tag;this.id=id;this.children=[];this.attributes={};this.className='';this.textContent='';}",
                " append(...nodes){this.children.push(...nodes);}",
                " replaceChildren(...nodes){this.children=[...nodes];}",
                " setAttribute(name,value){this.attributes[name]=String(value);if(name==='id')this.id=String(value);}",
                " addEventListener(){}",
                " querySelector(selector){const id=selector.startsWith('#')?selector.slice(1):'';if(id&&this.id===id)return this;for(const child of this.children){if(child&&typeof child.querySelector==='function'){const found=child.querySelector(selector);if(found)return found;}}return null;}",
                "}",
                "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const node=new Node('#text');node.textContent=String(value);return node;},body:new Node('body')};",
                "const mount=new Node('main');for(const id of ['dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list'])mount.append(new Node('section',id));",
                "ui.render(document,mount,model,{});",
                "const visibleText=node=>[node.textContent,...node.children.map(visibleText)].join(' ');const rendered=visibleText(mount);",
                "for(const expected of ['Chemical import 已导入，待研究者补全/复核','6 页','125 个分子条目','11 页','109 个分子条目','75 个分子条目','pipeline · 3.4.4','反应数据：导出包未提供','导入时间：2026-07-30T08:00:00Z','Chemical Completion 尚未开放','Reconciliation 尚未开放','Paper Evidence 尚不可用'])if(!rendered.includes(expected))throw new Error(`missing ${expected}: ${rendered}`);",
                "for(const blocked of ['Chemical Completion 尚未开放','Reconciliation 尚未开放','Paper Evidence 尚不可用'])if(rendered.split(blocked).length-1!==3)throw new Error(`wrong blocked count ${blocked}: ${rendered}`);",
                "if(rendered.includes('Chemical import 状态未知')||rendered.includes('Chemical import 当前有效'))throw new Error(rendered);",
                "const unknown=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[{chemical_import_status:'unknown',chemical:{status:'current'},page_count:99,molecule_count:99,backend:'private',version:'9'}]}).studies[0];",
                "const stale=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[{chemical_import_status:'stale',chemical:{status:'current'},page_count:99,molecule_count:99,backend:'private',version:'9'}]}).studies[0];",
                "if(unknown.chemicalLabel!=='Chemical import 状态未知'||unknown.chemicalFacts.length!==0)throw new Error(JSON.stringify(unknown));",
                "if(stale.chemicalLabel!=='Chemical import 已过期'||stale.chemicalFacts.length!==0)throw new Error(JSON.stringify(stale));",
            ]
        )
    )


def test_authoritative_availability_separates_sources_from_completed_evidence_review() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    fixture_path = json.dumps(str(FRESH_V2_FIXTURE))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                f"const fixture=require({fixture_path});",
                "const availability=ui.availabilityModel({sources:fixture.sources,dualParse:fixture.dual_parse,includedStudies:fixture.cockpit.metrics.included_studies,reviewedEvidenceStudies:fixture.cockpit.metrics.reviewed_studies});",
                "if(JSON.stringify(availability)!==JSON.stringify({mainFullText:{available:3,total:3},genericSource:{available:3,total:3},reviewedEvidence:{available:0,total:3}})) throw new Error(JSON.stringify(availability));",
                "const unknown=ui.availabilityModel({sources:{sources:[]},dualParse:{schema_version:'other'},includedStudies:3});",
                "if(unknown.mainFullText.available!==null || unknown.genericSource.available!==null || unknown.reviewedEvidence.available!==null) throw new Error(JSON.stringify(unknown));",
                "const divergent=ui.availabilityModel({sources:fixture.sources,dualParse:{schema_version:'dual-parse-projection.v1',status:'ready',summary:{core_studies:0,generic_current:0},studies:[{source_tier:'core'}]},includedStudies:3});",
                "if(divergent.genericSource.available!==null || divergent.genericSource.total!==3) throw new Error(JSON.stringify(divergent));",
                "const partial=ui.availabilityModel({sources:{sources:[{study_id:'a',role:'MAIN',status:'已获得'},{study_id:'a',role:'MAIN',status:'已获得'},{study_id:'b',role:'MAIN',status:'已获得'},{study_id:'c',role:'MAIN',status:'已获得'}]},dualParse:{schema_version:'other'},includedStudies:4,reviewedEvidenceStudies:1});",
                "if(partial.mainFullText.available!==3 || partial.mainFullText.total!==4) throw new Error(JSON.stringify(partial));",
            ]
        )
    )


def test_availability_fails_closed_for_stale_conflicting_and_overflow_counts() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    fixture_path = json.dumps(str(FRESH_V2_FIXTURE))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                f"const fixture=require({fixture_path});",
                "const clone=value=>JSON.parse(JSON.stringify(value));",
                "for(const status of ['stale','failed']){",
                " const dual=clone(fixture.dual_parse);dual.status=status;",
                " const availability=ui.availabilityModel({dualParse:dual,includedStudies:3});",
                " if(availability.genericSource.available!==null || availability.genericSource.total!==3) throw new Error(JSON.stringify({status,availability}));",
                "}",
                "const summaryConflict=clone(fixture.dual_parse);summaryConflict.studies[0].generic_parse_status='stale';",
                "const conflicting=ui.availabilityModel({dualParse:summaryConflict,includedStudies:3});",
                "if(conflicting.genericSource.available!==null || conflicting.genericSource.total!==3) throw new Error(JSON.stringify(conflicting));",
                "summaryConflict.summary.generic_current=2;",
                "const consistent=ui.availabilityModel({dualParse:summaryConflict,includedStudies:3});",
                "if(consistent.genericSource.available!==2 || consistent.genericSource.total!==3) throw new Error(JSON.stringify(consistent));",
                "const reviewedOverflow=ui.availabilityModel({includedStudies:3,reviewedEvidenceStudies:4});",
                "if(reviewedOverflow.reviewedEvidence.available!==null || reviewedOverflow.reviewedEvidence.total!==3) throw new Error(JSON.stringify(reviewedOverflow));",
                "const coreOverflow=clone(fixture.dual_parse);coreOverflow.summary={core_studies:4,generic_current:4};coreOverflow.studies.push(clone(coreOverflow.studies[0]));",
                "const overflowing=ui.availabilityModel({dualParse:coreOverflow,includedStudies:3});",
                "if(overflowing.genericSource.available!==null || overflowing.genericSource.total!==3) throw new Error(JSON.stringify(overflowing));",
                "const missingDenominator=ui.availabilityModel({dualParse:fixture.dual_parse,reviewedEvidenceStudies:3});",
                "if(missingDenominator.genericSource.available!==null || missingDenominator.reviewedEvidence.available!==null) throw new Error(JSON.stringify(missingDenominator));",
            ]
        )
    )


def test_rejected_evidence_decision_counts_as_reviewed_without_claiming_approval() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const rejectedReview=ui.availabilityModel({includedStudies:1,reviewedEvidenceStudies:1});",
                "if(rejectedReview.reviewedEvidence.available!==1 || 'approvedEvidence' in rejectedReview) throw new Error(JSON.stringify(rejectedReview));",
            ]
        )
    )


def test_dashboard_wires_distinct_source_and_evidence_availability_copy() -> None:
    html = REVIEW_HTML.read_text(encoding="utf-8")
    for required in (
        "ReviewDualParseUI.availabilityModel(",
        "MAIN 全文可用",
        "Generic Parse source 可用",
        "已完成 Evidence 复核",
    ):
        assert required in html
    assert "已批准 Evidence" not in html
    assert "已批准 Paper Evidence" not in html
    assert "['MAIN 全文覆盖', Number(metrics.full_text_main_coverage) || 0]" not in html


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
                "if(completion.displayLabel!=='分子条目 8' || completion.field!=='smiles_expanded' || completion.fieldLabel!=='展开 SMILES' || completion.locatorLabel!=='第 3 页 · 区域 x 10–30% · y 20–40%') throw new Error(JSON.stringify(completion));",
                "const item=model.reconciliationItems[0];",
                "if(item.statusLabel!=='两层候选冲突' || item.selectedLane!==null || item.genericCandidate!=='compound 3a' || item.chemicalCandidate!=='compound 3b') throw new Error(JSON.stringify(item));",
                "if(JSON.stringify(item.allowedActions)!==JSON.stringify(['pdf_resolved','pdf_locator_only','reject_both'])) throw new Error(JSON.stringify(item));",
                "const encoded=JSON.stringify(model).toLowerCase();",
                "for(const forbidden of ['secret-study','secret-object','opaque-preflight','opaque-version','opaque-registry']) if(encoded.includes(forbidden)) throw new Error(`leaked ${forbidden}`);",
            ]
        )
    )


def test_completion_rows_expose_source_order_and_distinct_same_page_regions() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[],completion_queue:[",
                " {study_id:'secret-study',molecule_index:7,molecule_id:'raw-molecule-a',version_token:'opaque-version',field:'mol_idt',page:4,bbox_normalized:[0.1,0.2,0.3,0.4],pdf_page_url:'/api/project/case/pdf/study?page=4',mol_block:'raw V2000 M  END',digest:'a'.repeat(64)},",
                " {study_id:'secret-study',molecule_index:12,molecule_id:'raw-molecule-b',version_token:'opaque-version',field:'mol_idt',page:4,bbox_normalized:[0.55,0.1,0.8,0.25],pdf_page_url:'/api/project/case/pdf/study?page=4'}]});",
                "const [first,second]=model.completionQueue;",
                "if(first.displayLabel!=='分子条目 8' || second.displayLabel!=='分子条目 13') throw new Error(JSON.stringify(model.completionQueue));",
                "if(first.locatorLabel!=='第 4 页 · 区域 x 10–30% · y 20–40%' || second.locatorLabel!=='第 4 页 · 区域 x 55–80% · y 10–25%') throw new Error(JSON.stringify(model.completionQueue));",
                "if(JSON.stringify(first.normalizedBbox)!==JSON.stringify([0.1,0.2,0.3,0.4]) || first.locatorLabel===second.locatorLabel) throw new Error(JSON.stringify(model.completionQueue));",
                "const encoded=JSON.stringify(model).toLowerCase();",
                "for(const forbidden of ['secret-study','raw-molecule','opaque-version','mol_block','v2000','digest','aaaaaaaa']) if(encoded.includes(forbidden)) throw new Error(`leaked ${forbidden}`);",
            ]
        )
    )


def test_completion_renderer_separates_visible_locator_from_truthful_source_link() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "class Node {",
                " constructor(tag,id=''){this.tag=tag;this.id=id;this.children=[];this.attributes={};this.className='';this.textContent='';this.style={};}",
                " append(...nodes){this.children.push(...nodes);}",
                " replaceChildren(...nodes){this.children=[...nodes];}",
                " setAttribute(name,value){this.attributes[name]=String(value);if(name==='id')this.id=String(value);}",
                " addEventListener(){}",
                " querySelector(selector){const id=selector.startsWith('#')?selector.slice(1):'';if(id&&this.id===id)return this;for(const child of this.children){if(child&&typeof child.querySelector==='function'){const found=child.querySelector(selector);if(found)return found;}}return null;}",
                "}",
                "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const node=new Node('#text');node.textContent=String(value);return node;},body:new Node('body')};",
                "const mount=new Node('main');for(const id of ['dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list'])mount.append(new Node('section',id));",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[],completion_queue:[",
                " {study_id:'secret-study',molecule_index:7,version_token:'opaque-version',field:'mol_idt',page:4,bbox_normalized:[0.1,0.2,0.3,0.4],pdf_page_url:'/api/project/case/pdf/study?page=4'},",
                " {study_id:'secret-study',molecule_index:12,version_token:'opaque-version',field:'smiles_expanded',page:4,bbox_normalized:[0.55,0.1,0.8,0.25],pdf_page_url:'/api/project/case/pdf/study?page=4'}]});",
                "ui.render(document,mount,model,{});",
                "const all=[];const visit=node=>{all.push(node);for(const child of node.children||[])if(child&&typeof child==='object')visit(child);};visit(mount);",
                "const locators=all.filter(node=>node.className==='dual-completion-locator');",
                "const overlays=all.filter(node=>node.className==='dual-completion-bbox');",
                "const sourceLinks=all.filter(node=>node.className==='dual-completion-source-link');",
                "if(locators.length!==2 || overlays.length!==2 || sourceLinks.length!==2) throw new Error(JSON.stringify({locators:locators.length,overlays:overlays.length,sourceLinks:sourceLinks.length}));",
                "for(const locator of locators){if(locator.tag!=='figure' || locator.href || locator.target) throw new Error(JSON.stringify(locator));}",
                "for(const link of sourceLinks){if(link.tag!=='a' || link.href!=='/api/project/case/pdf/study?page=4' || link.target!=='_blank' || link.textContent!=='另开原始整页（不含红框） ↗' || JSON.stringify(link).includes('高亮')) throw new Error(JSON.stringify(link));}",
                "const firstStyle=JSON.stringify(overlays[0].style);const secondStyle=JSON.stringify(overlays[1].style);",
                "if(firstStyle===secondStyle || overlays[0].style.left!=='10%' || overlays[0].style.top!=='20%' || overlays[0].style.width!=='20%' || overlays[0].style.height!=='20%') throw new Error(JSON.stringify(overlays.map(node=>node.style)));",
                "const visible=node=>[node.textContent,...(node.children||[]).map(visible)].join(' ');const rendered=visible(mount);",
                "for(const expected of ['分子条目 8','分子条目 13','区域 x 10–30% · y 20–40%','区域 x 55–80% · y 10–25%','红框为当前结构区域','另开原始整页（不含红框）'])if(!rendered.includes(expected))throw new Error(rendered);",
                "if(rendered.includes('打开带高亮定位'))throw new Error(rendered);",
                "for(const forbidden of ['secret-study','opaque-version','molecule_index'])if(rendered.includes(forbidden))throw new Error(`leaked ${forbidden}`);",
            ]
        )
    )

    css = DUAL_STYLE.read_text(encoding="utf-8")
    assert ".dual-completion-locator" in css
    assert ".dual-completion-bbox" in css
    assert "width: min(100%, 420px)" in css
    assert ".dual-completion-source-link:focus-visible" in css
    assert ".dual-completion-crop summary:focus-visible" in css


def test_completion_crop_is_keyboard_triggered_lazy_and_bounded_for_94_rows() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "class Node {",
                " constructor(tag,id=''){",
                "  this.tag=tag;this.id=id;this.children=[];this.attributes={};this.className='';this.textContent='';this.style={};this.listeners={};this.open=false;",
                "  if(tag==='img'){this.naturalWidth=1000;this.naturalHeight=2000;this.complete=true;}",
                "  if(tag==='canvas'){this.width=300;this.height=150;this.context={draws:[],imageSmoothingEnabled:false,drawImage(...args){this.draws.push(args);}};}",
                " }",
                " append(...nodes){this.children.push(...nodes);}",
                " replaceChildren(...nodes){this.children=[...nodes];}",
                " setAttribute(name,value){this.attributes[name]=String(value);if(name==='id')this.id=String(value);}",
                " addEventListener(name,handler){if(!this.listeners[name])this.listeners[name]=[];this.listeners[name].push(handler);}",
                " dispatch(name){for(const handler of this.listeners[name]||[])handler({currentTarget:this});}",
                " getContext(kind){return this.tag==='canvas'&&kind==='2d'?this.context:null;}",
                " querySelector(selector){const id=selector.startsWith('#')?selector.slice(1):'';if(id&&this.id===id)return this;for(const child of this.children){if(child&&typeof child.querySelector==='function'){const found=child.querySelector(selector);if(found)return found;}}return null;}",
                "}",
                "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const node=new Node('#text');node.textContent=String(value);return node;},body:new Node('body')};",
                "const mount=new Node('main');for(const id of ['dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list'])mount.append(new Node('section',id));",
                "const completion_queue=Array.from({length:94},(_,index)=>({study_id:'study',molecule_index:index,version_token:'version',field:'mol_idt',page:4,bbox_normalized:[0.1,0.2,0.3,0.4],pdf_page_url:'/api/project/case/pdf/study?page=4'}));",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[],completion_queue});",
                "ui.render(document,mount,model,{});",
                "const all=[];const visit=node=>{all.push(node);for(const child of node.children||[])if(child&&typeof child==='object')visit(child);};visit(mount);",
                "const images=all.filter(node=>node.className==='dual-completion-page-image');",
                "const crops=all.filter(node=>node.className==='dual-completion-crop-canvas');",
                "const details=all.filter(node=>node.className==='dual-completion-crop');",
                "const summaries=all.filter(node=>node.tag==='summary');",
                "if(images.length!==94 || crops.length!==94 || details.length!==94 || summaries.length!==94) throw new Error(JSON.stringify({images:images.length,crops:crops.length,details:details.length,summaries:summaries.length}));",
                "if(images.some(image=>image.loading!=='lazy' || image.decoding!=='async') || crops.some(canvas=>canvas.width!==1 || canvas.height!==1)) throw new Error('eager locator allocation');",
                "if(crops.some(canvas=>canvas.context.draws.length)) throw new Error('crop drawn before researcher opens it');",
                "details[0].open=true;details[0].dispatch('toggle');",
                "if(crops[0].context.draws.length!==1 || crops[0].width<2 || crops[0].height<2 || crops[0].width>480 || crops[0].height>320) throw new Error(JSON.stringify({width:crops[0].width,height:crops[0].height,draws:crops[0].context.draws.length}));",
                "if(crops.slice(1).some(canvas=>canvas.context.draws.length)) throw new Error('opening one crop drew another row');",
                "const draw=crops[0].context.draws[0];if(draw[1]!==100 || draw[2]!==400 || draw[3]!==200 || draw[4]!==400) throw new Error(JSON.stringify(draw));",
                "details[0].open=false;details[0].dispatch('toggle');details[0].open=true;details[0].dispatch('toggle');if(crops[0].context.draws.length!==1) throw new Error('crop redrawn');",
            ]
        )
    )


def test_completion_crop_failed_image_finishes_with_truthful_fallback() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "class Node {",
                " constructor(tag,id=''){",
                "  this.tag=tag;this.id=id;this.children=[];this.attributes={};this.className='';this.textContent='';this.style={};this.listeners={};this.open=false;",
                "  if(tag==='img'){this.naturalWidth=0;this.naturalHeight=0;this.complete=true;}",
                "  if(tag==='canvas'){this.width=300;this.height=150;this.context={draws:[],drawImage(...args){this.draws.push(args);}};}",
                " }",
                " append(...nodes){this.children.push(...nodes);}",
                " replaceChildren(...nodes){this.children=[...nodes];}",
                " setAttribute(name,value){this.attributes[name]=String(value);if(name==='id')this.id=String(value);}",
                " addEventListener(name,handler){if(!this.listeners[name])this.listeners[name]=[];this.listeners[name].push(handler);}",
                " dispatch(name){for(const handler of this.listeners[name]||[])handler({currentTarget:this});}",
                " getContext(kind){return this.tag==='canvas'&&kind==='2d'?this.context:null;}",
                " querySelector(selector){const id=selector.startsWith('#')?selector.slice(1):'';if(id&&this.id===id)return this;for(const child of this.children){if(child&&typeof child.querySelector==='function'){const found=child.querySelector(selector);if(found)return found;}}return null;}",
                "}",
                "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const node=new Node('#text');node.textContent=String(value);return node;},body:new Node('body')};",
                "const mount=new Node('main');for(const id of ['dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list'])mount.append(new Node('section',id));",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[],completion_queue:[{study_id:'study',molecule_index:0,version_token:'version',field:'mol_idt',page:4,bbox_normalized:[0.1,0.2,0.3,0.4],pdf_page_url:'/api/project/case/pdf/study?page=4'}]});",
                "ui.render(document,mount,model,{});",
                "const all=[];const visit=node=>{all.push(node);for(const child of node.children||[])if(child&&typeof child==='object')visit(child);};visit(mount);",
                "const image=all.find(node=>node.className==='dual-completion-page-image');const crop=all.find(node=>node.className==='dual-completion-crop');const canvas=all.find(node=>node.className==='dual-completion-crop-canvas');const status=all.find(node=>node.className==='dual-completion-crop-status');",
                "crop.open=true;crop.dispatch('toggle');",
                "const fallback='局部放大不可用；请使用上方红框上下文或另开原始整页核对。';",
                "if(status.textContent!==fallback || status.textContent.includes('重试') || status.textContent.includes('正在生成') || canvas.context.draws.length!==0) throw new Error(JSON.stringify({status:status.textContent,draws:canvas.context.draws.length}));",
                "if((image.listeners.load||[]).length || (image.listeners.error||[]).length) throw new Error('registered already-ended image events');",
                "status.textContent='sentinel';crop.open=false;crop.dispatch('toggle');crop.open=true;crop.dispatch('toggle');",
                "if(status.textContent!==fallback || canvas.context.draws.length!==0) throw new Error(JSON.stringify({status:status.textContent,draws:canvas.context.draws.length}));",
            ]
        )
    )


def test_completion_rejects_zero_area_bbox_without_claiming_or_drawing_location() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "class Node {",
                " constructor(tag,id=''){this.tag=tag;this.id=id;this.children=[];this.attributes={};this.className='';this.textContent='';this.style={};}",
                " append(...nodes){this.children.push(...nodes);}",
                " replaceChildren(...nodes){this.children=[...nodes];}",
                " setAttribute(name,value){this.attributes[name]=String(value);if(name==='id')this.id=String(value);}",
                " addEventListener(){}",
                " querySelector(selector){const id=selector.startsWith('#')?selector.slice(1):'';if(id&&this.id===id)return this;for(const child of this.children){if(child&&typeof child.querySelector==='function'){const found=child.querySelector(selector);if(found)return found;}}return null;}",
                "}",
                "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const node=new Node('#text');node.textContent=String(value);return node;},body:new Node('body')};",
                "const mount=new Node('main');for(const id of ['dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list'])mount.append(new Node('section',id));",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v1',status:'ready',studies:[],completion_queue:[",
                " {study_id:'study',molecule_index:1,version_token:'version',field:'mol_idt',page:5,bbox_normalized:[0.2,0.3,0.2,0.6],pdf_page_url:'/api/project/case/pdf/study?page=5'},",
                " {study_id:'study',molecule_index:2,version_token:'version',field:'smiles_expanded',page:5,bbox_normalized:[0.2,0.3,0.6,0.3],pdf_page_url:'/api/project/case/pdf/study?page=5'}]});",
                "for(const row of model.completionQueue){if('normalizedBbox' in row || row.locatorLabel!=='第 5 页 · 页面区域未提供') throw new Error(JSON.stringify(row));}",
                "ui.render(document,mount,model,{});",
                "const all=[];const visit=node=>{all.push(node);for(const child of node.children||[])if(child&&typeof child==='object')visit(child);};visit(mount);",
                "if(all.some(node=>node.className==='dual-completion-bbox' || node.className==='dual-completion-locator')) throw new Error('zero-area locator rendered');",
                "const rendered=all.map(node=>node.textContent).join(' ');",
                "if(rendered.includes('区域 x') || rendered.includes('带高亮定位')) throw new Error(rendered);",
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
