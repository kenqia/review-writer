# Three-paper Evidence-to-Release Complete Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 WSL 中用三篇可见光烯烃双官能团化论文完成新的 Parse Quality → Paper Evidence → Synthesis → Manuscript → internal DOCX → gold-standard evaluation 全流程，并通过两轮相互独立的 Playwright 模拟研究者验收证明流程可恢复、可追溯且不会复用旧 QoderWork 稿冒充新成果。

**Architecture:** Source Truth 和 Parse Quality 继续作为来源真源；旧 `evidence_cards.jsonl`、`claim_projection.jsonl`、`risk_packet.json`、`writer_packet.json` 和 `first_draft.md` 只允许经只读 adapter 生成候选或差距基线，不能授权新路线。新增持久化 Paper Evidence、Comparison Protocol、Coverage Map、Synthesis Claim、Section Contract、Source Figure、Synthesis Figure Placeholder、manuscript lineage v2、统一 workflow projection 和 impact invalidation；Dashboard、CLI、DOCX export 和 evaluation 共用同一权威投影。原论文图片是内部稿的主要视觉材料；跨论文综合图只产生制图占位符和 brief。

**Tech Stack:** Python 3.13 标准库、现有 JSON Schema validator、Pillow、现有 Markdown→DOCX exporter、`http.server` Dashboard、原生 HTML/CSS/JavaScript、pytest/unittest、WSL zsh、Codex subagents、Playwright Inline Execution。

---

## 执行授权与不可变边界

本计划已获得以下明确授权：

1. 所有开发、运行、浏览器和真实案例操作均在 WSL 中完成，主实现者是 Codex。
2. Playwright Agent 可以在真实三篇模拟项目中保存决定；其决定直接构成本次模拟流程的最终科学批准，但 actor 必须记录为 `simulated_researcher_agent`，不得冒充肯恰大人本人。
3. Playwright Agent 发现缺少候选证据、综合判断或章节草稿时，向主 Agent 返回结构化 `CONTENT_AGENT_REQUEST`；只有主 Agent 派发独立 Content Agent，浏览器 Agent 不读仓库、不运行 shell、不直接生成候选内容。
4. Content Agent 可以读取三篇项目中已绑定的本地 PDF、MinerU Markdown、页面/图片 sidecar 和经过验证的任务包；不得读取 token、cookie、auth、session 或其他项目。
5. 原论文 Source Figure 可直接用于内部模拟稿，不要求许可证检查；必须保留论文、页码、图号、caption 和文件 hash 绑定。
6. 综合图不得由系统生成、重绘、拼接或补画。源论文没有能够承担跨研究表达任务的图片时，系统生成 `SYNTHESIS_FIGURE_PLACEHOLDER` 与制图 brief。
7. 允许导出含明确综合图占位符的 `SELF_REVIEWED_DRAFT`；只要必需综合图未由用户制作、上传和验收，就禁止 `EXPERT_REVIEWED_RELEASE`。
8. 不进行远端 Git 写入、部署、发布、额外文献发现或批量网络抓取。任何 repo commit 均只在当前本地 worktree。

## 成功产物与本轮非目标

成功产物：

```text
vis-light-olefin-difunctionalization-complete-loop-v1/
├── 01_evidence/paper_evidence_projection.jsonl
├── 02_synthesis/comparison_protocol.json
├── 02_synthesis/coverage_map.json
├── 02_synthesis/synthesis_claim_projection.jsonl
├── 02_synthesis/section_contracts.jsonl
├── 03_figures/source_figure_registry.json
├── 03_figures/synthesis_figure_placeholders.json
├── 04_manuscript/manuscript.md
├── 04_manuscript/manuscript_lineage.v2.json
├── 05_release/self_reviewed_draft.docx
├── 05_release/release_snapshot.json
└── 06_evaluation/review_benchmark_report.json
```

完成门槛：

- 三篇 Parse Quality Gate 均闭合且不 stale；
- 新 evidence 全部绑定当前 Source Truth/Parse object digest；
- Comparison Protocol、Synthesis Claims 和 Section Contracts 已由模拟研究者批准；
- 所有高风险 manuscript claim 已完成模拟人工编辑批准；
- 目标 5–8 个图位，至少每篇论文有 1 个被选中的 Source Figure；只有跨论文表达确实无法由原图承担时才使用 placeholder；
- 新 Markdown 与旧稿 SHA-256 不同，新 DOCX 的 `word/document.xml` 与旧 DOCX 不同；
- `SELF_REVIEWED_DRAFT` 达到 80/100 且无适用于内部稿的 Hard Fail；
- 两轮相互独立的 Playwright Agent 完成全流程与回归。

本轮不做：大规模 discovery、增加论文数量、投稿级版权清算、用户制作综合图、`EXPERT_REVIEWED_RELEASE`、远端发布或通用多租户 Agent orchestration。

## 权威兼容规则

| 项目类型 | Evidence/Synthesis 真源 | Manuscript 真源 | Release 路径 |
| --- | --- | --- | --- |
| 含 Source Truth 的新路线项目 | 新 v1 对象与决定 | `04_manuscript/manuscript.md` + lineage v2 | 新 workflow projection，严格 fail-closed |
| 无 Source Truth 的 legacy fixture | 现有 projection/risk | `04_first_draft/first_draft.md` + lineage v1 | 保持现有兼容测试 |
| 含 Source Truth 但只有旧下游产物 | 旧产物仅作 candidate adapter | 旧稿只显示为历史基线 | 不得导出新路线 DOCX |

## 计划状态合同

执行者每完成一个 Task，必须立即把该 Task 的 checkbox 更新并在下表更新状态；不得等到最后一次性勾选。

| Milestone | Implemented | Target tests | Real case | Playwright | Owner-visible result |
| --- | --- | --- | --- | --- | --- |
| M1 authority + parse closure | complete (Tasks 1-3) | Task 3 target set: 270 passed; smoke + quality-check pass | clean project + standards archived; 11/11 parse decisions persisted | pre/post-restart pass | parse closed; release still blocked by downstream workflow |
| M2 evidence + figures | pending | pending | pending | pending | pending |
| M3 synthesis + section contracts | pending | pending | pending | pending | pending |
| M4 manuscript + internal DOCX | pending | pending | pending | pending | pending |
| M5 benchmark + independent regression | pending | pending | pending | pending | pending |

---

### Task 1: 固化基线、无覆盖创建新案例并归档标杆

**Files:**

- Create: `scripts/review/create_three_paper_complete_loop.py`
- Create: `scripts/review/archive_standard_corpus.py`
- Create: `schemas/quality/standard_corpus_manifest.v1.schema.json`
- Create: `tests/test_three_paper_complete_loop_bootstrap.py`
- Create external: `/home/kenqia/my_folder/review-writer-data/review-projects/vis-light-olefin-difunctionalization-complete-loop-v1`
- Create external: `/home/kenqia/my_folder/review-writer-data/template-papers/standards/20260728/`

- [x] **Step 1: 写失败测试锁定复制白名单和旧产物隔离**

```python
def test_bootstrap_copies_only_source_and_parse_inputs(tmp_path: Path) -> None:
    source = legacy_three_paper_fixture(tmp_path / "source")
    target = tmp_path / "target"
    create_complete_loop_project(source, target)
    assert (target / "00_sources/acquisition_final_receipt.json").is_file()
    assert (target / "01_evidence/mineru/manifest.json").is_file()
    assert not (target / "01_evidence/evidence_cards.jsonl").exists()
    assert not (target / "02_claims").exists()
    assert not (target / "04_first_draft").exists()
    assert not (target / "05_final_audit").exists()


def test_bootstrap_refuses_existing_target_without_writing(tmp_path: Path) -> None:
    source = legacy_three_paper_fixture(tmp_path / "source")
    target = tmp_path / "target"
    target.mkdir()
    before = directory_snapshot(target)
    with pytest.raises(BootstrapError, match="TARGET_EXISTS"):
        create_complete_loop_project(source, target)
    assert directory_snapshot(target) == before


def test_standard_archive_is_non_overwriting_and_hash_manifested(tmp_path: Path) -> None:
    source = standard_parse_fixture(tmp_path / "source", pdf_count=14)
    target = tmp_path / "standards"
    manifest = archive_standard_corpus(source, target, source_zip_sha256=STANDARD_ZIP_SHA256)
    assert manifest["pdf_count"] == 14
    assert manifest["source_zip_sha256"] == STANDARD_ZIP_SHA256
    assert all(row["sha256"] for row in manifest["files"])
    with pytest.raises(StandardArchiveError, match="TARGET_EXISTS"):
        archive_standard_corpus(source, target, source_zip_sha256=STANDARD_ZIP_SHA256)
```

- [x] **Step 2: 运行测试确认失败**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_three_paper_complete_loop_bootstrap.py
```

Expected: FAIL，bootstrap 模块不存在。

- [x] **Step 3: 实现非覆盖 bootstrap**

允许复制的相对根目录固定为：

```python
COPY_ROOTS = (
    Path("00_brief"),
    Path("00_discovery"),
    Path("00_sources"),
    Path("01_evidence/mineru"),
    Path("01_evidence/parses"),
    Path("01_evidence/text_layers"),
)
FORBIDDEN_ROOTS = (
    Path("01_evidence/evidence_cards.jsonl"),
    Path("02_claims"),
    Path("03_review"),
    Path("03_figure_redraw"),
    Path("04_first_draft"),
    Path("05_final_audit"),
)
```

目标先写入同级随机临时目录，完成 PDF 数量、receipt、MinerU manifest 和 text-layer manifest 校验后再 `os.replace()`；目标已存在、输入含 symlink/reparse point 或任何禁止路径进入临时副本时均 fail-closed。

- [x] **Step 4: 创建真实新项目并重新构建 Source Truth/Parse Gate**

```zsh
source_case=/home/kenqia/my_folder/review-writer-data/review-projects/vis-light-olefin-difunctionalization-wsl-v1
target_case=/home/kenqia/my_folder/review-writer-data/review-projects/vis-light-olefin-difunctionalization-complete-loop-v1
test -d "$source_case"
test ! -e "$target_case"
PYTHONDONTWRITEBYTECODE=1 python3 scripts/review/create_three_paper_complete_loop.py \
  --source "$source_case" --target "$target_case"
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_vertical_review.py \
  build-source-truth --project "$target_case"
```

Expected: 3 PDF、3 bundle、3 `needs_review` gate，且目标中没有旧 evidence/claim/draft/release。

- [x] **Step 5: 校验并归档标杆资产**

先验证仓库外原始包：

```zsh
sha256sum 标准.zip
```

Expected SHA-256:

```text
92d2546f71d8751d2d150f125cca0e19c801e7c2fffed6ecca2e61c104d90d3e
```

若 `/tmp/review-writer-standards.UO9hi7/mineru-outputs/` 存在，运行：

```zsh
standards_source=/tmp/review-writer-standards.UO9hi7/mineru-outputs
standards_target=/home/kenqia/my_folder/review-writer-data/template-papers/standards/20260728
test -d "$standards_source"
test ! -e "$standards_target"
PYTHONDONTWRITEBYTECODE=1 python3 scripts/review/archive_standard_corpus.py \
  --source "$standards_source" --source-zip 标准.zip --target "$standards_target"
```

脚本先在同级临时目录复制并生成 `standard_corpus_manifest.json`，再原子发布目标；要求 14/14 PDF、1,071 个文件和所有文件 hash 一致。临时源不存在时停止本 Step，报告 `STANDARD_PARSE_SOURCE_MISSING`；不得用旧文档中的 `<LEGACY_USER_HOME>/...` 路径代替。

- [x] **Step 6: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_three_paper_complete_loop_bootstrap.py tests/test_source_truth.py
git add -- scripts/review/create_three_paper_complete_loop.py \
  scripts/review/archive_standard_corpus.py \
  schemas/quality/standard_corpus_manifest.v1.schema.json \
  tests/test_three_paper_complete_loop_bootstrap.py
git diff --cached --check
git commit -m "feat: bootstrap clean three-paper review loop"
```

---

### Task 2: 增加 actor 决定合同、对象级 digest 和统一 workflow projection

**Files:**

- Create: `schemas/project/verification_decision.v1.schema.json`
- Create: `review_writer/project/verification_decision.py`
- Create: `review_writer/project/workflow_projection.py`
- Create: `tests/test_workflow_projection.py`
- Modify: `review_writer/project/parse_quality.py`
- Modify: `review_writer/project/source_truth.py`
- Modify: `schemas/evidence/parse_quality_gate.v1.schema.json`
- Modify: `tests/test_parse_quality.py`
- Modify: `tests/test_source_truth.py`

- [x] **Step 1: 写失败测试锁定模拟 actor、对象级失效和 fail-closed 投影**

```python
def test_simulated_agent_decision_records_actor_without_impersonating_owner() -> None:
    decision = verification_decision(
        actor_type="simulated_researcher_agent",
        actor_label="playwright-reviewer-round-1",
        action="approve",
        reason="Compared the candidate with the original PDF.",
        bound_object_digest="a" * 64,
    )
    assert decision["actor_type"] == "simulated_researcher_agent"
    assert "kenqia" not in json.dumps(decision).casefold()


def test_one_parse_object_change_invalidates_only_dependent_evidence(
    complete_loop_project: Path,
) -> None:
    before = workflow_state(complete_loop_project)
    mutate_one_parse_object_fixture(complete_loop_project, kind="table_structure")
    after = workflow_state(complete_loop_project)
    assert before["paper_evidence_ready"] is True
    assert after["paper_evidence_ready"] is False
    assert after["affected_object_ids"] == [TABLE_OBJECT_ID]


def test_source_truth_project_never_uses_legacy_files_as_completion(
    source_truth_project_with_legacy_release: Path,
) -> None:
    state = workflow_state(source_truth_project_with_legacy_release)
    assert state["active_stage"] == "parsing"
    assert state["internal_draft_export_ready"] is False
```

- [x] **Step 2: 运行失败测试**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_parse_quality.py tests/test_workflow_projection.py
```

Expected: FAIL，object digest 与统一 projection 尚不存在。

- [x] **Step 3: 为 Parse object 增加稳定 digest**

每个对象新增：

```python
object_digest = canonical_digest({
    "source_id": source_id,
    "kind": kind,
    "status": status,
    "issues": issues,
})
```

决定同时绑定 `gate_digest` 与 `object_digest`。兼容读取旧决定时，缺 `object_digest` 一律视为 stale；不得自动升级。

- [x] **Step 4: 实现唯一权威投影**

`workflow_state(project)` 固定返回：

```python
{
    "schema_version": "evidence-to-release-workflow-state.v1",
    "route": "evidence-to-release.v1" | "legacy",
    "active_stage": "sources" | "parsing" | "evidence" | "synthesis" | "drafting" | "final",
    "parse_ready": bool,
    "paper_evidence_ready": bool,
    "synthesis_ready": bool,
    "section_contracts_ready": bool,
    "manuscript_ready": bool,
    "internal_draft_export_ready": bool,
    "verified_release_ready": bool,
    "blockers": list[str],
    "workflow_digest": str,
}
```

含 `01_evidence/source_truth/` 的项目强制走新路线；任何未知、损坏、缺失或 stale 状态均 fail-closed。receipt 声明的研究集合必须与 Source Truth 目录严格一致。legacy 项目保持旧逻辑，但新路线模块禁止调用 legacy completion 推断。在 Paper Evidence、Synthesis、Manuscript 和 Release 各自的正式 schema validator 接入前，对应 capability 固定为 `False`，不得按同名文件存在或浅层字段猜测完成。

- [x] **Step 5: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_parse_quality.py tests/test_workflow_projection.py
git add -- schemas/project/verification_decision.v1.schema.json \
  schemas/evidence/parse_quality_gate.v1.schema.json \
  review_writer/project/verification_decision.py \
  review_writer/project/parse_quality.py review_writer/project/source_truth.py \
  review_writer/project/workflow_projection.py tests/test_parse_quality.py \
  tests/test_source_truth.py tests/test_workflow_projection.py
git diff --cached --check
git commit -m "feat: add authoritative review workflow projection"
```

---

### Task 3: 修复 DOCX 绕过门禁并关闭真实 Parse Quality

**Files:**

- Modify: `review_writer/delivery/project_release.py`
- Modify: `view/serve_review_dashboard.py`
- Modify: `view/assets/dashboard/review.html`
- Modify: `tests/test_project_release.py`
- Modify: `tests/test_qoderwork_native_review_writer.py`
- Create: `docs/qa/three-paper-parse-closure-playwright.md`

- [x] **Step 1: 写后端和前端失败测试**

```python
def test_source_truth_project_export_rejects_incomplete_parse_without_touching_release(
    tmp_path: Path,
) -> None:
    project = source_truth_release_fixture(tmp_path, parse_ready=False)
    before = release_file_snapshot(project)
    with pytest.raises(ProjectReleaseError, match="PARSE_QUALITY_NOT_READY"):
        build_project_release(project)
    assert release_file_snapshot(project) == before


def test_export_button_uses_server_capability_and_stays_disabled() -> None:
    html = dashboard_html()
    assert "release_capabilities.internal_draft_export_ready" in html
    assert "button.disabled = !releaseCapabilities.internal_draft_export_ready" in html
```

- [x] **Step 2: 运行测试确认失败**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_project_release.py -k 'parse or export' \
  tests/test_qoderwork_native_review_writer.py -k 'parse or export'
```

- [x] **Step 3: 在前后端接入 workflow projection**

新路线 `build_project_release()` 首行读取 `workflow_state()`；`internal_draft_export_ready=False` 时抛稳定 code 且不创建、覆盖或更新时间戳。Dashboard API 把 `release_capabilities` 投影给 UI，前端 `finally` 不得无条件重新启用按钮。

- [x] **Step 4: 编写 Parse closure Playwright 合同**

协议允许 `simulated_researcher_agent` 在真实新项目中逐项比较 PDF 与解析文本并保存全部异常对象决定。每项可选：

- 确认候选解析，仅在可通过可见 PDF 核对时使用；
- 仅原始 PDF 人工定位，在解析文本不可靠但原 PDF 可用时使用；
- 必须重新解析，在 PDF 与解析均不足时使用。

每个决定必须有具体理由；禁止批量全选同一动作、禁止读取内部 JSON、禁止直接调用 API。

- [x] **Step 5: 派发独立 Playwright Agent 关闭三篇 gate**

只给 Agent：URL、项目名、模拟研究者 persona、协议。Agent 完成 11 个异常对象，刷新后验证，再向主 Agent报告 `READY_FOR_SERVER_RESTART`。主 Agent只重启自己启动的 dashboard，Agent 再验证持久化。

Expected: 3 studies、21 objects、`needs_review=0`、`workflow_can_continue=true`；`automatic_extraction_allowed` 可因 `pdf_locator_only` 保持部分 false。

- [x] **Step 6: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_parse_quality.py tests/test_workflow_projection.py \
  tests/test_project_release.py tests/test_qoderwork_native_review_writer.py
git add -- review_writer/delivery/project_release.py view/serve_review_dashboard.py \
  view/assets/dashboard/review.html tests/test_project_release.py \
  tests/test_qoderwork_native_review_writer.py \
  docs/qa/three-paper-parse-closure-playwright.md
git diff --cached --check
git commit -m "fix: block release until parse review closes"
```

---

### Task 4: 实现 Typed Paper Evidence、人工 PDF evidence 和 legacy candidate adapter

**Files:**

- Create: `schemas/evidence/paper_evidence.v1.schema.json`
- Create: `schemas/evidence/evidence_decision.v1.schema.json`
- Create: `review_writer/project/paper_evidence.py`
- Create: `review_writer/project/legacy_evidence_adapter.py`
- Create: `tests/test_paper_evidence.py`
- Modify: `review_writer/project/workflow_projection.py`
- Modify: `scripts/run_vertical_review.py`
- Modify: `tests/test_vertical_review_projection.py`

- [x] **Step 1: 写失败测试锁定认识论类型、当前 digest 和人工 PDF 路径**

```python
def test_paper_evidence_requires_epistemic_type() -> None:
    with pytest.raises(PaperEvidenceError, match="EPISTEMIC_TYPE_REQUIRED"):
        register_paper_evidence_candidates(PROJECT, STUDY_ID, candidate_without_type())


def test_review_synthesis_is_forbidden_in_single_paper_evidence() -> None:
    with pytest.raises(PaperEvidenceError, match="EPISTEMIC_TYPE_INVALID"):
        register_paper_evidence_candidates(PROJECT, STUDY_ID, candidate(epistemic_type="review_synthesis"))


def test_pdf_locator_only_accepts_manual_hash_bound_evidence() -> None:
    project = pdf_locator_only_project()
    row = register_manual_pdf_evidence(project, manual_pdf_payload(page=3))
    assert row["locator"]["source_mode"] == "original_pdf_manual"
    assert row["source_pdf_sha256"] == current_source_pdf_sha256(project)


def test_legacy_approved_claim_becomes_unapproved_candidate() -> None:
    adapted = adapt_legacy_evidence(legacy_card(decision="APPROVED"))
    assert adapted["origin"] == "legacy_candidate"
    assert adapted["status"] == "needs_review"
    assert "epistemic_type" not in adapted
```

- [x] **Step 2: 定义 Paper Evidence 合同**

每条 evidence 固定包含：

```python
{
    "evidence_id": str,
    "study_id": str,
    "source_id": str,
    "epistemic_type": "experimental_observation" | "author_interpretation" | "proposed_mechanism",
    "statement": str,
    "locator": {
        "source_mode": "parsed_candidate" | "original_pdf_manual",
        "page": int,
        "section_or_item": str,
        "figure_or_table": str | None,
        "exact_quote": str | None,
    },
    "reported_conditions": list[str],
    "quantitative_results": list[str],
    "limitations": list[str],
    "mechanism_grade": "not_applicable" | "proposal" | "indirect_support" | "direct_support",
    "risk_classes": list[str],
    "bound_parse_object_digests": list[str],
    "source_pdf_sha256": str,
    "candidate_digest": str,
    "decision": VerificationDecision | None,
}
```

目录：

```text
01_evidence/<study_id>/paper_evidence_candidates.json
01_evidence/paper_evidence_decisions.jsonl
01_evidence/paper_evidence_projection.jsonl
```

- [x] **Step 3: 实现注册、决定、状态和局部失效接口**

公开接口固定为：

```python
register_paper_evidence_candidates(project, study_id, payload) -> dict
register_manual_pdf_evidence(project, payload) -> dict
apply_paper_evidence_decision(project, payload) -> dict
paper_evidence_state(project) -> dict
require_paper_evidence_ready(project) -> str
```

决定动作固定为 `approve`、`revise_and_approve`、`reject`。`revise_and_approve` 必须携带替代表述；决定绑定 candidate digest、所依赖 parse object digests 与 source PDF hash。上游变化只使依赖行 stale。

- [x] **Step 4: 把旧下游降为只读候选**

adapter 可读取旧卡片中的候选文本、locator 和风险提示，但输出必须带 `legacy_origin`、`needs_reverification`；不得继承旧 `APPROVED`，不得补造 epistemic type、parse digest、counter-evidence 或 comparison axis。

- [x] **Step 5: 添加 CLI**

```text
register-paper-evidence --project <path> --study-id <id> --input <json>
register-manual-pdf-evidence --project <path> --input <json>
record-paper-evidence --project <path> --input <json>
```

CLI stdout 只返回计数、状态和 reason code，不输出 quote、路径、hash 或内部 prompt。

- [x] **Step 6: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_paper_evidence.py tests/test_vertical_review_projection.py \
  tests/test_evidence_atom_vertical_slice.py tests/test_evidence_grounding_v2.py
git add -- schemas/evidence/paper_evidence.v1.schema.json \
  schemas/evidence/evidence_decision.v1.schema.json \
  review_writer/project/paper_evidence.py \
  review_writer/project/legacy_evidence_adapter.py \
  review_writer/project/workflow_projection.py \
  scripts/run_vertical_review.py tests/test_paper_evidence.py \
  tests/test_vertical_review_projection.py
git diff --cached --check
git commit -m "feat: add typed paper evidence review"
```

**Task 4 completion record (2026-07-29):** Implemented and hardened in `d132dc1`.
Focused regression: 239 passed; workflow projection: 5 passed; implementation report: 244 passed.
Project checks: `make smoke`, `make quality-check`, `git diff --check` passed. Specification and code-quality reviews passed.
Two non-blocking Minor candidates remain (narrow lock/output-parent symlink-swap TOCTOU and defensive duplicate event rejection); Windows-native `msvcrt` execution remains a static-review gap.

---

### Task 5: 建立 Source Truth 绑定的原论文图注册表和综合图占位符

**Files:**

- Create: `schemas/figures/source_figure.v1.schema.json`
- Create: `schemas/figures/synthesis_figure_placeholder.v1.schema.json`
- Create: `review_writer/project/review_figures.py`
- Create: `tests/test_review_figures.py`
- Modify: `review_writer/project/vertical_review.py`
- Modify: `tests/test_vertical_review_projection.py`

- [x] **Step 1: 写失败测试锁定原图优先和禁止自动综合图**

```python
def test_source_figure_binds_asset_caption_page_and_pdf() -> None:
    registry = build_source_figure_registry(THREE_PAPER_PROJECT)
    figure = registry["figures"][0]
    assert figure["source_pdf_sha256"]
    assert figure["asset_sha256"]
    assert figure["page"] >= 1
    assert figure["caption"]


def test_new_route_never_generates_comparative_bitmap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vertical_review, "_build_comparative_evidence_figure", forbidden_call)
    packet = build_writer_packet(NEW_ROUTE_PROJECT)
    assert packet["figure_policy"] == "source_figures_or_synthesis_placeholders_only"


def test_placeholder_requires_question_panels_claims_and_limits() -> None:
    with pytest.raises(ReviewFigureError, match="PLACEHOLDER_INVALID"):
        register_synthesis_figure_placeholder(PROJECT, {"title": "Figure 1"})
```

- [x] **Step 2: 实现 Source Figure 注册表**

`build_source_figure_registry()` 从当前 bundle 的 content list、canonical image directory 和 PDF descriptor 重建逐图对象；图片集合 digest 必须与 Source Truth Bundle 中的 `images.digest` 一致。每项包含 `study_id`、`source_id`、`page`、`figure_label`、`caption`、项目相对图片路径、asset hash、PDF hash、关联 Evidence IDs 和选择状态。

- [x] **Step 3: 实现高密度但非装饰性的图预算**

真实小综述目标为 5–8 个图位：

- 三篇论文至少各选择 1 张 Source Figure；
- 科学内容密集章节至少有 1 个 Source Figure 或 placeholder；
- 同一原图不得重复占位；
- 仅在跨论文比较无法由单篇原图承担时创建 placeholder；
- 缺少适合原图时必须记录原因，不得为了凑数生成装饰图。

- [x] **Step 4: 定义 placeholder 合同**

```python
{
    "placeholder_id": str,
    "scientific_question": str,
    "reader_takeaway": str,
    "panels": [{"panel": str, "task": str, "synthesis_claim_ids": list[str], "source_figure_ids": list[str]}],
    "comparison_axis": str,
    "required_labels_units": list[str],
    "counter_evidence": list[str],
    "forbidden_overclaims": list[str],
    "unresolved_uncertainties": list[str],
    "caption_draft": str,
    "target_size": str,
    "status": "awaiting_human_figure" | "uploaded" | "verified",
}
```

- [x] **Step 5: 移除新路线自动比较图调用**

legacy 项目保留旧行为；`evidence-to-release.v1` 路线不得调用 Pillow 自动综合图函数，不得产生 `ORIGINAL_GENERATED` 科学图。

- [x] **Step 6: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_review_figures.py tests/test_vertical_review_projection.py
git add -- schemas/figures/source_figure.v1.schema.json \
  schemas/figures/synthesis_figure_placeholder.v1.schema.json \
  review_writer/project/review_figures.py review_writer/project/vertical_review.py \
  tests/test_review_figures.py tests/test_vertical_review_projection.py
git diff --cached --check
git commit -m "feat: prefer source figures and synthesis briefs"
```

**Task 5 completion record (2026-07-29):** Implemented and hardened in `37f7629` + `c68222c`.
Focused regression: 182 passed (`tests/test_review_figures.py` and `tests/test_vertical_review_projection.py`); broader Paper Evidence + projection set: 211 passed.
The new route emits source-figure references and human-owned synthesis placeholders only; current content-list hashes and `images/` containment are revalidated, and legacy comparative bitmap behavior remains outside the new route.
Independent review passed. Non-blocking follow-up: persist per-paper/section human figure selection and bind placeholder `verified` to release-gate asset/hash acceptance.

---

### Task 6: 实现 Comparison Protocol、Coverage Map、Synthesis Claim 和 Section Contract

**Files:**

- Create: `schemas/synthesis/comparison_protocol.v1.schema.json`
- Create: `schemas/synthesis/coverage_map.v1.schema.json`
- Create: `schemas/synthesis/synthesis_claim.v1.schema.json`
- Create: `schemas/synthesis/section_contract.v1.schema.json`
- Create: `review_writer/project/synthesis.py`
- Create: `review_writer/project/section_contract.py`
- Create: `tests/test_evidence_synthesis.py`
- Modify: `review_writer/project/workflow_projection.py`

- [x] **Step 1: 写失败测试锁定比较先于综合、反证和 single-study**

```python
def test_synthesis_requires_approved_comparison_protocol() -> None:
    with pytest.raises(SynthesisError, match="COMPARISON_PROTOCOL_NOT_APPROVED"):
        register_synthesis_candidates(PROJECT, synthesis_candidate())


def test_multi_study_claim_requires_two_distinct_studies() -> None:
    with pytest.raises(SynthesisError, match="MULTI_STUDY_SUPPORT_REQUIRED"):
        register_synthesis_candidates(PROJECT, candidate(supporting_study_ids=["study-a"]))


def test_single_study_claim_is_explicit_and_cannot_claim_consensus() -> None:
    with pytest.raises(SynthesisError, match="SINGLE_STUDY_OVERGENERALIZATION"):
        register_synthesis_candidates(
            PROJECT,
            candidate(single_study=True, proposition="The field generally establishes that ..."),
        )


def test_section_contract_requires_counterevidence_and_figure_plan() -> None:
    with pytest.raises(SectionContractError, match="SECTION_CONTRACT_INVALID"):
        register_section_contracts(PROJECT, contract_without_limits_or_figures())
```

- [x] **Step 2: 定义并实现 Comparison Protocol**

协议至少包含比较对象、比较轴、单位/归一化规则、缺失值处理、不可比条件、反例纳入规则、结论强度、当前 Paper Evidence projection digest 和模拟研究者决定。未批准协议时禁止注册 Synthesis Claim。

- [x] **Step 3: 实现 Coverage Map**

三篇案例的 coverage map 明确标记这是 calibration corpus，不宣称领域完整覆盖。每个比较轴列出已覆盖研究、缺失单元、不可比项、反证、已知遗漏及其对结论的影响。

- [x] **Step 4: 实现 Synthesis Claim**

每条包含 proposition、comparison axis、supporting Evidence IDs、counter Evidence IDs、applicability boundary、mechanism/evidence grade、uncertainty、risk class、single-study 标志、上游 digest 和 VerificationDecision。未批准、reject 或 stale Evidence 不得被引用。

- [x] **Step 5: 实现 Section Contract 和 writer packet**

每节 contract 包含：研究问题、比较对象/轴、预期综合判断、必须覆盖的反例/局限、Evidence/Synthesis ID 预算、Source Figure/Placeholder 计划、允许的措辞强度和决定。`build_section_writer_packet()` 只输出已批准且当前的最小字段，不输出旧稿、内部 prompt 或未批准候选。

- [x] **Step 6: 实现局部 impact invalidation**

依赖边固定为：

```text
Parse object → Paper Evidence → Synthesis Claim → Section Contract
             → Source Figure ───────────────────┘
Section Contract → Manuscript section → DOCX snapshot → benchmark report
```

上游 digest 变化只标记可达下游 stale，但任何 stale 对象都使对应 release capability fail-closed。

- [x] **Step 7: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_paper_evidence.py tests/test_evidence_synthesis.py \
  tests/test_workflow_projection.py
git add -- schemas/synthesis review_writer/project/synthesis.py \
  review_writer/project/section_contract.py tests/test_evidence_synthesis.py \
  review_writer/project/workflow_projection.py tests/test_workflow_projection.py
git diff --cached --check
git commit -m "feat: add evidence synthesis contracts"
```

**Task 6 completion record (2026-07-29):** Implemented and hardened through `aef248b`, `9e7faf8`, `f87a929`, `106c075`, `1c09c9d`, `cda03d2`, `ee9d7bc`, and `1fa15d3`.
Focused regression: 43 passed; `make quality-check` and `git diff --check` passed. Independent review passed with no Critical/Important findings.
Non-blocking follow-up: move synthesis/section read-modify-write reads inside the transaction lock, and broaden single-study overclaim detection beyond the current conservative vocabulary.

---

### Task 7: 将 Evidence + Synthesis 工作台接入同一个 Dashboard

**Files:**

- Create: `view/assets/dashboard/review-evidence.js`
- Create: `view/assets/dashboard/review-synthesis.js`
- Create: `view/assets/dashboard/review-evidence.css`
- Modify: `view/serve_review_dashboard.py`
- Modify: `view/assets/dashboard/review.html`
- Modify: `view/assets/dashboard/review-ui.css`
- Modify: `tests/test_qoderwork_native_review_writer.py`

- [x] **Step 1: 写 API 与 UI 接线失败测试**

固定 API：

```text
GET/PUT /api/project/<id>/paper-evidence
GET/PUT /api/project/<id>/comparison-protocol
GET/PUT /api/project/<id>/synthesis
GET/PUT /api/project/<id>/section-contracts
GET/PUT /api/project/<id>/review-figures
```

测试必须断言 payload 不暴露路径、hash、schema、JSON、prompt、Agent 内部 ID；PUT stale token 返回 409 且不写盘。

```python
def test_source_truth_project_evidence_payload_uses_new_projection_only(self) -> None:
    payload = dashboard.project_paper_evidence_payload(ROOT, "new-route")
    assert payload["route"] == "evidence-to-release.v1"
    assert all("epistemic_type" in row for row in payload["items"])
    assert "legacy_approved" not in json.dumps(payload)


def test_synthesis_workspace_exposes_source_figures_before_placeholders(self) -> None:
    html = dashboard_html()
    assert html.index("原论文图片") < html.index("综合图制图任务")
```

- [x] **Step 2: 拆出 Evidence 与 Synthesis 前端模块**

`review.html` 保留页面壳和通用状态；Evidence/Synthesis 交互放入两个独立 JS 文件，避免继续扩张单个内联脚本。模块只消费 safe API payload；动态文本只用 `textContent`。

- [x] **Step 3: 实现研究者工作流**

Evidence 工作区提供论文列表、PDF/parsed text 对照、epistemic type、条件/数值/机制等级、风险、原图预览、批准/修改批准/拒绝。Synthesis 工作区依次呈现 Comparison Protocol、Coverage Map、claims、反证/局限、Section Contracts 和图计划；未满足前置门禁时后续控件禁用并显示真实原因。

- [x] **Step 4: 删除新路线独立 Risk 阶段**

风险作为 Evidence/Synthesis 属性集中处理。legacy 项目继续显示旧 Risk Packet；新路线 UI 不再导航到独立 risk stage。

- [x] **Step 5: 实现响应式和可访问性**

- `1440×1000`：论文/对象列表、主审阅区、上下文三列；
- `1024×900`：两列，Context 下移；
- `390×844`：单列，PDF/图片在新标签打开；
- 固定 badge、decision control、save button、figure thumbnail 尺寸；
- 无横向滚动、文字遮挡或低于现有正文可读性的密度；
- radio、textarea、buttons 有 label、focus ring 和键盘顺序。

- [x] **Step 6: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_qoderwork_native_review_writer.py -k 'paper_evidence or synthesis or section_contract or review_figure or progress'
git add -- view/serve_review_dashboard.py view/assets/dashboard/review.html \
  view/assets/dashboard/review-ui.css view/assets/dashboard/review-evidence.js \
  view/assets/dashboard/review-synthesis.js view/assets/dashboard/review-evidence.css \
  tests/test_qoderwork_native_review_writer.py
git diff --cached --check
git commit -m "feat: add evidence synthesis workspace"
```

**Task 7 implementation record (2026-07-29):** API layer in `85ea108`, UI and hardening in `8863cb0`.
New workspace routes expose only researcher-safe projections with opaque version tokens; stale writes return 409 before mutation. Evidence and Synthesis are split into dedicated modules, Source Figures render before synthesis placeholders, and the new route hides the legacy Risk stage.
Validation: `tests/test_dashboard_evidence_workspace.py` 3 passed, native dashboard suite 120 passed, focused workspace/projection suite 23 passed, latest combined dashboard regression 123 passed, JS syntax and Python compile passed. Independent review passed after adding Coverage Map rendering, prerequisite button gating, 409 stale-domain handling, and live status accessibility.

---

### Task 8: 定义 Content Agent 请求/导入协议并完成真实 Evidence + Synthesis

**Files:**

- Create: `schemas/agents/content_agent_request.v1.schema.json`
- Create: `schemas/agents/content_agent_result.v1.schema.json`
- Create: `scripts/agent-orchestration/build_content_task_package.py`
- Create: `scripts/agent-orchestration/import_content_agent_result.py`
- Create: `tests/test_content_agent_handoff.py`
- External modify: 新三篇项目的 `01_evidence/` 与 `02_synthesis/`

- [ ] **Step 1: 写失败测试锁定角色隔离和有界输入**

```python
def test_content_task_package_contains_only_bound_project_artifacts(tmp_path: Path) -> None:
    package = build_content_task_package(PROJECT, request_for_study(STUDY_ID))
    assert package["project_id"] == PROJECT.name
    assert set(package["inputs"]) <= {"source_truth", "parse_quality", "paper_evidence", "comparison_protocol", "section_contract"}
    assert "auth" not in json.dumps(package).casefold()
    assert "04_first_draft" not in json.dumps(package)


def test_import_rejects_unrequested_objects_without_project_change(tmp_path: Path) -> None:
    before = project_snapshot(PROJECT)
    with pytest.raises(ContentAgentError, match="RESULT_OUT_OF_SCOPE"):
        import_content_agent_result(PROJECT, result_with_extra_study())
    assert project_snapshot(PROJECT) == before
```

- [ ] **Step 2: 定义浏览器 Agent 的请求格式**

```json
{
  "schema_version": "content-agent-request.v1",
  "request_kind": "paper_evidence|synthesis_claims|section_draft",
  "project_id": "vis-light-olefin-difunctionalization-complete-loop-v1",
  "target_ids": ["bounded-visible-id"],
  "reason": "Visible candidate content is missing or insufficient for review"
}
```

Playwright Agent 只能把该请求发给主 Agent。主 Agent校验当前 UI/项目状态后，派发未参与实现的 Content Agent。

- [ ] **Step 3: 定义 Content Agent 运行边界**

每个 Content Agent：

- 只读一个 `/tmp/review-writer-content-<id>/task-package/`；
- 可读取 task package 绑定的本地 PDF/Markdown/图片；
- 输出到同一临时目录的 `result.json`；
- 不直接写项目、不启动浏览器、不批准自己的候选；
- evidence Agent、synthesis Agent、section drafting Agent 分开派发；
- 输出必须经过 schema、digest、locator 和作用域校验后原子导入。

- [ ] **Step 4: 完成三篇真实 Paper Evidence**

主 Agent按 study 顺序派发三个独立 evidence Content Agent；每个生成候选 evidence 和 Source Figure 建议。导入后由 Playwright 模拟研究者在 Dashboard 中逐项核对、修改并批准。任何 `pdf_locator_only` 对象只允许人工 PDF evidence 路径。

- [ ] **Step 5: 完成真实 Comparison Protocol、Synthesis Claims 和 Section Contracts**

证据全部闭合后派发独立 synthesis Content Agent；导入 Comparison Protocol、Coverage Map、候选 Synthesis Claims、outline、Section Contracts 和 5–8 个图位计划。Playwright 模拟研究者逐项批准；高风险或冲突对象必须有具体理由，不得批量静默批准。

- [ ] **Step 6: 记录刷新和重启持久化**

Evidence 批次完成后重启一次 Dashboard；Synthesis 批次完成后再重启一次。每次由同一 Playwright Agent 刷新确认决定、理由、actor 和状态仍一致。

- [ ] **Step 7: 验证并提交代码**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_content_agent_handoff.py tests/test_paper_evidence.py \
  tests/test_evidence_synthesis.py
git add -- schemas/agents/content_agent_request.v1.schema.json \
  schemas/agents/content_agent_result.v1.schema.json \
  scripts/agent-orchestration/build_content_task_package.py \
  scripts/agent-orchestration/import_content_agent_result.py \
  tests/test_content_agent_handoff.py
git diff --cached --check
git commit -m "feat: add bounded content agent handoff"
```

---

### Task 9: 实现 manuscript lineage v2、按节起草和高风险人工编辑

**Files:**

- Create: `schemas/delivery/manuscript_lineage.v2.schema.json`
- Create: `review_writer/project/manuscript_v2.py`
- Create: `tests/test_manuscript_v2.py`
- Modify: `review_writer/delivery/project_release.py`
- Modify: `view/serve_review_dashboard.py`
- Modify: `view/assets/dashboard/review.html`
- Modify: `tests/test_project_release.py`
- Modify: `tests/test_qoderwork_native_review_writer.py`

- [ ] **Step 1: 写失败测试锁定旧稿隔离和高风险编辑**

```python
def test_new_route_draft_never_reads_legacy_first_draft(tmp_path: Path) -> None:
    project = new_route_project(tmp_path)
    (project / "04_first_draft/first_draft.md").write_text("LEGACY SENTINEL", encoding="utf-8")
    payload = build_manuscript_workspace(project)
    assert "LEGACY SENTINEL" not in json.dumps(payload)


def test_section_generation_requires_approved_contract() -> None:
    with pytest.raises(ManuscriptV2Error, match="SECTION_CONTRACT_NOT_APPROVED"):
        register_section_draft(PROJECT, unapproved_section_result())


def test_high_risk_claim_requires_simulated_human_edit_decision() -> None:
    draft = register_section_draft(PROJECT, high_risk_section())
    assert draft["status"] == "needs_human_edit"
    with pytest.raises(ManuscriptV2Error, match="HIGH_RISK_EDIT_PENDING"):
        approve_section(PROJECT, draft["section_id"], actor=None)
```

- [ ] **Step 2: 定义 lineage v2**

lineage 必须绑定 route、workflow digest、每项 parse object digest、Paper Evidence projection digest、Synthesis projection digest、Section Contract digest、section draft digest、Source Figure/Placeholder digest、generation Content Agent result digest、每个 manuscript claim 的 evidence/synthesis IDs 和当前 section approval。

- [ ] **Step 3: 实现按节导入和批准**

Content Agent 每次只得到一个 approved Section Writer Packet。`register_section_draft()` 验证所有科学句的 claim marker 均指向已批准 Paper Evidence 或 Synthesis Claim；纯过渡句可无 marker但不得包含新科学事实。高风险规则触发时状态强制 `needs_human_edit`。

- [ ] **Step 4: 实现 Dashboard 高风险编辑**

研究者直接修改正文、查看关联证据/综合判断/Source Figure、保存并批准。决定 actor 为 `simulated_researcher_agent`，同时记录原表述、新表述、理由、上游 digest 和时间。刷新/并发版本冲突返回 409，不静默覆盖。

- [ ] **Step 5: 合并 authoritative manuscript**

只有所有 Section Contract 与 section draft 当前且已批准时，原子生成：

```text
04_manuscript/manuscript.md
04_manuscript/manuscript_lineage.v2.json
```

旧 `04_first_draft/first_draft.md` 不读取、不复制、不覆盖，仅由 evaluation 读取 hash 做差距基线。

- [ ] **Step 6: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_manuscript_v2.py tests/test_project_release.py \
  tests/test_qoderwork_native_review_writer.py -k 'manuscript or draft or scientific_edit'
git add -- schemas/delivery/manuscript_lineage.v2.schema.json \
  review_writer/project/manuscript_v2.py tests/test_manuscript_v2.py \
  review_writer/delivery/project_release.py view/serve_review_dashboard.py \
  view/assets/dashboard/review.html tests/test_project_release.py \
  tests/test_qoderwork_native_review_writer.py
git diff --cached --check
git commit -m "feat: add evidence bound manuscript v2"
```

---

### Task 10: 实现双层图政策、内部 DOCX、内容完整性和下载失效

**Files:**

- Create: `review_writer/delivery/docx_integrity.py`
- Create: `tests/test_docx_integrity.py`
- Modify: `review_writer/delivery/figure_policy.py`
- Modify: `review_writer/delivery/project_release.py`
- Modify: `view/serve_review_dashboard.py`
- Modify: `view/assets/dashboard/review.html`
- Modify: `tests/test_project_release.py`
- Modify: `tests/test_qoderwork_native_review_writer.py`

- [ ] **Step 1: 写失败测试锁定双层发布和新旧稿差异**

```python
def test_internal_draft_allows_attributed_source_figures_and_visible_placeholders() -> None:
    release = build_project_release(PROJECT, release_level="SELF_REVIEWED_DRAFT")
    assert release["status"] == "SELF_REVIEWED_DRAFT"
    assert release["placeholder_count"] >= 1


def test_expert_release_rejects_unresolved_placeholder() -> None:
    with pytest.raises(ProjectReleaseError, match="FIGURE_PLACEHOLDER_PENDING"):
        build_project_release(PROJECT, release_level="EXPERT_REVIEWED_RELEASE")


def test_new_docx_internal_document_and_images_differ_from_legacy() -> None:
    result = compare_docx_to_legacy(NEW_DOCX, LEGACY_DOCX)
    assert result["document_xml_changed"] is True
    assert result["current_markdown_roundtrip_match"] is True
    assert result["legacy_repackage_only"] is False
```

- [ ] **Step 2: 扩展内部图政策**

新 figure types：

```text
SOURCE_FIGURE_INTERNAL
SYNTHESIS_FIGURE_PLACEHOLDER
HUMAN_SYNTHESIS_FIGURE
```

内部稿允许前两者；Source Figure 必须有完整 attribution 和 lineage，placeholder 必须在正文中明显显示科学问题、制图任务和未完成状态。专家发布只接受 rights-cleared Source Figure 与已验证人工综合图。

- [ ] **Step 3: 改造 release 读取路径**

新路线只读 `04_manuscript/manuscript.md` 与 lineage v2，输出：

```text
05_release/self_reviewed_draft.md
05_release/self_reviewed_draft.docx
05_release/release_snapshot.json
05_release/quality_report.json
```

legacy 路径保持原文件名与测试兼容。

- [ ] **Step 4: 实现 DOCX 内容完整性检查**

检查 ZIP 结构、`word/document.xml` 文本、relationships、media hash、figure attribution、当前 Markdown 正文规范化匹配和当前 workflow digest。外层 DOCX SHA 改变但 `document.xml` 与旧稿相同必须标记 `LEGACY_REPACKAGE_ONLY` 并拒绝新路线成功状态。

- [ ] **Step 5: 实现下载失效和两个按钮**

UI 分别显示“导出内部评审 DOCX”和“生成已验证发布稿”。后者在 placeholder 未解决时禁用。任何上游改变后 release snapshot stale，`/file` 返回 403；失败导出不得改写现有 DOCX、snapshot 或 quality report。

- [ ] **Step 6: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_docx_integrity.py tests/test_project_release.py \
  tests/test_qoderwork_native_review_writer.py -k 'release or export or docx or figure'
git add -- review_writer/delivery/docx_integrity.py tests/test_docx_integrity.py \
  review_writer/delivery/figure_policy.py review_writer/delivery/project_release.py \
  view/serve_review_dashboard.py view/assets/dashboard/review.html \
  tests/test_project_release.py tests/test_qoderwork_native_review_writer.py
git diff --cached --check
git commit -m "feat: add evidence bound internal review release"
```

---

### Task 11: 建立 credits ledger、黄金标准 rubric 和 Hard Fail evaluator

**Files:**

- Create: `schemas/operations/credit_event.v1.schema.json`
- Create: `review_writer/project/credit_ledger.py`
- Create: `tests/test_credit_ledger.py`
- Create: `docs/quality/review_benchmark_rubric.md`
- Create: `schemas/quality/review_benchmark_report.v1.schema.json`
- Create: `review_writer/evaluation/standard_corpus.py`
- Create: `review_writer/evaluation/review_benchmark.py`
- Create: `scripts/validators/validate_review_benchmark.py`
- Create: `tests/test_review_benchmark.py`
- Modify: `scripts/run_vertical_review.py`

- [ ] **Step 1: 写 credits ledger 失败测试**

```python
def test_credit_ledger_records_reported_baseline() -> None:
    event = record_credit_event(PROJECT, before=2004, after=1351, source="manual_dashboard")
    assert event["consumed"] == 653


def test_credit_ledger_rejects_broken_continuity_without_append() -> None:
    record_credit_event(PROJECT, before=2004, after=1351, source="manual_dashboard")
    before = ledger_bytes(PROJECT)
    with pytest.raises(CreditLedgerError, match="CREDIT_CONTINUITY_INVALID"):
        record_credit_event(PROJECT, before=1400, after=1300, source="manual_dashboard")
    assert ledger_bytes(PROJECT) == before
```

ledger 为 append-only JSONL，只记录阶段、study IDs、输入/输出 digest、forecast、before/after/consumed、measurement source 和时间；不记录账号或认证信息。新增无副作用 CLI：

```text
record-credits --project <path> --stage <name> --before <int> --after <int> --source manual_dashboard
```

- [ ] **Step 2: 写 benchmark 失败测试**

```python
def test_hard_fail_overrides_numeric_score() -> None:
    report = evaluate_review(RELEASE, rubric_scores(total=96), hard_fails=["WRONG_SOURCE_BINDING"])
    assert report["status"] == "fail"
    assert report["score"] == 96


def test_internal_placeholder_is_reported_but_not_internal_hard_fail() -> None:
    report = evaluate_review(INTERNAL_RELEASE_WITH_PLACEHOLDER, rubric_scores(total=84))
    assert report["status"] == "pass_internal"
    assert report["expert_release_ready"] is False
```

- [ ] **Step 3: 固化 100 分量表**

仓库 rubric 固定为总设计的产品维度：

| 维度 | 分值 |
| --- | ---: |
| 范围与问题价值 | 10 |
| Source Set 覆盖 | 15 |
| 证据忠实度 | 20 |
| 综合与批判性 | 20 |
| 结构与叙事 | 15 |
| 图表的信息价值 | 10 |
| 引用与可追溯性 | 10 |

同时在子项中提高化学正确性、认识论分型、反例/局限和图文对应的权重解释。`80–89` 为可接受内部稿但需修订，`90–100` 为标杆级内部稿；任何 Hard Fail 优先。

- [ ] **Step 4: 实现内部稿与专家稿两套 Hard Fail 投影**

共同 Hard Fail：错误来源绑定、未读支撑来源、未批准高风险主张、stale approval、补造条件/机制/共识、磁盘/API/UI/release 不一致、无来源科学主张、旧稿重新打包、系统生成综合科学图。

内部稿允许清晰标记且 lineage 完整的 synthesis placeholder；专家稿额外要求所有必需综合图由用户上传并完成科学验收。

- [ ] **Step 5: 绑定 `标准.zip` 分层标杆**

`load_standard_corpus()` 校验 Task 1 生成的 repo 外只读 corpus manifest、所有文件 hash、8 篇标杆论文/综述、6 份写作/图稿指南、1 份 ChemDraw stylesheet 和 MinerU 解析覆盖；不得把标杆正文复制进 repo。比较项包括章节比例、比较/批判段落密度、Source Figure 密度、caption 信息量、引用密度和可追溯性，但分数最终保留人工/Agent逐项理由。

- [ ] **Step 6: 验证并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_credit_ledger.py tests/test_review_benchmark.py \
  tests/test_quality_validators.py
git add -- schemas/operations/credit_event.v1.schema.json \
  review_writer/project/credit_ledger.py tests/test_credit_ledger.py \
  docs/quality/review_benchmark_rubric.md \
  schemas/quality/review_benchmark_report.v1.schema.json \
  review_writer/evaluation/standard_corpus.py \
  review_writer/evaluation/review_benchmark.py \
  scripts/validators/validate_review_benchmark.py \
  tests/test_review_benchmark.py scripts/run_vertical_review.py
git diff --cached --check
git commit -m "feat: add review benchmark and credit ledger"
```

---

### Task 12: 完成真实章节、内部 DOCX 和黄金标准评估

**Files:**

- External modify: 新三篇项目的 `04_manuscript/`、`05_release/`、`06_evaluation/`
- Review only: 旧项目的 `04_first_draft/`、`05_final_audit/`

- [ ] **Step 1: 派发逐节 Content Agents**

每节使用独立或全新上下文的 drafting Agent，只接收当前 Section Writer Packet。目标正文必须包含比较、反例、局限与适用边界，不得成为逐篇摘要串联。每节 result 经 deterministic importer 注册后由 Playwright 模拟研究者直接编辑和批准高风险表述。

- [ ] **Step 2: 完成图位**

在正文中放入已选 Source Figures 与 caption/attribution；保持三篇至少各 1 张原图。需要跨论文综合表达的位置插入明显 placeholder，不生成综合图片。Dashboard 显示图位总数、Source Figure 数、placeholder 数和缺口理由。

- [ ] **Step 3: 导出内部 DOCX**

从 Dashboard 点击“导出内部评审 DOCX”。Expected：新路线所有门禁闭合，生成 `SELF_REVIEWED_DRAFT`；专家稿按钮因 placeholder 保持禁用。

- [ ] **Step 4: 验证不是旧稿重新打包**

记录并比较：

```text
old Markdown SHA-256
new Markdown SHA-256
old DOCX word/document.xml SHA-256
new DOCX word/document.xml SHA-256
old/new media entry hashes
new Markdown ↔ DOCX normalized text match
```

所有“新”内容指标必须来自当前 manuscript lineage v2；DOCX 外层 SHA 不作为充分证据。

- [ ] **Step 5: 运行黄金标准评估**

```zsh
case_root=/home/kenqia/my_folder/review-writer-data/review-projects/vis-light-olefin-difunctionalization-complete-loop-v1
standards_root=/home/kenqia/my_folder/review-writer-data/template-papers/standards/20260728
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validators/validate_review_benchmark.py \
  --project "$case_root" --standards "$standards_root" --release-level SELF_REVIEWED_DRAFT
```

Expected: score ≥ 80，无 internal Hard Fail；若失败，保留报告并回到具体 Evidence/Synthesis/Section，不整体重启项目。

- [ ] **Step 6: 渲染并检查 DOCX 页面**

使用工作区可用的文档/PDF工具将 DOCX 渲染为页面图像，逐页检查文字裁切、空白页、标题层级、公式/化学符号、图片清晰度、caption、分页、引用和 placeholder 可见性。无法渲染时报告 `ENVIRONMENT_UNDETERMINED`，不得用 XML 检查冒充视觉验收。

---

### Task 13: 第一轮独立 Playwright 全流程黑盒验收

**Files:**

- Create: `docs/qa/three-paper-evidence-to-release-playwright.md`
- Create external screenshots: `/tmp/review-writer-e2r-round1/`

- [ ] **Step 1: 写完整黑盒协议**

新 Reviewer 未参与实现，只获得 URL、项目名、`simulated_researcher` persona 和协议。它只用 Playwright navigation、snapshot/find、click、fill/type、keyboard、resize、screenshot、console、network list、wait 和 close；不得读仓库、shell、storage、内部 JSON 或 request/response body。

- [ ] **Step 2: 固定全流程序列**

Reviewer 必须从当前项目阶段开始，依次验证：

1. Parse 状态已闭合；
2. 三篇 Paper Evidence、PDF/parsed/Source Figure locator 和决定；
3. Comparison Protocol、Coverage Map、Synthesis Claims、反证/局限；
4. Section Contracts 和 5–8 个图位；
5. 高风险正文编辑与逐节批准；
6. 内部 DOCX 可导出、专家稿因 placeholder 不可导出；
7. 黄金标准分数和 Hard Fail 结果；
8. refresh、两次 server restart 持久化；
9. `1440×1000`、`1024×900`、`390×844`；
10. keyboard focus、console 零 warning/error、计划内请求均成功。

- [ ] **Step 3: 内容缺口请求协议**

如果 UI 缺少候选内容，Reviewer 返回 `CONTENT_AGENT_REQUEST` 并暂停；主 Agent派发独立 Content Agent、校验导入并回复继续。Reviewer 不自行生成内容，也不因请求而失去独立性。

- [ ] **Step 4: Pass rule**

零 P0/P1；影响科学决定的 P2 阻断；无横向滚动/重叠；决定与 actor 持久；普通 UI 不暴露 path/hash/schema/JSON/Prompt；新 DOCX 可下载且不是旧稿；Source Figures/placeholder 含义清晰；磁盘/API/UI/release/evaluation 一致。

- [ ] **Step 5: 派发 Round 1 并由主 Agent 审查**

主 Agent复核 screenshots、console、network、项目状态、release snapshot、DOCX integrity 和 benchmark report。Reviewer 只报告，不修代码。

---

### Task 14: 失败测试修复、全新 Agent 回归和最终验收

**Files:**

- Modify: only files required by confirmed findings
- Create external regression project: `vis-light-olefin-difunctionalization-complete-loop-regression-v1`
- Create external screenshots: `/tmp/review-writer-e2r-round2/`

- [ ] **Step 1: 分类 Round 1 findings**

每个 finding 记录 ID、severity、category、root cause、affected contract、失败测试、最小修复、验证命令和 commit。禁止把多个不相关 finding 混成一次重构。

- [ ] **Step 2: 用 TDD 修复**

P0/P1 和影响科研判断的 P2：失败测试 → 最小实现 → 局部测试 → commit。普通视觉 P2/P3 在不改变科学合同的前提下修复；无法复现时保留 `ENVIRONMENT_UNDETERMINED`。

- [ ] **Step 3: 创建全新非覆盖 regression 项目**

不得复用 Round 1 的浏览器 session、项目决定或已生成下游对象。使用 Task 1 bootstrap 创建新 project ID，从 Source Truth/Parse 开始；原始 PDF/MinerU 可只读复用，所有决定、Evidence、Synthesis、正文和 DOCX 重新生成。

- [ ] **Step 4: 派发全新 Playwright Agent 完整重跑**

Round 2 Agent 未参与实现或 Round 1，使用相同协议完成全流程。主 Agent在内容请求时派发新的 Content Agents，不复用 Round 1 content result 作为批准对象。

- [ ] **Step 5: 运行分层新鲜验证**

快速门禁：

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_parse_quality.py tests/test_paper_evidence.py \
  tests/test_evidence_synthesis.py tests/test_review_figures.py \
  tests/test_manuscript_v2.py tests/test_docx_integrity.py \
  tests/test_review_benchmark.py tests/test_workflow_projection.py
```

Dashboard/release 门禁：

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_vertical_review_projection.py \
  tests/test_qoderwork_native_review_writer.py \
  tests/test_project_release.py
```

最终完整回归只在 Round 2 后运行一次：

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -s -q -p no:cacheprovider \
  tests/test_source_truth.py tests/test_parse_quality.py \
  tests/test_vertical_review_projection.py \
  tests/test_qoderwork_native_review_writer.py \
  tests/test_project_release.py tests/test_reusable_library.py \
  tests/test_review_batch_runner.py
make smoke
make quality-check
```

记录测试总数和耗时；已知完整回归基线为 470 passed / 约 32 分钟，因此不得把完整集塞进每个小 Task。

- [ ] **Step 6: 提交边界和安全审查**

```zsh
git diff --check a6d67db..HEAD
git status --short --branch
git log --oneline --decorate a6d67db..HEAD
git diff --stat a6d67db..HEAD
```

确认 repo 不含真实 PDF、MinerU 输出、标杆正文、项目 artifacts、token/env、浏览器数据、自动综合图或绝对外部数据路径。

- [ ] **Step 7: 向肯恰大人交付最终验收入口**

报告必须包含：

- WSL Dashboard URL；
- Round 1 findings、修复 commits 和 Round 2 结果；
- 三视口截图与 DOCX 页面截图；
- 三篇 Parse/Evidence/Synthesis/Section/figure 状态；
- Source Figure 数量、placeholder 数量及每个图位理由；
- 新旧 Markdown、DOCX internal content 差异；
- benchmark 分项分数、Hard Fail、黄金标准差距；
- credits ledger；
- 测试、console、network、restart、Git 状态；
- 明确声明当前只是 `SELF_REVIEWED_DRAFT`，不是投稿级或专家发布稿。

只有肯恰大人明确批准后，M5 才能标记 `Owner-visible result=accepted`，随后才讨论大综述计划。

---

## 自审矩阵

| 总设计要求 | 落地 Task |
| --- | --- |
| Source Truth + Parse Quality | 1–3 |
| Typed Paper Evidence + epistemic type | 4 |
| 原论文图片优先、综合图只占位符 | 5、10、12 |
| Comparison Protocol + Coverage Map | 6–8 |
| Synthesis Claim + counter-evidence | 6–8 |
| Section Contract + high-risk editing | 6、9、12 |
| 旧稿隔离 + lineage v2 | 9–10 |
| DOCX fail-closed + 双层发布 | 3、10 |
| 黄金标准 + Hard Fail + credits | 11–12 |
| Playwright 独立 Agent → 主 Agent 审查 → 修复 → 新 Agent 回归 | 13–14 |

## 回滚边界

- 每个 Task 一个或少量独立本地 commit，可使用普通 `git revert <commit>` 回退；不使用 reset/checkout。
- 新真实项目和 regression 项目均为外部非覆盖副本；旧 `vis-light-olefin-difunctionalization-wsl-v1` 保持可读基线。
- 新路线通过 route detection 隔离；legacy fixture 未迁移前继续使用旧行为。
- 失败 importer、decision PUT、release 和 benchmark 均要求写前完成全部校验并原子替换；失败不得留下部分状态。

## 已锁定执行方式

用户已选择 Inline Execution。实现阶段使用 `superpowers:executing-plans` 分批执行本计划；主 Agent 保持实现与审查所有权，按需派发相互隔离的 Evidence、Synthesis、Drafting Content Agents，并在 Task 3、8、12–14 派发未参与实现的 Playwright Agents。每批完成后先更新本计划状态表，再进入下一批。
