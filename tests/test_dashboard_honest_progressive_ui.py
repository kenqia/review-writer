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
                " honest_progressive:{core_molecule_count:309,confirmed_count:180,ai_provisional_count:68,blocked_count:61,coverage_ratio:0.8026,coverage_threshold:0.8,uncertainty_statement:'61 个结构仍无法唯一确定',gap_registry:[{study_id:'study-a',molecule_index:4,status:'BLOCKED',gap_reason:'结构图不完整'}]},",
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
                "const request=ui.completionBatchRequest('study-a','v1',[{moleculeIndex:4,field:'resolved_smiles',value:'CCO',resolutionStatus:'AI_PROVISIONAL',confidence:0.66,provenance:{source:'pdf',pdfLocator:{page:5}},reason:'PDF structure figure supports this candidate.',pdfLocator:{page:5}}],{actorType:'simulated_researcher_agent',actorLabel:'simulated_researcher_agent'});",
                "const row=request.corrections[0];",
                "if(row.resolution_status!=='AI_PROVISIONAL' || row.confidence!==0.66 || row.provenance.source!=='pdf' || row.provenance.pdf_locator.page!==5) throw new Error(JSON.stringify(request));",
                "if(row.confirmed===true || row.gap_reason!==undefined) throw new Error(JSON.stringify(request));",
            ]
        )
    )


def test_honest_progressive_route_is_visible_in_dashboard_copy() -> None:
    html = (ROOT / "view" / "assets" / "dashboard" / "review.html").read_text(encoding="utf-8")
    for expected in ("Honest Progressive Route", "CONFIRMED", "AI_PROVISIONAL", "BLOCKED", "不确定性说明"):
        assert expected in html
