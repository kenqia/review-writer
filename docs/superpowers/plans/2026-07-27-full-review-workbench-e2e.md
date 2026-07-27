# Full Review Workbench E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing localhost review workbench so a researcher can move from QoderWork-created Review Brief through one ZIP upload, automatic progress, Risk Packet, evidence-linked manuscript editing, and DOCX export without seeing internal files or commands.

**Architecture:** Keep `serve_review_dashboard.py`, `review.html`, the current project state, and the existing Expert Kit as the only product path. Add one bounded project-local ZIP inbox and derive all visible source/progress states from existing project artifacts; do not add a second state model or browser-side workflow engine.

**Tech Stack:** Python standard library `http.server`, existing `review_writer` project/acquisition modules, vanilla HTML/CSS/JavaScript, `unittest`, existing Makefile checks, real localhost browser smoke.

---

## File map

- Modify `view/serve_review_dashboard.py`: zero-project startup, researcher-safe source/progress payloads, bounded atomic ZIP inbox route.
- Modify `view/assets/dashboard/review.html`: empty state, stage-adaptive source/progress/Risk Packet UI, polling, ZIP drag/drop.
- Modify `view/assets/dashboard/review-ui.css`: approved paper-white/deep-green stage layouts and responsive behavior.
- Modify `qoderwork/plugins/research-review-writer/skills/research-review-writer/SKILL.md`: observe and consume the fixed inbox in the existing automatic stage.
- Modify `tests/test_qoderwork_native_review_writer.py`: backend/API/UI/Expert Kit regression coverage.
- Rebuild ignored artifact `dist/research-review-writer-0.2.3.zip`: current Expert Kit package for E2E preparation; do not commit the ZIP.

No new runtime module, schema, frontend framework, project database, state file, Agent, or generic infrastructure is created.

### Task 1: Zero-project startup and automatic project discovery

**Files:**
- Modify: `tests/test_qoderwork_native_review_writer.py`
- Modify: `view/serve_review_dashboard.py`
- Modify: `view/assets/dashboard/review.html`
- Modify: `view/assets/dashboard/review-ui.css`

- [ ] **Step 1: Write failing zero-project server and UI tests**

Add tests that create an empty review root, assert `run()` reaches `ThreadingHTTPServer` instead of returning error 2, and assert the workbench contains a visible waiting state plus project polling:

```python
def test_dashboard_starts_without_projects_and_exposes_empty_project_list(self) -> None:
    from view import serve_review_dashboard as dashboard
    with tempfile.TemporaryDirectory() as temp_dir:
        review_root = Path(temp_dir) / "review-root"
        review_root.mkdir()
        status, _, body = self._request(
            dashboard,
            review_root,
            b"GET /api/projects HTTP/1.1\r\nHost: localhost\r\n\r\n",
        )
        self.assertEqual(200, status)
        self.assertEqual([], json.loads(body))
        args = argparse.Namespace(review_root=str(review_root), host="127.0.0.1", port=0)
        with patch.object(dashboard, "ThreadingHTTPServer") as server_type:
            server_type.return_value.serve_forever.side_effect = KeyboardInterrupt
            self.assertEqual(0, dashboard.run(args))

def test_review_workbench_has_researcher_facing_empty_state_and_polling(self) -> None:
    html = (ROOT / "view/assets/dashboard/review.html").read_text(encoding="utf-8")
    self.assertIn('id="empty-project-workspace"', html)
    self.assertIn("等待 QoderWork 创建科研综述", html)
    self.assertIn("setInterval(refreshProjects", html)
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_qoderwork_native_review_writer.NativeReviewWriterDashboardTests.test_dashboard_starts_without_projects_and_exposes_empty_project_list \
  tests.test_qoderwork_native_review_writer.NativeReviewWriterDashboardTests.test_review_workbench_has_researcher_facing_empty_state_and_polling
```

Expected: FAIL because `run()` rejects an empty root and the empty-state elements do not exist.

- [ ] **Step 3: Implement the minimal zero-project behavior**

Remove only the `has_dashboard_data()` startup rejection. Add `#empty-project-workspace`; update `loadProjects()` so an empty list hides project workspaces, renders the waiting state, and schedules bounded polling. When a project appears, clear the empty state and load the first project.

The JS state transition must follow this shape:

```javascript
const PROJECT_POLL_MS = 3000;
let projectPollTimer = 0;

async function refreshProjects() {
  const nextProjects = await getPayload('/api/projects');
  if (!nextProjects.length) {
    showEmptyProjectState();
    return;
  }
  hideEmptyProjectState();
  const nextId = nextProjects.some(row => row.project_id === projectId)
    ? projectId : nextProjects[0].project_id;
  projects = nextProjects;
  renderProjectOptions();
  if (nextId !== projectId) {
    projectId = nextId;
    await loadProject();
  }
}

projectPollTimer = window.setInterval(refreshProjects, PROJECT_POLL_MS);
```

- [ ] **Step 4: Run focused and existing dashboard tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tests/test_qoderwork_native_review_writer.py
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add view/serve_review_dashboard.py view/assets/dashboard/review.html \
  view/assets/dashboard/review-ui.css tests/test_qoderwork_native_review_writer.py
git commit -m "feat(review): keep empty workbench ready for projects"
```

### Task 2: Researcher-safe source queue and bounded ZIP inbox

**Files:**
- Modify: `tests/test_qoderwork_native_review_writer.py`
- Modify: `view/serve_review_dashboard.py`

- [ ] **Step 1: Write failing source payload and upload tests**

Add synthetic acquisition manifest/receipt rows under a temporary project. Assert the payload exposes only scientific fields (`study_id`, `citation`, `role`, `status`, `download_url`, `message`) and never exposes absolute paths, hashes, receipts, or internal commands.

Add raw `application/zip` request tests for:

```python
valid_zip = io.BytesIO()
with zipfile.ZipFile(valid_zip, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("study-main.pdf", b"%PDF-1.4\nsynthetic\n%%EOF\n")

request = (
    b"POST /api/project/synthetic-review/source-archive HTTP/1.1\r\n"
    b"Host: localhost\r\nContent-Type: application/zip\r\nContent-Length: "
    + str(len(valid_zip.getvalue())).encode()
    + b"\r\n\r\n"
    + valid_zip.getvalue()
)
```

Verify: 201 response, exact bytes at the fixed inbox, no temporary residue, 400 for malformed ZIP, 413 for an over-limit declared length, 404 for unknown projects, and 409 unless an existing archive is explicitly replaced with `?replace=invalid` while the project reports a source-upload blocker.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_qoderwork_native_review_writer.NativeReviewWriterDashboardTests.test_source_handoff_payload_is_researcher_safe \
  tests.test_qoderwork_native_review_writer.NativeReviewWriterDashboardTests.test_source_archive_route_publishes_one_valid_zip_atomically \
  tests.test_qoderwork_native_review_writer.NativeReviewWriterDashboardTests.test_source_archive_route_rejects_invalid_unsafe_or_unapproved_replacement
```

Expected: FAIL because source-handoff and source-archive routes do not exist.

- [ ] **Step 3: Implement source payload helpers**

Add focused helpers in `serve_review_dashboard.py`:

```python
SOURCE_ARCHIVE_RELATIVE = Path("00_sources/manual_upload/inbox/source_bundle.zip")
SOURCE_ARCHIVE_CONTENT_TYPE = "application/zip"

def safe_public_url(value: Any) -> str:
    text = visible_text(value)
    parsed = urlparse(text)
    return text if parsed.scheme in {"http", "https"} and parsed.netloc else ""

def project_source_handoff_payload(review_root: Path, project_id: str) -> dict[str, Any]:
    project = project_dir(review_root, project_id)
    receipt = read_json_if_exists(project / "00_sources/acquisition_final_receipt.json") or {}
    studies = receipt.get("studies") if isinstance(receipt, dict) else []
    studies = studies if isinstance(studies, list) else []
    sources: list[dict[str, Any]] = []
    for index, study in enumerate(row for row in studies if isinstance(row, dict)):
        label = visible_text(
            study.get("citation") or study.get("title") or study.get("doi") or study.get("study_id")
        ) or f"研究 {index + 1}"
        for role, key in (("MAIN", "main_pdf"), ("SI", "si_pdf")):
            if role == "SI" and key not in study:
                continue
            source = study.get(key) if isinstance(study.get(key), dict) else {}
            acquired = bool(visible_text(source.get("path"))) or int(source.get("bytes") or 0) > 0
            sources.append({
                "study_id": visible_text(study.get("study_id") or study.get("doi")),
                "citation": label,
                "role": role,
                "status": "已获得" if acquired else "需要上传",
                "download_url": safe_public_url(study.get(f"{role.lower()}_url")),
                "message": "全文已就绪" if acquired else f"请补充{role}文件",
            })
    return {
        "project_id": project_id,
        "sources": sources,
        "counts": {
            "total": len(sources),
            "ready": sum(row["status"] == "已获得" for row in sources),
        },
        "upload_required": any(row["status"] == "需要上传" for row in sources),
    }

def project_source_archive_path(review_root: Path, project_id: str) -> Path:
    project = project_dir(review_root, project_id)
    validate_project_path_components(project, (SOURCE_ARCHIVE_RELATIVE,))
    return project / SOURCE_ARCHIVE_RELATIVE
```

Use existing `visible_text`, `read_json_if_exists`, project path validation, and importer size constants. Do not duplicate manual archive member extraction or alias matching.

- [ ] **Step 4: Implement bounded atomic upload**

Add `POST /api/project/<id>/source-archive`. Parse a required nonnegative Content-Length, reject anything above `DEFAULT_MAX_ARCHIVE_BYTES`, stream exactly that many bytes into a same-directory temporary file, `fsync`, check `zipfile.is_zipfile`, then `os.replace()` into the fixed inbox. Return only:

```json
{
  "status": "received",
  "message": "压缩包已接收，正在核验来源。"
}
```

Do not use the request filename as a path. On error, unlink the temporary file. Do not touch project state or run Provider work in the HTTP handler.

- [ ] **Step 5: Run source tests and importer regression**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tests/test_qoderwork_native_review_writer.py
make manual-source-import-check
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add view/serve_review_dashboard.py tests/test_qoderwork_native_review_writer.py
git commit -m "feat(review): accept one bounded source archive"
```

### Task 3: Source upload and automatic scientific progress UI

**Files:**
- Modify: `tests/test_qoderwork_native_review_writer.py`
- Modify: `view/assets/dashboard/review.html`
- Modify: `view/assets/dashboard/review-ui.css`
- Modify: `view/serve_review_dashboard.py`

- [ ] **Step 1: Write failing stage UI and sanitized progress tests**

Assert the workbench contains `source-workspace`, `source-drop-zone`, `processing-workspace`, and a stage list driven by API payloads. Assert the HTML uses a raw ZIP body and does not ask for paths or mapping files:

```python
self.assertIn("body:file", review_html)
self.assertIn("Content-Type':'application/zip", review_html)
self.assertIn("source-archive", review_html)
self.assertNotIn("manifest path", visible.casefold())
self.assertNotIn("mapping file", visible.casefold())
```

Add a backend test for `project_progress_payload()` covering Brief, sources, parsing, evidence, Risk Packet, drafting, and final review. Assert stage labels and blockers are researcher-safe and derived from existing files.

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_qoderwork_native_review_writer.NativeReviewWriterDashboardTests.test_review_workbench_exposes_one_zip_drop_and_automatic_progress \
  tests.test_qoderwork_native_review_writer.NativeReviewWriterDashboardTests.test_project_progress_payload_uses_existing_artifacts_only
```

Expected: FAIL because source/progress UI and payload are absent.

- [ ] **Step 3: Add project progress payload**

Add a `progress` stage builder to the existing generic GET map. Return a bounded payload:

```python
{
    "project_id": project_id,
    "active_stage": "sources|parsing|evidence|risk|drafting|final",
    "stages": [{"id": "sources", "label": "整理文献来源", "status": "complete|active|pending|blocked"}],
    "studies": [{"label": citation_or_study_id, "status": "已获得全文|正在处理|已完成|需要补充"}],
    "blocker": "",
    "recommended_next": "后台正在核验来源",
}
```

Derive it from current state and existing artifacts. Never return command lines, paths, hashes, agent names, prompts, or receipt payloads.

- [ ] **Step 4: Implement the stage-adaptive central UI**

Add source and processing sections inside the existing cockpit center. `renderStageWorkspace()` selects Brief, sources, progress, Risk Packet, or standard cockpit from `projectState.current_stage`, source payload, progress payload, and risk target count. The user sees one recommended action.

Implement drag/drop and file picker with the same handler:

```javascript
async function uploadSourceArchive(file, replace = false) {
  if (!file || !file.name.toLowerCase().endsWith('.zip')) {
    showSourceError('请选择一个 PDF ZIP 压缩包。');
    return;
  }
  const suffix = replace ? '?replace=invalid' : '';
  await getPayload(`/api/project/${encodeURIComponent(projectId)}/source-archive${suffix}`, {
    method:'POST', headers:{'Content-Type':'application/zip'}, body:file
  });
  await loadProject();
}
```

On success switch immediately to processing copy. On error remain in source view with one correction message. Poll current-project payloads while the project is not complete; pause polling during edits or upload.

- [ ] **Step 5: Add responsive styles without changing the approved visual system**

Use the existing colors and typography. At desktop, keep left/center/right columns; below 1100px stack context below the main task; below 640px use full-width controls and horizontally scroll only tables. Ensure the drop zone, Risk controls, manuscript editor, and evidence inspector use `min-width: 0` and `overflow-wrap: anywhere`.

- [ ] **Step 6: Run focused and full native workbench tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tests/test_qoderwork_native_review_writer.py
```

Expected: all tests PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add view/serve_review_dashboard.py view/assets/dashboard/review.html \
  view/assets/dashboard/review-ui.css tests/test_qoderwork_native_review_writer.py
git commit -m "feat(review): show source handoff and live progress"
```

### Task 4: Complete Risk Packet interaction in the main workbench

**Files:**
- Modify: `tests/test_qoderwork_native_review_writer.py`
- Modify: `view/assets/dashboard/review.html`
- Modify: `view/assets/dashboard/review-ui.css`

- [ ] **Step 1: Write failing Risk Packet UI contract tests**

Assert every target renders four decisions, reword exposes one inline text field, tokens remain hidden, and one submit serializes exactly the existing API contract. Assert unresolved decisions keep drafting blocked in visible copy.

```python
for value in ("approve", "reword", "exclude", "unresolved"):
    self.assertIn(f'value="{value}"', review_html)
self.assertIn("decision_token:target.decision_token", review_html)
self.assertIn("approved_text", review_html)
self.assertIn("/risk-decisions", review_html)
self.assertIn("尚有暂缓项，完成决定后才能进入写作", review_html)
```

- [ ] **Step 2: Run focused test and confirm failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_qoderwork_native_review_writer.NativeReviewWriterDashboardTests.test_review_workbench_completes_risk_packet_in_scientific_language
```

Expected: FAIL because the current workbench only previews risk targets.

- [ ] **Step 3: Implement Risk Packet rendering and submission**

Render each target as one scientific decision article with claim, evidence summary, excerpt, page, categories, and decision radios. Keep `decision_token` only in JS memory. Reword toggles its text input. Submit all targets once:

```javascript
const decisions = riskPayload.targets.map(target => ({
  target_id: target.target_id,
  decision: selectedRiskDecision(target.target_id),
  ...(selectedRiskDecision(target.target_id) === 'reword'
    ? {approved_text:riskRewordText(target.target_id)} : {}),
  decision_token: target.decision_token
}));
await getPayload(`/api/project/${encodeURIComponent(projectId)}/risk-decisions`, {
  method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({decisions})
});
```

Reject empty reword text in the browser before request. After save, reload the canonical risk payload. If any target is unresolved, show the blocker and do not claim writing has started.

- [ ] **Step 4: Run Risk and complete native workbench tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tests/test_qoderwork_native_review_writer.py
```

Expected: all tests PASS, including existing backend fail-closed decision tests.

- [ ] **Step 5: Commit Task 4**

```bash
git add view/assets/dashboard/review.html view/assets/dashboard/review-ui.css \
  tests/test_qoderwork_native_review_writer.py
git commit -m "feat(review): complete scientific risk decisions in workbench"
```

### Task 5: Expert Kit inbox handoff and complete local verification

**Files:**
- Modify: `qoderwork/plugins/research-review-writer/skills/research-review-writer/SKILL.md`
- Modify: `tests/test_qoderwork_native_review_writer.py`
- Verify: `view/serve_review_dashboard.py`
- Verify: `view/assets/dashboard/review.html`
- Verify: `view/assets/dashboard/review-ui.css`

- [ ] **Step 1: Write the failing Expert Kit handoff test**

Add assertions that the skill tells the same QoderWork task to observe the exact project-relative inbox, import it once, and continue immediately without asking the user for a path or another “continue” action:

```python
self.assertIn("00_sources/manual_upload/inbox/source_bundle.zip", skill)
self.assertIn("同一个任务", skill)
self.assertIn("不要求研究者再次点击继续", skill)
self.assertNotIn("请提供 ZIP 路径", skill)
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_qoderwork_native_review_writer.NativeReviewWriterPluginTests.test_expert_kit_consumes_dashboard_source_inbox
```

Expected: FAIL because the current skill does not bind the fixed inbox.

- [ ] **Step 3: Update only the existing automatic corpus/evidence instructions**

State that after publishing the consolidated HTML queue, the same task observes:

```text
review-projects/<project_id>/00_sources/manual_upload/inbox/source_bundle.zip
```

When it appears, call the existing manual importer exactly once, then verify-only acquisition and continue to MinerU. Do not add a new Agent, prompt, receipt, schema, retry, fallback, browser robot, or user checkpoint.

- [ ] **Step 4: Run fresh repository checks**

Run:

```bash
make qoderwork-native-review-check
make manual-source-import-check
make smoke
make quality-check
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 5: Build and validate the current Expert Kit**

Run:

```bash
make qoderwork-plugin-package OUTPUT_ZIP=dist/research-review-writer-0.2.3.zip
python3 -m zipfile -t dist/research-review-writer-0.2.3.zip
```

Expected: plugin package build exits 0 and ZIP test reports `Done testing`.

- [ ] **Step 6: Start a clean localhost engineering smoke environment**

Use a fresh ignored Windows-native directory with no project data. Start:

```bash
python3 view/serve_review_dashboard.py \
  --review-root /mnt/c/Users/26960/QW-RW-E2E-V1/review-writer \
  --host 127.0.0.1 --port 44061
```

Expected: server stays up with zero projects and `/review` shows the waiting state.

- [ ] **Step 7: Perform supplemental browser smoke only**

Use the real browser to verify desktop and narrow viewport behavior with isolated synthetic fixtures: empty state, Brief, ZIP upload, processing, Risk Packet, manuscript locator, scientific pending review/restore, DOCX export. Do not create or manipulate the user’s real E2E project, and report only `DEMO_V0_ENGINEERING_SMOKE=PASS|FAIL`.

- [ ] **Step 8: Commit Task 5**

```bash
git add qoderwork/plugins/research-review-writer/skills/research-review-writer/SKILL.md \
  tests/test_qoderwork_native_review_writer.py
git commit -m "feat(review): connect expert kit to source inbox"
```

### Task 6: Prepare, but do not perform, the human E2E

**Files:**
- No tracked file changes.

- [ ] **Step 1: Confirm clean tracked state and identify deliverables**

Run:

```bash
git status --short --branch
git log -6 --oneline
sha256sum dist/research-review-writer-0.2.3.zip
```

Expected: clean tracked worktree; only ignored E2E data/build artifacts may exist.

- [ ] **Step 2: Stop before impersonating the user**

Report exactly:

- QoderWork clean working directory;
- current Expert Kit ZIP;
- localhost URL;
- the first single UI action: create the new project in QoderWork with `/research-review-writer` and a natural-language topic.

Do not create the QoderWork task, send the scientific request, confirm Brief, upload ZIP, decide Risk Packet, edit manuscript, or export DOCX for the user.

The final status remains:

```text
FULL_NEW_PROJECT_E2E=PENDING_HUMAN_ACCEPTANCE
```

until the user personally completes every interface checkpoint and opens the DOCX.
