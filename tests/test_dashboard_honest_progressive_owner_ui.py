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


def test_owner_projection_exposes_honest_progressive_counts_coverage_and_uncertainty() -> None:
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


def test_owner_completion_model_preserves_resolution_states_and_ai_provenance() -> None:
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
                "if(provisional.resolvedSmilesStatus!=='AI_PROVISIONAL' || provisional.confidence!==0.72 || provisional.provenanceSource!=='structure_figure' || provisional.provenanceLocator.page!==3 || provisional.provenance.source!=='structure_figure' || provisional.provenance.pdfLocator.page!==3) throw new Error(JSON.stringify(provisional));",
                "const blocked=model.completionQueue[1];",
                "if(blocked.resolvedSmilesStatus!=='BLOCKED' || blocked.resolvedSmiles!==null || blocked.gapReason!=='PDF 仅给出 generic R-group') throw new Error(JSON.stringify(blocked));",
                "const encoded=JSON.stringify(model);",
                "if(encoded.includes('/home/') || encoded.includes('evidence_excerpt')) throw new Error('unsafe projection');",
            ]
        )
    )


def test_owner_completion_batch_request_serializes_ai_metadata_without_confirmation() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "const request=ui.completionBatchRequest('study-a','v1',[{moleculeIndex:4,field:'resolved_smiles',value:'CCO',resolutionStatus:'AI_PROVISIONAL',confidence:0.66,provenance:{source:'pdf',pdfLocator:{page:5}},reason:'PDF structure figure supports this candidate.',pdfLocator:{page:5}}],{actorType:'simulated_researcher_agent',actorLabel:'simulated_researcher_agent'});",
                "const row=request.corrections[0];",
                "if(row.resolution_status!=='AI_PROVISIONAL' || row.confidence!==0.66 || row.provenance.source!=='pdf' || row.provenance.pdf_locator.page!==5) throw new Error(JSON.stringify(request));",
                "if(row.confirmed===true || row.gap_reason!==undefined) throw new Error(JSON.stringify(request));",
            ]
        )
    )


def test_owner_dashboard_copy_names_honest_progressive_route_and_three_states() -> None:
    html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")
    for expected in ("Honest Progressive Route", "CONFIRMED", "AI_PROVISIONAL", "BLOCKED", "不确定性说明"):
        assert expected in html


def test_new_route_header_and_stage_list_use_progress_authority() -> None:
    html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")

    assert "const evidenceToReleaseRoute = progressPayload.route === 'evidence-to-release.v1';" in html
    assert "progressPayload.route === 'evidence-to-release.v1' || parseQualityGateActive()" in html
    assert "progressPayload.route === 'evidence-to-release.v1'\n        ? progressPayload.recommended_next" in html


def test_owner_renderer_shows_counts_study_coverage_blocked_gap_and_actor_residual() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "class Node {",
                " constructor(tag,id=''){this.tag=tag;this.id=id;this.children=[];this.attributes={};this.className='';this.textContent='';this.listeners={};this.value='';this.type='';}",
                " append(...nodes){this.children.push(...nodes);} replaceChildren(...nodes){this.children=[...nodes];}",
                " setAttribute(name,value){this.attributes[name]=String(value);if(name==='id')this.id=String(value);}",
                " addEventListener(name,handler){this.listeners[name]=handler;}",
                " querySelector(selector){const match=selector.startsWith('#')?['id',selector.slice(1)]:selector.startsWith('.')?['className',selector.slice(1)]:null;if(match&&this[match[0]]===match[1])return this;for(const child of this.children){if(child&&typeof child.querySelector==='function'){const found=child.querySelector(selector);if(found)return found;}}return null;}",
                "}",
                "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const node=new Node('#text');node.textContent=String(value);return node;},body:new Node('body')};",
                "const mount=new Node('main');for(const id of ['honest-progressive-summary','dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list'])mount.append(new Node('section',id));",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v2',status:'ready',route:'honest_progressive',honest_progressive:{availability:'available',status:'ready',core_molecule_count:2,coverage_denominator:2,confirmed_count:1,ai_provisional_count:0,blocked_count:1,coverage_ratio:0.5,coverage_threshold:0.8,uncertainty_statement:'1 个结构仍无法唯一确定',gap_registry:[{study_id:'secret-study',molecule_index:1,status:'BLOCKED',gap_reason:'PDF 仅给出 generic R-group',value:'C'}],actor_provenance_residual:'本记录只允许 append-only 追加，不覆盖历史。'},studies:[{source_tier:'core',confirmed_count:1,ai_provisional_count:0,blocked_count:1,coverage_ratio:0.5,coverage_denominator:2,uncertainty_statement:'该论文仍有 1 个 BLOCKED'}],completion_queue:[{study_id:'secret-study',molecule_index:1,version_token:'v1',field:'resolved_smiles',resolved_smiles:'C',resolved_smiles_status:'BLOCKED',gap_reason:'PDF 仅给出 generic R-group',actor_provenance_residual:'append-only residual'}]});",
                "ui.render(document,mount,model,{});",
                "const visibleText=node=>[node.textContent,...node.children.map(visibleText)].join(' ');const rendered=visibleText(mount);",
                "for(const expected of ['Honest Progressive Route','总分子 2','CONFIRMED 1','AI_PROVISIONAL 0','BLOCKED 1','覆盖率 50%','阈值 80%','不确定性说明','1 个结构仍无法唯一确定','论文覆盖率 50% · 1/2','PDF 仅给出 generic R-group','value=null','append-only'])if(!rendered.includes(expected))throw new Error(`missing ${expected}: ${rendered}`);",
                "if(rendered.includes('secret-study') || rendered.includes('value=C')) throw new Error(`unsafe or confirmed blocked value: ${rendered}`);",
            ]
        )
    )


def test_owner_ai_candidate_form_submits_provisional_metadata_and_pdf_locator() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "class Node {",
                " constructor(tag,id=''){this.tag=tag;this.id=id;this.children=[];this.attributes={};this.className='';this.textContent='';this.listeners={};this.value='';this.type='';}",
                " append(...nodes){this.children.push(...nodes);} replaceChildren(...nodes){this.children=[...nodes];}",
                " setAttribute(name,value){this.attributes[name]=String(value);if(name==='id')this.id=String(value);}",
                " addEventListener(name,handler){this.listeners[name]=handler;}",
                " querySelector(selector){const match=selector.startsWith('#')?['id',selector.slice(1)]:selector.startsWith('.')?['className',selector.slice(1)]:null;if(match&&this[match[0]]===match[1])return this;for(const child of this.children){if(child&&typeof child.querySelector==='function'){const found=child.querySelector(selector);if(found)return found;}}return null;}",
                "}",
                "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const node=new Node('#text');node.textContent=String(value);return node;},body:new Node('body')};",
                "const mount=new Node('main');for(const id of ['honest-progressive-summary','dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list'])mount.append(new Node('section',id));",
                "const model=ui.projectionModel({schema_version:'dual-parse-projection.v2',status:'ready',route:'honest_progressive',studies:[],completion_queue:[{study_id:'study-a',molecule_index:0,version_token:'v1',field:'resolved_smiles',resolved_smiles:null,resolved_smiles_status:'BLOCKED',gap_reason:'结构图不完整',actor_provenance_residual:'append-only residual'}]});",
                "let saved=null;ui.render(document,mount,model,{actor:{actorType:'simulated_researcher_agent',actorLabel:'agent'},onCompletionSave:payload=>{saved=payload;}});",
                "const all=[];const visit=node=>{all.push(node);for(const child of node.children||[])if(child&&typeof child==='object')visit(child);};visit(mount);",
                "const form=all.find(node=>node.className==='dual-ai-candidate-form');if(!form)throw new Error('missing AI candidate form');",
                "const value=all.find(node=>node.className==='dual-ai-candidate-value');const confidence=all.find(node=>node.className==='dual-ai-candidate-confidence');const provenance=all.find(node=>node.className==='dual-ai-candidate-provenance');const page=all.find(node=>node.className==='dual-ai-candidate-page');const reason=all.find(node=>node.className==='dual-ai-candidate-reason');",
                "value.value='CCO';confidence.value='0.66';provenance.value='pdf';page.value='5';reason.value='PDF structure figure supports this candidate.';form.listeners.submit({preventDefault(){}});",
                "const row=saved?.corrections?.[0];if(!row||row.resolution_status!=='AI_PROVISIONAL'||row.confidence!==0.66||row.provenance.source!=='pdf'||row.pdf_locator.page!==5||row.confirmed===true)throw new Error(JSON.stringify(saved));",
                "if(row.gap_reason!==undefined)throw new Error(JSON.stringify(row));",
            ]
        )
    )


def test_owner_ai_candidate_request_rejects_private_or_raw_reason_text() -> None:
    module_path = json.dumps(str(DUAL_SCRIPT))
    _run_node(
        "\n".join(
            [
                f"const ui=require({module_path});",
                "let rejected=false;try{ui.completionBatchRequest('study-a','v1',[{moleculeIndex:1,field:'resolved_smiles',value:'CCO',resolutionStatus:'AI_PROVISIONAL',confidence:0.5,provenance:{source:'pdf',pdfLocator:{page:5}},reason:'/home/private/raw.json',pdfLocator:{page:5}}],{actorType:'simulated_researcher_agent',actorLabel:'agent'});}catch(_){rejected=true;}",
                "if(!rejected)throw new Error('private reason text was serialized');",
                "rejected=false;try{ui.completionBatchRequest('study-a','v1',[{moleculeIndex:1,field:'resolved_smiles',value:'{raw:json}',reason:'visible PDF note',pdfLocator:{page:5}}],{actorType:'human_researcher',actorLabel:'researcher'});}catch(_){rejected=true;}",
                "if(!rejected)throw new Error('raw resolved value was serialized');",
            ]
        )
    )
