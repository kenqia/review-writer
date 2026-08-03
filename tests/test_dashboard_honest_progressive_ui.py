from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DUAL_SCRIPT = ROOT / "view" / "assets" / "dashboard" / "review-dual-parse.js"


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


def test_honest_progressive_projection_exposes_counts_coverage_and_uncertainty() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v2',status:'ready',route:'honest_progressive',",
                " honest_progressive:{availability:'available',status:'ready',core_molecule_count:309,coverage_denominator:309,confirmed_count:180,ai_provisional_count:68,blocked_count:61,coverage_ratio:0.8026,coverage_threshold:0.8,uncertainty_statement:'61 个结构仍无法唯一确定',gap_registry:[{study_id:'study-a',molecule_index:4,status:'BLOCKED',gap_reason:'结构图不完整'}]},",
                " next_action:{label:'继续补充可追溯候选',description:'逐项披露不确定性并保留 gap。'},studies:[{study_id:'study-a',source_tier:'core',",
                " confirmed_count:60,ai_provisional_count:10,blocked_count:5,coverage_ratio:0.9333,uncertainty_statement:'5 个 BLOCKED',",
                " pdf_status:'verified',generic_parse_status:'current',chemical_import_status:'needs_review',completion_status:'current',reconciliation_status:'current',paper_evidence_status:'available'}]});",
                "if(model.route!=='honest_progressive') throw new Error(JSON.stringify(model));",
                "if(model.honestProgressive.coverageRatio!==0.8026 || model.honestProgressive.coverageThreshold!==0.8) throw new Error(JSON.stringify(model.honestProgressive));",
                "if(model.honestProgressive.confirmedCount!==180 || model.honestProgressive.aiProvisionalCount!==68 || model.honestProgressive.blockedCount!==61) throw new Error(JSON.stringify(model.honestProgressive));",
                "if(model.honestProgressive.gapRegistry.length!==1 || model.honestProgressive.uncertaintyStatement!=='61 个结构仍无法唯一确定') throw new Error(JSON.stringify(model.honestProgressive));",
                "const study=model.studies[0];",
                "if(study.confirmedCount!==60 || study.aiProvisionalCount!==10 || study.blockedCount!==5 || study.coverageRatio!==0.9333) throw new Error(JSON.stringify(study));",
            ]
        )
    )


def test_unknown_projection_preserves_nulls_and_does_not_render_completion_as_done() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v2',status:'ready',route:'honest_progressive',",
                " honest_progressive:{availability:'unknown',status:'unknown',core_molecule_count:'0',coverage_denominator:'0',confirmed_count:'0',ai_provisional_count:'0',blocked_count:'0',coverage_ratio:'0',coverage_sufficient:false,coverage_threshold:0.8,uncertainty_statement:'待 Chemical Paper 导入；状态未知。',gap_registry:null,credits_status:'NOT_APPLICABLE_BY_CURRENT_SCOPE'},",
                " studies:[{study_id:'study-a',source_tier:'core',pdf_status:'verified',generic_parse_status:'current',chemical_import_status:'needs_review',completion_status:'current',reconciliation_status:'current',paper_evidence_status:'available',confirmed_count:null,ai_provisional_count:null,blocked_count:null,coverage_ratio:null,coverage_threshold:null}],completion_queue:[],reconciliation_items:[]});",
                "if(model.honestProgressive.availability!=='unknown'||model.honestProgressive.coreMoleculeCount!==null||model.honestProgressive.coverageDenominator!==null||model.honestProgressive.confirmedCount!==null||model.honestProgressive.coverageRatio!==null) throw new Error(JSON.stringify(model.honestProgressive));",
                "class Node {",
                " constructor(tag,id=''){this.tag=tag;this.id=id;this.children=[];this.attributes={};this.className='';this.textContent='';this.listeners={};this.value='';this.type='';}",
                " append(...nodes){this.children.push(...nodes);} replaceChildren(...nodes){this.children=[...nodes];}",
                " setAttribute(name,value){this.attributes[name]=String(value);if(name==='id')this.id=String(value);}",
                " addEventListener(name,handler){this.listeners[name]=handler;}",
                " querySelector(selector){const match=selector.startsWith('#')?['id',selector.slice(1)]:selector.startsWith('.')?['className',selector.slice(1)]:null;if(match&&this[match[0]]===match[1])return this;for(const child of this.children){if(child&&typeof child.querySelector==='function'){const found=child.querySelector(selector);if(found)return found;}}return null;}",
                "}",
                "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const node=new Node('#text');node.textContent=String(value);return node;},body:new Node('body')};",
                "const mount=new Node('main');for(const id of ['honest-progressive-summary','dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list'])mount.append(new Node('section',id));",
                "ui.render(document,mount,model,{});",
                "const visibleText=node=>[node.textContent,...node.children.map(visibleText)].join(' ');const rendered=visibleText(mount);",
                "for(const expected of ['总分子 未知','CONFIRMED 未知','AI_PROVISIONAL 未知','BLOCKED 未知','覆盖率 未知','待 Chemical Paper 导入','状态未知'])if(!rendered.includes(expected))throw new Error(`missing ${expected}: ${rendered}`);",
                "for(const forbidden of ['总分子 0','CONFIRMED 0','AI_PROVISIONAL 0','BLOCKED 0','覆盖率 0%','Chemical Completion 已完成'])if(rendered.includes(forbidden))throw new Error(`misleading ${forbidden}: ${rendered}`);",
            ]
        )
    )


def test_below_threshold_projection_preserves_needs_more_candidates_status() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v2',status:'ready',route:'honest_progressive',",
                " honest_progressive:{availability:'available',status:'needs_more_traceable_candidates',core_molecule_count:309,coverage_denominator:309,confirmed_count:0,ai_provisional_count:210,blocked_count:99,coverage_ratio:210/309,coverage_sufficient:false,coverage_threshold:0.8,uncertainty_statement:'99 个结构仍无法唯一确定',gap_registry:[]},studies:[]});",
                "if(model.honestProgressive.status!=='needs_more_traceable_candidates') throw new Error(JSON.stringify(model.honestProgressive));",
            ]
        )
    )


def test_completion_model_preserves_three_resolution_states_and_ai_provenance() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v2',status:'ready',route:'honest_progressive',studies:[],",
                " completion_queue:[",
                " {study_id:'study-a',molecule_index:1,version_token:'v1',field:'resolved_smiles',resolved_smiles:'CCO',resolved_smiles_status:'AI_PROVISIONAL',confidence:0.72,provenance:{source:'structure_figure',pdf_locator:{page:3,figure_label:'Scheme 1'},evidence_excerpt:'Figure 2'},gap_reason:null,pdf_page_url:'/api/project/p/pdf/study-a?page=3'},",
                " {study_id:'study-a',molecule_index:2,version_token:'v1',field:'resolved_smiles',resolved_smiles:null,resolved_smiles_status:'BLOCKED',confidence:null,provenance:null,gap_reason:'PDF 仅给出 generic R-group',pdf_page_url:'/api/project/p/pdf/study-a?page=4'}]});",
                "const provisional=model.completionQueue[0];",
                "if(provisional.resolvedSmilesStatus!=='AI_PROVISIONAL' || provisional.confidence!==0.72 || provisional.provenanceSource!=='structure_figure' || provisional.provenanceLocator.page!==3) throw new Error(JSON.stringify(provisional));",
                "const blocked=model.completionQueue[1];",
                "if(blocked.resolvedSmilesStatus!=='BLOCKED' || blocked.resolvedSmiles!==null || blocked.gapReason!=='PDF 仅给出 generic R-group') throw new Error(JSON.stringify(blocked));",
                "const encoded=JSON.stringify(model);",
                "if(encoded.includes('/home/') || encoded.includes('evidence_excerpt')) throw new Error('unsafe projection');",
            ]
        )
    )


def test_completion_batch_request_serializes_ai_provisional_metadata_without_faking_confirmation() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const request=ui.completionBatchRequest('study-a','v1',[{moleculeIndex:4,field:'resolved_smiles',value:'CCO',resolutionStatus:'AI_PROVISIONAL',confidence:0.66,provenance:{source:'pdf',evidence:'visible structure',pdfLocator:{page:5}},reason:'PDF structure figure supports this candidate.',pdfLocator:{page:5}}],{actorType:'simulated_researcher_agent',actorLabel:'simulated_researcher_agent'});",
                "const row=request.corrections[0];",
                "if(row.resolution_status!=='AI_PROVISIONAL' || row.confidence!==0.66 || row.provenance.source!=='pdf' || row.provenance.evidence!=='visible structure' || row.provenance.pdf_locator!==undefined || row.pdf_locator.page!==5) throw new Error(JSON.stringify(request));",
                "if(row.confirmed===true || row.gap_reason!==undefined) throw new Error(JSON.stringify(request));",
            ]
        )
    )


def test_honest_progressive_route_is_visible_in_dashboard_copy() -> None:
    html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")
    for expected in ("Honest Progressive Route", "CONFIRMED", "AI_PROVISIONAL", "BLOCKED", "不确定性说明"):
        assert expected in html
