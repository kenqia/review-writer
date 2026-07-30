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


def test_project_rows_have_stable_unique_researcher_labels_without_technical_ids() -> None:
    sys.path.insert(0, str(ROOT))
    from view import serve_review_dashboard as dashboard

    rows = [
        {"project_id": "technical-old-v2", "topic": "同题综述"},
        {"project_id": "technical-fresh-v2", "topic": "同题综述"},
        {"project_id": "technical-unknown-v2", "topic": ""},
    ]

    labeled = dashboard.with_visible_project_labels(rows)

    assert [row["visible_label"] for row in labeled] == [
        "同题综述（项目 1/3）",
        "同题综述（项目 2/3）",
        "未命名综述项目（项目 3/3）",
    ]
    assert dashboard.with_visible_project_labels(rows) == labeled
    assert len({row["visible_label"] for row in labeled}) == len(labeled)
    visible = json.dumps([row["visible_label"] for row in labeled], ensure_ascii=False)
    for technical_id in ("technical-old-v2", "technical-fresh-v2", "technical-unknown-v2"):
        assert technical_id not in visible


def test_project_selector_keeps_ids_out_of_dom_and_requires_explicit_visible_selection() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    refresh = _function(html, "refreshProjects")
    select = _function(html, "selectProject")
    _run_node(
        "\n".join(
            [
                "const selectNode={value:'',options:[],append(option){this.options.push(option);if(option.selected)this.value=option.value;}};",
                "const nodes={project:selectNode,'project-waiting-message':{textContent:''},'workbench-message':{textContent:''}};const $=id=>nodes[id];",
                "const document={createElement:()=>({value:'',textContent:'',disabled:false,selected:false})};",
                "const window={location:{pathname:'/review',search:'?review_actor=simulated_researcher_agent'}};",
                "const clear=node=>{node.options=[];node.value='';};",
                "const setProjectSelectionWorkspace=()=>{},setEmptyProjectWorkspace=()=>{},setWorkspace=()=>{},setProjectLoadBusy=()=>{};",
                "const confirmDiscardDraftChanges=()=>true,confirmDiscardRiskDecisions=()=>true,confirmDiscardParseQualityDecisions=()=>true;",
                "let projectsRefreshBusy=false,projects=[],projectId='',projectLoadGeneration=0,projectLoadBusy=false,activeWorkspace='cockpit',activeParseStudyId='';",
                "let projectOptionIds=new Map(),projectOptionKeys=new Map(),loadCount=0;const loadProject=async()=>{loadCount+=1;return 'loaded';};",
                "const getPayload=async()=>[",
                " {project_id:'technical-old-v2',topic:'同题综述',visible_label:'同题综述（项目 1/2）'},",
                " {project_id:'technical-fresh-v2',topic:'同题综述',visible_label:'同题综述（项目 2/2）'}];",
                refresh,
                select,
                "(async()=>{",
                " const initial=await refreshProjects();",
                " if(initial!=='selection_required'||projectId!==''||loadCount!==0||selectNode.value!=='')throw new Error(JSON.stringify({initial,projectId,loadCount,value:selectNode.value}));",
                " const serialized=JSON.stringify(selectNode.options);",
                " if(serialized.includes('technical-old-v2')||serialized.includes('technical-fresh-v2'))throw new Error(`technical id leaked into DOM ${serialized}`);",
                " if(JSON.stringify(selectNode.options.map(option=>option.value))!==JSON.stringify(['','project-option-1','project-option-2']))throw new Error(serialized);",
                " if(selectNode.options[2].textContent!=='同题综述（项目 2/2）')throw new Error(serialized);",
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
