from __future__ import annotations

import json
import shutil
import subprocess
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


def test_evidence_and_synthesis_do_not_poll_five_surfaces_in_background() -> None:
    evidence_path = json.dumps(str(DASHBOARD / "review-evidence.js"))
    synthesis_path = json.dumps(str(DASHBOARD / "review-synthesis.js"))
    _run_node(
        "\n".join(
            [
                "const timers=[];const events={};const requests=[];",
                "class Node{constructor(){this.value='case-01';this.hidden=false;this.textContent='';this.children=[];}addEventListener(name,fn){(events[name]??=[]).push(fn)}replaceChildren(...value){this.children=value}append(...value){this.children.push(...value)}prepend(...value){this.children.unshift(...value)}}",
                "const nodes={'evidence-workspace-root':new Node(),'evidence-synthesis-workspace':new Node(),'evidence-workspace-status':new Node(),'evidence-workspace-message':new Node(),project:new Node(),'risk-stage-panel':new Node(),'synthesis-workspace-root':new Node()};",
                "global.document={getElementById:id=>nodes[id]||null,createElement:()=>new Node(),addEventListener:(name,fn)=>{(events[name]??=[]).push(fn)}};",
                "global.window={ReviewAuditUI:{researcherLabel:(value,fallback)=>value||fallback,humanStatus:value=>value,decisionActor:()=>''},reviewDecisionActor:()=>({}),prompt:()=>null,setInterval:(fn,delay)=>{timers.push({fn,delay});return timers.length}};",
                "global.fetch=async url=>{requests.push(url);return {ok:true,json:async()=>({route:'other',items:[],protocol:{},source_figures:[],placeholders:[]})}};",
                f"require({evidence_path});require({synthesis_path});",
                "for(const fn of events.DOMContentLoaded||[])fn();",
                "for(let checkpoint=0;checkpoint<3;checkpoint+=1)for(const timer of timers)for(let tick=0;tick<10;tick+=1)timer.fn();",
                "setImmediate(()=>{",
                " if(timers.length!==0)throw new Error(`background timers ${JSON.stringify(timers.map(value=>value.delay))}`);",
                " if(requests.length!==5)throw new Error(`request storm ${requests.length}: ${JSON.stringify(requests)}`);",
                " const counts={};for(const url of requests)counts[url]=(counts[url]||0)+1;",
                " for(const count of Object.values(counts))if(count!==1)throw new Error(JSON.stringify(counts));",
                "});",
            ]
        )
    )


def test_project_discovery_uses_one_bounded_non_overlapping_timer() -> None:
    session_path = json.dumps(str(DASHBOARD / "review-session.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({session_path});",
                "let selected='';let requests=0;let nextId=0;const timers=new Map();",
                "const setTimer=(fn,delay)=>{const id=++nextId;timers.set(id,{fn,delay});return id};",
                "const clearTimer=id=>timers.delete(id);",
                "const scheduler=ui.createProjectRefreshScheduler({refresh:async()=>{requests+=1},getProjectId:()=>selected,setTimer,clearTimer,emptyDelay:3000,selectedDelay:30000});",
                "scheduler.start();",
                "if(timers.size!==1||[...timers.values()][0].delay!==3000)throw new Error(JSON.stringify([...timers.values()]));",
                "const fire=async()=>{const [id,timer]=[...timers.entries()][0];timers.delete(id);await timer.fn();};",
                "(async()=>{",
                " await fire();if(requests!==1||timers.size!==1||[...timers.values()][0].delay!==3000)throw new Error('empty scheduling not bounded');",
                " selected='case-01';await fire();if(requests!==2||timers.size!==1||[...timers.values()][0].delay!==30000)throw new Error('selected scheduling not slowed');",
                " const [id,timer]=[...timers.entries()][0];timers.delete(id);const first=timer.fn();const duplicate=timer.fn();await Promise.all([first,duplicate]);",
                " if(requests!==3||timers.size!==1)throw new Error(`overlap requests=${requests} timers=${timers.size}`);",
                " scheduler.stop();if(timers.size!==0)throw new Error('timer not stopped');",
                "})().catch(error=>{console.error(error);process.exit(1)});",
            ]
        )
    )


def test_synthesis_mutation_performs_one_explicit_post_write_refresh() -> None:
    source = (DASHBOARD / "review-synthesis.js").read_text(encoding="utf-8")
    assert "await refresh(true)" in source
    assert "async function refresh(force = false)" in source
    assert "busy && !force" in source
    assert source.count("await refresh(true)") == 1


def test_review_page_uses_refresh_scheduler_instead_of_fixed_interval() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    assert "ReviewSessionUI.createProjectRefreshScheduler" in html
    assert "setInterval(refreshProjects, 3000)" not in html
    assert html.count("startProjectsRefresh();") == 1
