from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_SCRIPT = ROOT / "view/assets/dashboard/review-dual-parse.js"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _authority_payloads(*, chemical_bound: bool, next_action: str) -> tuple[dict, dict, dict, dict, dict]:
    study_ids = ["study-a", "study-b", "study-c"]
    dual = {
        "studies": [
            {
                "study_id": study_id,
                "source_tier": "core",
                "status": "current" if chemical_bound else "blocked",
                "pdf_status": "verified",
                "generic_parse_status": "current",
            }
            for study_id in study_ids
        ]
    }
    completion = {
        "schema_version": "chemical-completion-project-state.v2",
        "studies": [
            {
                "study_id": study_id,
                "status": "current" if chemical_bound else "blocked",
                "missing_name_count": 0,
                "missing_resolved_smiles_count": 0,
                "ai_authored_smiles_count": 0,
                "version_token": f"cpv1.{study_id}",
            }
            for study_id in study_ids
        ],
    }
    reconciliation = {
        "schema_version": "parse-reconciliation-project-state.v2",
        "studies": [
            {"study_id": study_id, "status": "current" if chemical_bound else "blocked"}
            for study_id in study_ids
        ],
    }
    chemical = {
        "schema_version": "chemical-paper-projection.v2",
        "studies": [
            {
                "study_id": study_id,
                "status": "needs_review" if chemical_bound else "missing",
                "pdf_binding_status": "bound" if chemical_bound else "missing",
            }
            for study_id in study_ids
        ],
    }
    return dual, completion, reconciliation, chemical, {"unique_next_action": next_action}


def _write_six_source_inputs(project: Path, *, ready: bool) -> None:
    downloads = []
    results = []
    for study_id in ("study-a", "study-b", "study-c"):
        for role in ("MAIN", "SI"):
            download_id = f"{study_id}-{role}"
            downloads.append(
                {
                    "download_id": download_id,
                    "study_id": study_id,
                    "document_role": role,
                }
            )
            if ready:
                results.append({"download_id": download_id, "status": "VERIFIED_EXISTING"})
    _write_json(project / "00_discovery/acquisition_manifest.json", {"downloads": downloads})
    _write_json(project / "00_sources/acquisition_receipt.json", {"results": results})


def _write_formal_source_inputs(project: Path) -> None:
    study_ids = ["study-a", "study-b", "study-c"]
    rows = [
        {
            "study_id": study_id,
            "document_role": role,
            "status": "IMPORTED",
            "path": f"/private/formal/{study_id}/{role.lower()}.pdf",
            "sha256": f"raw-sha256-{study_id}-{role}",
            "raw": {"provider": "private-provider", "payload": "raw-payload"},
        }
        for study_id in study_ids
        for role in ("MAIN", "SI")
    ]
    _write_json(
        project / "00_sources/input_provenance_manifest.json",
        {"schema_version": "input-provenance-manifest.v1", "inputs": rows},
    )
    _write_json(
        project / "00_sources/si_resource_registry.json",
        {
            "schema_version": "si-resource-registry.v1",
            "resources": [
                {
                    "study_id": study_id,
                    "document_role": "SI",
                    "status": "IMPORTED",
                    "raw_path": f"/private/registry/{study_id}.zip",
                    "content_sha256": f"raw-registry-sha256-{study_id}",
                }
                for study_id in study_ids
            ],
        },
    )
    _write_json(
        project / "00_sources/source_coverage.json",
        {
            "schema_version": "source-coverage.v1",
            "studies": [
                {
                    "study_id": study_id,
                    "available_roles": ["MAIN", "SI"],
                    "si_policy": "REQUIRED",
                    "study_status": "READY",
                    "raw_digest": f"raw-coverage-sha256-{study_id}",
                }
                for study_id in study_ids
            ],
        },
    )


def test_formal_source_artifacts_drive_si_currentness_without_private_fields(
    tmp_path: Path, monkeypatch
) -> None:
    from review_writer.delivery import dual_parse_release

    project = tmp_path / "project"
    project.mkdir()
    _write_six_source_inputs(project, ready=False)
    _write_formal_source_inputs(project)
    monkeypatch.setattr(
        dual_parse_release,
        "_dashboard_authority_payloads",
        lambda _: _authority_payloads(
            chemical_bound=True,
            next_action="继续补充可追溯候选",
        ),
    )

    projection = dual_parse_release.dual_parse_dashboard_projection(project)
    coverage = projection["input_coverage"]
    serialized = json.dumps(projection, ensure_ascii=False)

    assert coverage["hard_gate"] == "3/3/3/3"
    assert coverage["lanes"]["si"] == {
        "available": 3,
        "total": 3,
        "status": "current",
    }
    assert all(row["si_status"] == "current" for row in coverage["studies"])
    for private_value in (
        "/private/formal/",
        "/private/registry/",
        "raw-payload",
        "raw-sha256-",
        "raw-registry-sha256-",
        "raw-coverage-sha256-",
    ):
        assert private_value not in serialized


def test_projection_exposes_four_input_hard_gate_and_per_study_currentness(
    tmp_path: Path, monkeypatch
) -> None:
    from review_writer.delivery import dual_parse_release

    project = tmp_path / "project"
    project.mkdir()
    _write_six_source_inputs(project, ready=True)
    monkeypatch.setattr(
        dual_parse_release,
        "_dashboard_authority_payloads",
        lambda _: _authority_payloads(
            chemical_bound=True,
            next_action="继续补充可追溯候选",
        ),
    )

    projection = dual_parse_release.dual_parse_dashboard_projection(project)
    coverage = projection["input_coverage"]

    assert coverage["hard_gate"] == "3/3/3/3"
    assert coverage["ready"] is True
    assert {
        name: (lane["available"], lane["total"], lane["status"])
        for name, lane in coverage["lanes"].items()
    } == {
        "main_pdf": (3, 3, "current"),
        "si": (3, 3, "current"),
        "chemical_zip": (3, 3, "current"),
        "generic_parse": (3, 3, "current"),
    }
    assert all(row["si_status"] == "current" for row in coverage["studies"])
    assert all(row["chemical_zip_status"] == "current" for row in coverage["studies"])


def test_missing_chemical_keeps_unknown_science_and_owns_unique_next_action(
    tmp_path: Path, monkeypatch
) -> None:
    from review_writer.delivery import dual_parse_release

    project = tmp_path / "project"
    project.mkdir()
    _write_six_source_inputs(project, ready=True)
    monkeypatch.setattr(
        dual_parse_release,
        "_dashboard_authority_payloads",
        lambda _: _authority_payloads(
            chemical_bound=False,
            next_action="完成 11 项 Generic Parse 决定",
        ),
    )

    projection = dual_parse_release.dual_parse_dashboard_projection(project)

    assert projection["input_coverage"]["hard_gate"] == "3/3/0/3"
    assert projection["input_coverage"]["ready"] is False
    assert projection["next_action"]["label"] == "待 Chemical Paper 导入"
    assert projection["honest_progressive"]["coverage_denominator"] if "honest_progressive" in projection else True


def test_ui_renders_hard_gate_and_source_disclosure_without_internal_ids() -> None:
    node = shutil.which("node")
    assert node is not None
    script = json.dumps(str(DASHBOARD_SCRIPT))
    source = "\n".join(
        [
            f"const ui=require({script});",
            "const model=ui.projectionModel({schema_version:'dual-parse-projection.v2',status:'ready',route:'honest_progressive',",
            " input_coverage:{schema_version:'dashboard-input-coverage.v1',hard_gate:'3/3/3/3',ready:true,",
            "  source_disclosure:'当前输入仅披露来源可用性；原始 PDF 是科学仲裁来源。',",
            "  lanes:{main_pdf:{available:3,total:3,status:'current'},si:{available:3,total:3,status:'current'},chemical_zip:{available:3,total:3,status:'current'},generic_parse:{available:3,total:3,status:'current'}},",
            "  studies:[{study_id:'internal-study-a',si_status:'current',chemical_zip_status:'current'}]},",
            " next_action:{label:'继续补充可追溯候选',description:'保留不确定性。'},",
            " studies:[{study_id:'internal-study-a',source_tier:'core',pdf_status:'verified',generic_parse_status:'current',chemical_import_status:'needs_review',completion_status:'blocked',reconciliation_status:'blocked',paper_evidence_status:'blocked'}],",
            " honest_progressive:{availability:'unknown',status:'unknown',coverage_threshold:0.8,uncertainty_statement:'待 Chemical Completion 核验。',gap_registry:null}});",
            "class Node{constructor(tag,id=''){this.tag=tag;this.id=id;this.children=[];this.textContent='';this.className='';this.attributes={};}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=[...nodes];}setAttribute(k,v){this.attributes[k]=String(v);if(k==='id')this.id=String(v);}addEventListener(){ }querySelector(selector){const id=selector.startsWith('#')?selector.slice(1):'';if(id&&this.id===id)return this;for(const child of this.children){const found=child?.querySelector?.(selector);if(found)return found;}return null;}}",
            "const document={createElement:tag=>new Node(tag),createTextNode:value=>{const n=new Node('#text');n.textContent=String(value);return n;},body:new Node('body')};",
            "const mount=new Node('main');for(const id of ['honest-progressive-summary','dual-study-status','chemical-import-preflight','chemical-completion-queue','reconciliation-list'])mount.append(new Node('section',id));",
            "ui.render(document,mount,model,{});",
            "const visible=node=>[node.textContent,...node.children.map(visible)].join(' ');const rendered=visible(mount);",
            "for(const expected of ['3/3/3/3','主 PDF','SI','Chemical ZIP','Generic Parse','当前输入仅披露来源可用性','SI 当前有效','Chemical ZIP 当前有效'])if(!rendered.includes(expected))throw new Error(`missing ${expected}: ${rendered}`);",
            "for(const forbidden of ['internal-study-a','/home/','sha256','token'])if(JSON.stringify(model).includes(forbidden))throw new Error(`leaked ${forbidden}`);",
        ]
    )
    completed = subprocess.run([node, "-e", source], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
