from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "view" / "assets" / "dashboard"


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


def test_dashboard_exposes_chemical_review_without_removing_original_pdf_intake() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    parser = _DashboardParser()
    parser.feed(html)

    assert parser.attributes["chemical-paper-panel"].get("aria-labelledby") == (
        "chemical-paper-heading"
    )
    assert parser.attributes["chemical-paper-message"].get("aria-live") == "polite"
    assert "MinerU Chemical Paper 手工导出" in html
    assert "原始 PDF 仍是科学事实来源" in html
    assert "通用 MinerU" not in html
    assert parser.attributes["source-archive-input"].get("accept") == ".zip,application/zip"
    assert "拖入一个 PDF ZIP" in html
    assert "/source-archive" in html
    assert "chemical-paper-import" not in html
    assert "/assets/dashboard/review-chemical-paper.js" in html
    assert "/assets/dashboard/review-chemical-paper.css" in html


def test_projection_v1_model_preserves_unknown_and_reaction_absence_semantics() -> None:
    module_path = json.dumps(str(DASHBOARD / "review-chemical-paper.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.buildChemicalPaperModel({",
                " schema_version:'chemical-paper-projection.v1',route:'chemical-paper-zip-only',project_status:'needs_review',",
                " summary:{studies:3,imported:1,molecules:125,unresolved_fields:32,reaction_data_status:'unavailable_not_provided'},",
                " studies:[{study_id:'scholarly-secret',status:'needs_review',pdf_binding_status:'bound',backend:'pipeline',version:'3.4.4',imported_at:'2026-07-30T08:00:00Z',",
                "   file_kinds:['layout','markdown','molecule_info'],page_count:6,molecule_count:125,reaction_data_status:'unavailable_not_provided',",
                "   missing_field_counts:{mol_idt:30,smiles_expanded:1,smiles_unexpanded:1},gaps:['32 个候选字段待核对'],",
                "   molecules:[{molecule_index:7,page:3,bbox_normalized:[0.1,0.2,0.3,0.4],molblock_available:true,",
                "     mol_idt:null,smiles_expanded:null,smiles_unexpanded:'C=C',missing_fields:['mol_idt','smiles_expanded'],",
                "     candidate_elements:[{symbol:'C',count:2},{symbol:'H',count:4}],element_review_state:'not_reviewed',",
                "     pdf_page_url:'/api/project/case/pdf/study?page=3',version_token:'opaque-v1',",
                "     history:[{kind:'field_correction',field:'smiles_unexpanded',prior_value:null,value:'C=C',actor_label:'李研究员',recorded_at:'2026-07-30T08:10:00Z',reason:'核对原始 PDF'},",
                "       {kind:'element_review',prior_state:'not_reviewed',action:'confirmed',actor_label:'李研究员',recorded_at:'2026-07-30T08:11:00Z',reason:'核对候选元素'}]}]",
                " },{study_id:'second-secret',status:'missing',pdf_binding_status:'missing',backend:null,version:null,imported_at:null,file_kinds:[],page_count:null,molecule_count:null,reaction_data_status:'unavailable_not_provided',missing_field_counts:null,gaps:['尚未导入'],molecules:[]}],",
                " path:'/private/import',sha256:'a'.repeat(64),raw_json:{secret:true},credits:{measured:9}",
                "});",
                "if(model.route!=='chemical-paper-zip-only' || model.projectStatus!=='needs_review') throw new Error(JSON.stringify(model));",
                "if(model.summary.reactionLabel!=='反应数据：导出包未提供') throw new Error(JSON.stringify(model));",
                "const study=model.studies[0];",
                "if(study.backendLabel!=='pipeline · 3.4.4' || study.pdfBindingLabel!=='已绑定原始 PDF') throw new Error(JSON.stringify(study));",
                "if(study.missingFieldLabel!=='32 个候选字段待核对') throw new Error(JSON.stringify(study));",
                "const molecule=study.molecules[0];",
                "if(molecule.fields.molIdt.label!=='待补充' || molecule.fields.smilesUnexpanded.label!=='C=C') throw new Error(JSON.stringify(molecule));",
                "if(molecule.elementReview.label!=='候选元素尚未审查' || molecule.candidateElements.length!==2) throw new Error(JSON.stringify(molecule));",
                "if(molecule.locatorLabel!=='第 3 页 · 页面区域已定位') throw new Error(JSON.stringify(molecule));",
                "if(molecule.history[1].prior!=='候选元素尚未审查' || molecule.history[1].current!=='候选元素已确认') throw new Error(JSON.stringify(molecule.history));",
                "if(model.studies[1].moleculeCountLabel!=='分子条目数未提供') throw new Error(JSON.stringify(model.studies[1]));",
                "const encoded=JSON.stringify(model);",
                "for(const secret of ['/private/','sha256','raw_json','credits']) if(encoded.includes(secret)) throw new Error(`leaked ${secret}`);",
                "if(encoded.includes('0 个反应') || encoded.includes('科学事实已确认')) throw new Error(encoded);",
            ]
        )
    )


def test_projection_model_fails_closed_on_wrong_schema_or_route() -> None:
    module_path = json.dumps(str(DASHBOARD / "review-chemical-paper.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "for(const payload of [",
                " {schema_version:'internal-v2',route:'chemical-paper-zip-only',project_status:'ready',studies:[{study_id:'private',molecules:[]}]},",
                " {schema_version:'chemical-paper-projection.v1',route:'generic-mineru',project_status:'ready',studies:[{study_id:'private',molecules:[]}]}]",
                " ) { const model=ui.buildChemicalPaperModel(payload); if(model.contractValid!==false || model.studies.length!==0 || model.projectStatus!=='unknown') throw new Error(JSON.stringify(model)); }",
            ]
        )
    )


def test_patch_bodies_match_frozen_v1_and_require_opaque_version_actor_reason() -> None:
    module_path = json.dumps(str(DASHBOARD / "review-chemical-paper.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const field=ui.buildFieldMutation({studyId:'study-a',moleculeIndex:7,field:'mol_idt',value:'compound-7',actorType:'simulated_researcher_agent',actorLabel:'dashboard-playwright-reviewer',reason:'逐项核对原始 PDF',versionToken:'opaque-v1'});",
                "if(JSON.stringify(field)!==JSON.stringify({study_id:'study-a',molecule_index:7,field:'mol_idt',value:'compound-7',reason:'逐项核对原始 PDF',actor_type:'simulated_researcher_agent',actor_label:'dashboard-playwright-reviewer',version_token:'opaque-v1'})) throw new Error(JSON.stringify(field));",
                "const confirmed=ui.buildElementMutation({studyId:'study-a',moleculeIndex:7,action:'confirmed',actorType:'human_researcher',actorLabel:'李研究员',reason:'核对 MolBlock 与原 PDF',versionToken:'opaque-v1'});",
                "if(confirmed.action!=='confirmed' || 'corrected_elements' in confirmed) throw new Error(JSON.stringify(confirmed));",
                "const corrected=ui.buildElementMutation({studyId:'study-a',moleculeIndex:7,action:'corrected',correctedElements:'C: 2, H: 4',actorType:'human_researcher',actorLabel:'李研究员',reason:'按原 PDF 更正',versionToken:'opaque-v1'});",
                "if(corrected.corrected_elements.length!==2 || corrected.corrected_elements[0].symbol!=='C' || corrected.corrected_elements[0].count!==2) throw new Error(JSON.stringify(corrected));",
                "for(const invalid of [",
                " ()=>ui.buildFieldMutation({studyId:'s',moleculeIndex:0,field:'mol_idt',value:'x',actorLabel:'',reason:'r',versionToken:'v'}),",
                " ()=>ui.buildFieldMutation({studyId:'s',moleculeIndex:0,field:'private',value:'x',actorLabel:'a',reason:'r',versionToken:'v'}),",
                " ()=>ui.buildElementMutation({studyId:'s',moleculeIndex:0,action:'confirmed',actorLabel:'a',reason:'',versionToken:'v'}),",
                " ()=>ui.buildElementMutation({studyId:'s',moleculeIndex:0,action:'corrected',correctedElements:'',actorLabel:'a',reason:'r',versionToken:'v'})",
                "]) { let rejected=false; try { invalid(); } catch (_) { rejected=true; } if(!rejected) throw new Error('invalid action accepted'); }",
            ]
        )
    )


def test_mutation_uses_patch_and_surfaces_stale_without_silent_overwrite() -> None:
    module_path = json.dumps(str(DASHBOARD / "review-chemical-paper.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "let options=null,conflicts=0,successes=0;",
                "ui.saveMutation({request:async(_url,value)=>{options=value;return {ok:false,status:409,json:async()=>({ok:false,error_code:'STALE_CHEMICAL_PAPER_STATE',message:'状态已更新'})}},url:'/api/project/case/chemical-paper/field',payload:{field:'mol_idt'},onConflict:()=>{conflicts+=1},onSuccess:()=>{successes+=1}}).then(result=>{",
                " if(options.method!=='PATCH' || result.status!=='conflict' || result.code!=='STALE_CHEMICAL_PAPER_STATE' || conflicts!==1 || successes!==0) throw new Error(JSON.stringify(result));",
                "}).catch(error=>{console.error(error);process.exit(1)});",
            ]
        )
    )


def test_assets_use_only_frozen_routes_and_hide_credits_and_sensitive_terms() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (DASHBOARD / "review.html", *DASHBOARD.glob("review-chemical-paper.*"))
    )
    lowered = sources.lower()
    for forbidden in (
        "credit",
        "实测消耗",
        "预测用量",
        "bound_import_digest",
        "source_pdf_sha256",
        "raw_json",
        "innerhtml",
        "/chemical-paper-import",
        "/chemical-paper-field-correction",
        "/chemical-paper-element-review",
    ):
        assert forbidden not in lowered

    module_path = json.dumps(str(DASHBOARD / "review-chemical-paper.js"))
    _run_node(
        f"const ui=require({module_path});"
        "const value=ui.routes('a/b');"
        "if(JSON.stringify(value)!==JSON.stringify({read:'/api/project/a%2Fb/chemical-paper',field:'/api/project/a%2Fb/chemical-paper/field',elements:'/api/project/a%2Fb/chemical-paper/elements'})) throw new Error(JSON.stringify(value));"
    )


def test_dashboard_loads_projection_and_wires_both_patch_mutations() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    assert "nextChemicalPaperPayload" in html
    assert "chemicalPaperPayload = nextChemicalPaperPayload" in html
    assert html.count("ReviewChemicalPaperUI.routes(") == 2
    assert "ReviewChemicalPaperUI.renderChemicalPaper" in html
    assert html.count("ReviewChemicalPaperUI.saveMutation") == 1
    assert "submitChemicalPaperMutation('field', payload)" in html
    assert "submitChemicalPaperMutation('elements', payload)" in html
    assert "window.reviewDecisionActor" in html
    assert "chemicalPaperPayload.summary" not in html
    assert "chemicalPaperPayload.molecule" not in html
