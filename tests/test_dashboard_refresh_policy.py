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
    session_path = json.dumps(str(DASHBOARD / "review-session.js"))
    _run_node(
        "\n".join(
            [
                "const timers=[];const events={};const requests=[];",
                "class Node{constructor(){this.value='case-01';this.hidden=false;this.textContent='';this.children=[];}addEventListener(name,fn){(events[name]??=[]).push(fn)}replaceChildren(...value){this.children=value}append(...value){this.children.push(...value)}prepend(...value){this.children.unshift(...value)}}",
                "const nodes={'evidence-workspace-root':new Node(),'evidence-synthesis-workspace':new Node(),'evidence-workspace-status':new Node(),'evidence-workspace-message':new Node(),project:new Node(),'risk-stage-panel':new Node(),'synthesis-workspace-root':new Node()};",
                "global.document={getElementById:id=>nodes[id]||null,createElement:()=>new Node(),addEventListener:(name,fn)=>{(events[name]??=[]).push(fn)}};",
                f"global.window={{ReviewSessionUI:require({session_path}),ReviewAuditUI:{{researcherLabel:(value,fallback)=>value||fallback,humanStatus:value=>value,decisionActor:()=>''}},reviewDecisionActor:()=>({{}}),prompt:()=>null,setInterval:(fn,delay)=>{{timers.push({{fn,delay}});return timers.length}}}};",
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


def test_project_surface_coordinator_ignores_delayed_a_responses_and_refreshes_b_once() -> None:
    session_path = json.dumps(str(DASHBOARD / "review-session.js"))
    _run_node(
        "\n".join(
            [
                f"const ui=require({session_path});",
                "const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};",
                "const until=async predicate=>{for(let index=0;index<20;index+=1){if(predicate())return;await new Promise(resolve=>setImmediate(resolve));}throw new Error('condition not reached')};",
                "(async()=>{",
                " let selected='A';const mutationA=deferred();const mutationLoads=[];const mutationRendered=[];",
                " const mutationCoordinator=ui.createProjectSurfaceCoordinator({getProjectId:()=>selected,load:id=>{const call={id,...deferred()};mutationLoads.push(call);return call.promise},render:value=>mutationRendered.push(value)});",
                " const mutationRun=mutationCoordinator.mutate(id=>{if(id!=='A')throw new Error(`wrong mutation ${id}`);return mutationA.promise},{renderResult:value=>mutationRendered.push(value)});",
                " selected='B';const mutationChange=mutationCoordinator.projectChanged();mutationCoordinator.refresh();mutationA.resolve('A mutation response');",
                " await until(()=>mutationLoads.length===1);if(mutationLoads[0].id!=='B')throw new Error(JSON.stringify(mutationLoads));mutationLoads[0].resolve('B refresh response');",
                " await Promise.all([mutationRun,mutationChange]);if(JSON.stringify(mutationRendered)!==JSON.stringify(['B refresh response']))throw new Error(`A mutation leaked ${JSON.stringify(mutationRendered)}`);",
                " if(mutationLoads.length!==1)throw new Error(`B mutation refresh count ${mutationLoads.length}`);",
                " selected='A';const getLoads=[];const getRendered=[];",
                " const getCoordinator=ui.createProjectSurfaceCoordinator({getProjectId:()=>selected,load:id=>{const call={id,...deferred()};getLoads.push(call);return call.promise},render:value=>getRendered.push(value)});",
                " const getA=getCoordinator.refresh();await until(()=>getLoads.length===1);selected='B';const getChange=getCoordinator.projectChanged();getCoordinator.refresh();",
                " getLoads[0].resolve('A delayed GET');await until(()=>getLoads.length===2);if(getLoads[1].id!=='B')throw new Error(JSON.stringify(getLoads));getLoads[1].resolve('B current GET');",
                " await Promise.all([getA,getChange]);if(JSON.stringify(getRendered)!==JSON.stringify(['B current GET']))throw new Error(`A GET leaked ${JSON.stringify(getRendered)}`);",
                " if(getLoads.filter(call=>call.id==='B').length!==1)throw new Error(`B GET count ${getLoads.length}`);",
                "})().catch(error=>{console.error(error);process.exit(1)});",
            ]
        )
    )


def test_evidence_and_synthesis_route_all_async_rendering_through_project_guard() -> None:
    for filename in ("review-evidence.js", "review-synthesis.js"):
        source = (DASHBOARD / filename).read_text(encoding="utf-8")
        assert "ReviewSessionUI.createProjectSurfaceCoordinator" in source
        assert 'projectSelect.addEventListener("change", coordinator.projectChanged)' in source
        assert 'document.addEventListener("DOMContentLoaded", coordinator.refresh)' in source

    evidence = (DASHBOARD / "review-evidence.js").read_text(encoding="utf-8")
    synthesis = (DASHBOARD / "review-synthesis.js").read_text(encoding="utf-8")
    assert "renderResult: render" in evidence
    assert "refreshAfterSuccess: true" in synthesis


def test_review_page_uses_refresh_scheduler_instead_of_fixed_interval() -> None:
    html = (DASHBOARD / "review.html").read_text(encoding="utf-8")
    assert "ReviewSessionUI.createProjectRefreshScheduler" in html
    assert "setInterval(refreshProjects, 3000)" not in html
    assert html.count("startProjectsRefresh();") == 1
