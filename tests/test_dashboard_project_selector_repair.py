from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "view" / "assets" / "dashboard"


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


def _function(html: str, name: str) -> str:
    match = re.search(
        rf"^    (?:async )?function {name}\([^\n]*\) \{{[\s\S]*?^    \}}",
        html,
        flags=re.MULTILINE,
    )
    assert match is not None
    return match.group(0)


def test_explicit_project_label_is_stable_when_other_projects_are_inserted_or_removed(
    tmp_path: Path,
) -> None:
    sys.path.insert(0, str(ROOT))
    from view import serve_review_dashboard as dashboard

    target = {
        "project_id": "technical-fresh-v2",
        "topic": "同题综述",
        "project_label": "新一轮证据复核",
    }
    legacy = {"project_id": "technical-old-v2", "topic": "同题综述"}
    unrelated = {"project_id": "technical-other-v2", "topic": "其他课题"}

    snapshots = ([legacy, target], [unrelated, legacy, target], [target])
    target_rows = [
        next(
            row
            for row in dashboard.with_visible_project_labels(list(snapshot))
            if row["project_id"] == target["project_id"]
        )
        for snapshot in snapshots
    ]

    assert [row["visible_label"] for row in target_rows] == ["新一轮证据复核"] * 3
    assert all(row["selectable"] is True for row in target_rows)
    assert all("project_label" not in row for row in target_rows)
    visible = json.dumps(
        [
            {
                "visible_label": row["visible_label"],
                "selection_message": row["selection_message"],
            }
            for row in target_rows
        ],
        ensure_ascii=False,
    )
    assert target["project_id"] not in visible

    state_path = (
        tmp_path
        / "review-projects"
        / target["project_id"]
        / "00_brief"
        / "review_state.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {"brief": {"topic": target["topic"], "project_label": target["project_label"]}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    listed_target = next(
        row
        for row in dashboard.list_review_projects(tmp_path)
        if row["project_id"] == target["project_id"]
    )
    assert listed_target["visible_label"] == target["project_label"]
    assert listed_target["selectable"] is True


def test_duplicate_legacy_labels_fail_closed_without_exposing_technical_ids() -> None:
    sys.path.insert(0, str(ROOT))
    from view import serve_review_dashboard as dashboard

    labeled = dashboard.with_visible_project_labels(
        [
            {"project_id": "technical-old-v2", "topic": "同题综述"},
            {"project_id": "technical-fresh-v2", "topic": "同题综述"},
        ]
    )

    assert [row["visible_label"] for row in labeled] == ["同题综述", "同题综述"]
    assert all(row["selectable"] is False for row in labeled)
    assert all("唯一项目显示名称" in row["selection_message"] for row in labeled)
    visible = json.dumps(
        [
            {key: value for key, value in row.items() if key != "project_id"}
            for row in labeled
        ],
        ensure_ascii=False,
    )
    assert "technical-old-v2" not in visible
    assert "technical-fresh-v2" not in visible

    session_path = json.dumps(str(DASHBOARD / "review-session.js"))
    payload = json.dumps(labeled, ensure_ascii=False)
    _run_node(
        "\n".join(
            [
                f"const ui=require({session_path});",
                f"const choices=ui.createProjectSelectionRegistry().replace({payload});",
                "if(choices.some(choice=>choice.selectable))throw new Error(JSON.stringify(choices));",
                "const visible=JSON.stringify(choices);",
                "if(visible.includes('technical-old-v2')||visible.includes('technical-fresh-v2'))throw new Error(visible);",
                "if(!choices.every(choice=>choice.label.includes('唯一项目显示名称')))throw new Error(visible);",
            ]
        )
    )


def test_project_selector_keeps_ids_out_of_dom_and_requires_explicit_visible_selection() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    session_path = json.dumps(str(DASHBOARD / "review-session.js"))
    refresh = _function(html, "refreshProjects")
    select = _function(html, "selectProject")
    _run_node(
        "\n".join(
            [
                "const selectNode={value:'',options:[],append(option){this.options.push(option);if(option.selected)this.value=option.value;}};",
                "const nodes={project:selectNode,'project-waiting-message':{textContent:''},'workbench-message':{textContent:''}};const $=id=>nodes[id];",
                "const document={createElement:()=>({value:'',textContent:'',disabled:false,selected:false})};",
                f"const ReviewSessionUI=require({session_path});const projectSelection=ReviewSessionUI.createProjectSelectionRegistry();",
                "const window={location:{pathname:'/review',search:'?review_actor=simulated_researcher_agent'},reviewProjectSelection:projectSelection};",
                "const clear=node=>{node.options=[];node.value='';};",
                "const setProjectSelectionWorkspace=()=>{},setEmptyProjectWorkspace=()=>{},setWorkspace=()=>{},setProjectLoadBusy=()=>{};",
                "const confirmDiscardDraftChanges=()=>true,confirmDiscardRiskDecisions=()=>true,confirmDiscardParseQualityDecisions=()=>true;",
                "let projectsRefreshBusy=false,projects=[],projectId='',projectLoadGeneration=0,projectLoadBusy=false,activeWorkspace='cockpit',activeParseStudyId='';",
                "let loadCount=0;const loadProject=async()=>{loadCount+=1;return 'loaded';};",
                "const getPayload=async()=>[",
                " {project_id:'technical-old-v2',topic:'同题综述',visible_label:'历史复核',selectable:true,selection_message:''},",
                " {project_id:'technical-fresh-v2',topic:'同题综述',visible_label:'新一轮证据复核',selectable:true,selection_message:''}];",
                refresh,
                select,
                "(async()=>{",
                " const initial=await refreshProjects();",
                " if(initial!=='selection_required'||projectId!==''||loadCount!==0||selectNode.value!=='')throw new Error(JSON.stringify({initial,projectId,loadCount,value:selectNode.value}));",
                " const serialized=JSON.stringify(selectNode.options);",
                " if(serialized.includes('technical-old-v2')||serialized.includes('technical-fresh-v2'))throw new Error(`technical id leaked into DOM ${serialized}`);",
                " if(JSON.stringify(selectNode.options.map(option=>option.value))!==JSON.stringify(['','project-option-1','project-option-2']))throw new Error(serialized);",
                " if(selectNode.options[2].textContent!=='新一轮证据复核')throw new Error(serialized);",
                " const result=await selectProject({target:{value:'project-option-2'}});",
                " if(result!=='loaded'||projectId!=='technical-fresh-v2'||loadCount!==1)throw new Error(JSON.stringify({result,projectId,loadCount}));",
                " if(window.location.pathname!=='/review'||window.location.search!=='?review_actor=simulated_researcher_agent')throw new Error(JSON.stringify(window.location));",
                "})().catch(error=>{console.error(error);process.exit(1)});",
            ]
        )
    )


def test_initial_project_load_and_bfcache_share_one_bounded_scheduler() -> None:
    session_path = json.dumps(str(DASHBOARD / "review-session.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({session_path});",
                "let now=0,requests=0,nextId=0;const timers=new Map();",
                "const setTimer=(fn,delay)=>{const id=++nextId;timers.set(id,{fn,due:now+delay});return id};",
                "const clearTimer=id=>timers.delete(id);",
                "const scheduler=ui.createProjectRefreshScheduler({refresh:async()=>{requests+=1},getProjectId:()=>'',setTimer,clearTimer,emptyDelay:3000,selectedDelay:30000});",
                "const lifecycle={};const fakeWindow={addEventListener:(name,handler)=>{lifecycle[name]=handler}};ui.installProjectRefreshLifecycle(fakeWindow,()=>scheduler);",
                "const advance=async target=>{while(true){const due=[...timers.entries()].filter(([,timer])=>timer.due<=target).sort((a,b)=>a[1].due-b[1].due)[0];if(!due)break;const [id,timer]=due;timers.delete(id);now=timer.due;await timer.fn();}now=target};",
                "(async()=>{",
                " await scheduler.start({immediate:true});",
                " if(requests!==1||timers.size!==1)throw new Error(`initial requests=${requests} timers=${timers.size}`);",
                " scheduler.start({immediate:true});lifecycle.pageshow({persisted:false});lifecycle.pageshow({persisted:false});",
                " await advance(5000);if(requests>2||timers.size!==1)throw new Error(`five-second bound requests=${requests} timers=${timers.size}`);",
                " lifecycle.pagehide({persisted:true});if(timers.size!==0)throw new Error(`pagehide timers=${timers.size}`);",
                " lifecycle.pageshow({persisted:true});lifecycle.pageshow({persisted:true});if(timers.size!==1)throw new Error(`BFCache timers=${timers.size}`);",
                " const before=requests;await advance(10000);if(requests-before>1||timers.size!==1)throw new Error(`BFCache requests=${requests-before} timers=${timers.size}`);",
                " scheduler.stop();",
                "})().catch(error=>{console.error(error);process.exit(1)});",
            ]
        )
    )


def test_evidence_and_synthesis_resolve_five_requests_through_shared_selection_registry() -> None:
    evidence_path = json.dumps(str(DASHBOARD / "review-evidence.js"))
    synthesis_path = json.dumps(str(DASHBOARD / "review-synthesis.js"))
    session_path = json.dumps(str(DASHBOARD / "review-session.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({session_path});",
                "const selection=ui.createProjectSelectionRegistry();",
                "const choices=selection.replace([",
                " {project_id:'technical-old-v2',visible_label:'历史复核',selectable:true},",
                " {project_id:'technical-fresh-v2',visible_label:'新一轮证据复核',selectable:true}]);",
                "const events={};const requests=[];const visibleLabels=[];",
                "const getVisibleLabel=selection.getVisibleLabel;selection.getVisibleLabel=key=>{const label=getVisibleLabel(key);visibleLabels.push(label);return label};",
                "class Node{constructor(){this.value='';this.hidden=false;this.textContent='';this.children=[];}addEventListener(name,fn){(events[name]??=[]).push(fn)}replaceChildren(...value){this.children=value}append(...value){this.children.push(...value)}prepend(...value){this.children.unshift(...value)}}",
                "const nodes={'evidence-workspace-root':new Node(),'evidence-synthesis-workspace':new Node(),'evidence-workspace-status':new Node(),'evidence-workspace-message':new Node(),project:new Node(),'risk-stage-panel':new Node(),'synthesis-workspace-root':new Node()};",
                "nodes.project.value=choices[1].key;",
                "global.document={getElementById:id=>nodes[id]||null,createElement:()=>new Node(),addEventListener:(name,fn)=>{(events[name]??=[]).push(fn)}};",
                "global.window={ReviewSessionUI:ui,reviewProjectSelection:selection,ReviewAuditUI:{researcherLabel:(value,fallback)=>value||fallback,humanStatus:value=>value,decisionActor:()=>''},reviewDecisionActor:()=>({}),prompt:()=>null};",
                "global.fetch=async url=>{requests.push(url);return {ok:true,json:async()=>({route:'other',items:[],protocol:{},source_figures:[],placeholders:[]})}};",
                f"require({evidence_path});require({synthesis_path});",
                "for(const fn of events.DOMContentLoaded||[])fn();",
                "setImmediate(()=>{",
                " const expected=['paper-evidence','comparison-protocol','synthesis','section-contracts','review-figures'].map(suffix=>`/api/project/technical-fresh-v2/${suffix}`).sort();",
                " if(JSON.stringify([...requests].sort())!==JSON.stringify(expected))throw new Error(JSON.stringify(requests));",
                " if(requests.some(url=>url.includes('project-option')||url.includes(encodeURIComponent('新一轮证据复核'))))throw new Error(JSON.stringify(requests));",
                " if(visibleLabels.filter(label=>label==='新一轮证据复核').length<2)throw new Error(JSON.stringify(visibleLabels));",
                "});",
            ]
        )
    )
