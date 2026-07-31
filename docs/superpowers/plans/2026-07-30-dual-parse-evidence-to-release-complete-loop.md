# Dual-parse Evidence-to-Release Complete Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在全新三篇 core 项目中同时使用 Generic MinerU API 与用户手工导出的 MinerU Chemical Paper ZIP，经独立 Agent 模拟全部产品内研究者操作，完整产出可审计的 `SELF_REVIEWED_DRAFT` DOCX/PDF。

**Architecture:** 原始 PDF 是唯一科学真源；Generic MinerU 是正文/版面/原图基础层，Chemical Paper 是经 formal importer 导入后的 core study 化学增强层。两层通过同一 PDF 与 study identity 绑定，Honest Progressive Route 负责三态化学投影与可见缺口；对象级 Reconciliation 仍对其依赖对象 fail-closed。已有 Evidence、Synthesis、Manuscript 和 Release 模块只消费当前双层安全投影，不能把候选静默升级为科学事实。

## Fresh v3 Honest Progressive Contract

<!-- FRESH_V3_CONTRACT_START -->

This is the normative contract for every fresh v3 execution. The route never
converts a candidate into a confirmed fact and never uses zero as a substitute
for an unknown or unavailable state.

### Three-state scientific value

Every authoritative molecule row uses exactly one state:

| State | Value | Required evidence | Allowed use |
|---|---|---|---|
| `CONFIRMED` | non-null | PDF locator and researcher confirmation | precise scientific claims |
| `AI_PROVISIONAL` | non-null | PDF locator, confidence, and provenance | explicitly provisional internal views only |
| `BLOCKED` | `null` | non-empty `gap_reason`; locator when available | limitation/gap disclosure only |

`CONFIRMED` is never inferred from an AI candidate. `AI_PROVISIONAL` must keep
its PDF locator, confidence, and provenance. `BLOCKED` must keep
`value=null` plus `gap_reason`. The researcher-safe projection may expose
status, safe locator, confidence, provenance, and gap reason, but never raw
paths, hashes, JSON, MolBlocks, tokens, sessions, or internal IDs. Append-only
history is immutable; actor mismatch is disclosed as provenance residual.

### Fresh v3 initial state

When the fresh project has only verified PDFs and fresh Generic current, with no
authoritative Chemical cohort yet:

- `availability/status` is `unknown/unavailable`, never `ready/current`;
- `core_denominator`, `confirmed_count`, `ai_provisional_count`,
  `blocked_count`, `coverage_ratio`, `coverage_sufficient`, and `gap_registry`
  remain unknown/null; none is compressed to `0` and no empty `gap_registry`
  is fabricated;
- the only next action is `待 Chemical Paper 导入`; after the first approved ZIP
  has completed safe preflight and awaits confirmation, the only next action is
  `确认第一份 Chemical Paper 导入`;
- credits are displayed only as `NOT_APPLICABLE_BY_CURRENT_SCOPE`.

No new next action is allowed to compete with those labels. `gap_registry` is
created only after authoritative molecule rows exist.

### Formal Chemical import and v3 counting

Only after all three approved Chemical inputs have completed formal
preflight/confirm/import and are `3/3 current` may the server validate pages
`6/11/11`, molecule counts `125/109/75` (project total `309`), and
`reaction_data_status=unavailable_not_provided`. At that point, and only when
authoritative molecule rows exist:

```text
project_denominator = 309
coverage_ratio = (confirmed_count + ai_provisional_count) / 309
coverage_threshold = 0.8
coverage_sufficient = server_calculated(coverage_ratio >= coverage_threshold)
```

The server calculates all counts, denominator, ratio, threshold, and
`coverage_sufficient`; client-supplied counts are untrusted. Missing reaction
data remains `unavailable_not_provided`, never zero.

Approved ZIPs enter only through the formal preflight → confirm → importer
path. Never hand-unzip them, use a v2 Generic ZIP, or reuse old Generic
outputs. ZIP/PDF binding and path/hash evidence are Coordinator-only and never
enter Dashboard or Researcher projections.

### Progressive continuation and role sequence

Honest Progressive permits incomplete work but never permits opaque work. Below
80%, source/evidence preparation may continue with an explicit
`needs_more_traceable_candidates` state; no scientific approval may be
fabricated or silently upgraded.

The Researcher makes visible PDF-bound decisions and supplies confirmation for
`CONFIRMED`; the Coordinator audits binding, path/hash, formal-import, safe-
projection, and gap evidence read-only; the Integration Owner owns Task 10
fresh bootstrap, formal preflight/confirm/import, safe projection, runtime
readiness, and protocol restarts. Only after formal import, safe projection,
and runtime readiness are complete may Task 11 create a new Playwright
Researcher. Content Agents remain candidate-only and study-local.

### Researcher-safe fields

```text
resolved_smiles_status
resolved_smiles
confidence
provenance
gap_reason
actor_provenance_residual
```

<!-- FRESH_V3_CONTRACT_END -->

**Tech Stack:** Python 3.11+、JSON Schema 2020-12、stdlib HTTP server、vanilla JavaScript/CSS、pytest、MinerU precise parsing batch API、Playwright MCP、python-docx、Git worktrees。

---

## 1. 执行基线与并行拓扑

共同 parent 固定为：

```text
eb9964a  docs: define dual-parse evidence-to-release design
```

其 product parent 是 frozen candidate `9213018b527c0abb7583365311c7a7b1c86c55a7`。权威规格是 `docs/superpowers/specs/2026-07-30-dual-parse-evidence-to-release-design.md`。

第一波四个并行会话全部从 `eb9964a` 创建独立 worktree：

| 会话 | Branch | 独占任务 |
| --- | --- | --- |
| Scientific State Owner | `codex/e2r-dual-scientific` | Tasks 1–5 |
| Dashboard UI Owner | `codex/e2r-dual-dashboard` | Task 6 |
| Release Backend Owner | `codex/e2r-dual-release` | Task 7 |
| QA Protocol Owner | `codex/e2r-dual-qa-protocol` | Task 8 |

启动第一波前，由协调会话从主仓库只执行一次以下准备；四个目标 branch/worktree 任一已存在时先只读审计，不覆盖、不复用未知工作树：

```zsh
git -C /home/kenqia/my_folder/review-writer status --short --branch
git -C /home/kenqia/my_folder/review-writer cat-file -e eb9964a^{commit}
git -C /home/kenqia/my_folder/review-writer worktree add -b codex/e2r-dual-scientific \
  /home/kenqia/my_folder/review-writer/.worktrees/e2r-dual-scientific eb9964a
git -C /home/kenqia/my_folder/review-writer worktree add -b codex/e2r-dual-dashboard \
  /home/kenqia/my_folder/review-writer/.worktrees/e2r-dual-dashboard eb9964a
git -C /home/kenqia/my_folder/review-writer worktree add -b codex/e2r-dual-release \
  /home/kenqia/my_folder/review-writer/.worktrees/e2r-dual-release eb9964a
git -C /home/kenqia/my_folder/review-writer worktree add -b codex/e2r-dual-qa-protocol \
  /home/kenqia/my_folder/review-writer/.worktrees/e2r-dual-qa-protocol eb9964a
git -C /home/kenqia/my_folder/review-writer worktree list
```

每个会话只收到自己的绝对 worktree、branch、任务号、共同 parent、权威规格和 handoff 格式。协调会话确认四者都从 `eb9964a` 开始后才允许并行写入。

第二波顺序执行：

| 会话 | 范围 |
| --- | --- |
| Integration Owner | Tasks 9–10：集成、门禁、fresh project、runtime |
| Independent QA Coordinator | Tasks 11–12：Playwright Researcher、Content Agents、两次 restart、artifact audit |

固定禁止：

- push、PR、deploy、远端写；
- 修改旧计划 checkbox；并行 Workers 也不编辑本计划；
- 多个 Owner 写同一 worktree；
- 读取、打印或记录 token/cookie/session；
- 使用 MinerU 私有 Chemical Paper API；
- AI 把候选静默升级为 `CONFIRMED`，或丢弃 `AI_PROVISIONAL` 的 locator/confidence/provenance；
- 复用 regression-v1 的决定、Evidence、Synthesis、Content Agent result、manuscript、DOCX、release 或 browser/session；
- 读取 quarantined study2 results 的语义内容；
- 自动生成、组合或重绘科学综合图；
- 在出现 release-blocking finding 的同一独立 run 中修补后宣称 PASS。

## 2. 文件责任边界

Scientific State 新增：

- `review_writer/project/dual_parse_bootstrap.py`：fresh source-only bootstrap 与 Generic output 正式绑定。
- `review_writer/project/dual_source.py`：Generic/Chemical/PDF currentness。
- `review_writer/project/chemical_completion.py`：名称/局部标签、单一 `resolved_smiles` 与 Honest Progressive 三态投影。
- `review_writer/project/parse_reconciliation.py`：对象级双层仲裁。
- `tests/test_dual_parse_figures.py`：Generic caption/image authority、Chemical gap 与 registry currentness。
- 对应四份 schema 与 tests。

Dashboard UI 新增：

- `view/assets/dashboard/review-dual-parse.js`
- `view/assets/dashboard/review-dual-parse.css`
- `tests/test_dashboard_dual_parse_ui.py`

Release Backend 新增：

- `review_writer/delivery/dual_parse_release.py`
- `tests/test_dual_parse_release.py`
- `tests/test_dashboard_dual_parse_api.py`

Release Backend 同时只接线 `review_writer/project/manuscript_v2.py`、`schemas/delivery/manuscript_lineage.v2.schema.json`、`schemas/delivery/project_release.v2.schema.json` 和 `schemas/quality/review_benchmark_report.v1.schema.json`，把 dual-source versions 纳入 manuscript/release currentness；不改 Scientific State 的写入规则。

QA 新增：

- `docs/qa/three-paper-dual-parse-evidence-to-release-playwright.md`
- `tests/test_dual_parse_qa_protocol.py`
- `tests/test_honest_progressive_docs_contract.py`

现有大文件只做必要接线，不做无关重构：`scripts/run_vertical_review.py`、`review_writer/project/chemical_paper.py`、`review_writer/project/paper_evidence.py`、`review_writer/project/content_agent_handoff.py`、`review_writer/project/workflow_projection.py`、`view/serve_review_dashboard.py`、`view/assets/dashboard/review.html`、release/evaluation schemas。

---

### Task 1: Scientific Owner — Fresh bootstrap 与 Generic MinerU 正式绑定

**Files:**

- Create: `schemas/project/dual_parse_bootstrap_request.v1.schema.json`
- Create: `review_writer/project/dual_parse_bootstrap.py`
- Create: `tests/test_dual_parse_bootstrap.py`
- Modify: `scripts/run_vertical_review.py`

- [ ] **Step 1: 写 source-only、原子性和零语义复制失败测试**

```python
def test_bootstrap_creates_only_brief_discovery_and_bound_pdfs(tmp_path: Path) -> None:
    request = source_request(tmp_path, project_id="dual-fresh", count=3)
    project = bootstrap_dual_parse_project(tmp_path / "review-projects", request)
    assert len(list((project / "00_sources/papers").glob("*.pdf"))) == 3
    assert not (project / "01_evidence").exists()
    assert not (project / "02_synthesis").exists()
    assert not (project / "04_manuscript").exists()


def test_hash_mismatch_is_zero_write(tmp_path: Path) -> None:
    request = source_request(tmp_path, project_id="dual-fresh", count=3)
    request["sources"][0]["expected_pdf_sha256"] = "0" * 64
    before = snapshot(tmp_path / "review-projects")
    with pytest.raises(DualParseBootstrapError, match="SOURCE_PDF_HASH_MISMATCH"):
        bootstrap_dual_parse_project(tmp_path / "review-projects", request)
    assert snapshot(tmp_path / "review-projects") == before
```

参数化覆盖重复 study/source ID、非 MAIN、symlink、非 PDF、相同 PDF、2/4 篇输入、未知字段、target exists。

- [ ] **Step 2: 运行 RED**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_dual_parse_bootstrap.py
```

Expected: collection FAIL。

- [ ] **Step 3: 定义 bootstrap request**

固定字段：`schema_version`、`project_id`、`brief`、三条 `sources`。每条 source 只含 `study_id`、`source_id`、`doi`、`title`、`tier=core|background`、`document_role=MAIN`、operator-only `pdf_input_path`、`expected_pdf_sha256`。`pdf_input_path` 不得持久化。

- [ ] **Step 4: 实现公开接口**

```python
class DualParseBootstrapError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def bootstrap_dual_parse_project(review_root: Path, request: object) -> Path:
    """Validate all PDFs, stage a source-only project, publish once."""


def bind_generic_parse_outputs(project: Path, mineru_output: Path) -> dict[str, object]:
    """Bind only fresh output rows matching current project PDF bytes."""
```

Bootstrap 只创建 Brief、candidate pool、acquisition receipt、identity audit 和 PDF。Generic binding 必须验证 3 completed/0 failed、formula/table enabled、language `en`、model `vlm`，复制当前 Markdown/content-list v2/layout/model/images/raw ZIP，构建 text layers、Source Truth 和 Parse Quality 自动 assessment；任何 study 失败则权威项目零写入。

- [ ] **Step 5: 接入正式主 CLI**

```text
bootstrap-dual-parse --review-root ROOT --request REQUEST_JSON
bind-generic-parse --project PROJECT --mineru-output OUTPUT_ROOT
```

stdout 只返回 safe counts/status；错误只返回稳定 reason code。

- [ ] **Step 6: 运行 GREEN 与旧 bootstrap 回归**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_dual_parse_bootstrap.py tests/test_three_paper_complete_loop_bootstrap.py   tests/test_source_truth.py tests/test_parse_quality.py
```

- [ ] **Step 7: 提交**

```zsh
git add -- schemas/project/dual_parse_bootstrap_request.v1.schema.json   review_writer/project/dual_parse_bootstrap.py tests/test_dual_parse_bootstrap.py   scripts/run_vertical_review.py
git diff --cached --check
git commit -m "feat: add fresh dual parse bootstrap"
```

---

### Task 2: Scientific Owner — Dual-source Binding 与 core/background 路由

**Files:**

- Create: `schemas/evidence/dual_source_binding.v1.schema.json`
- Create: `review_writer/project/dual_source.py`
- Create: `tests/test_dual_source.py`
- Modify: `review_writer/project/source_truth.py`
- Modify: `review_writer/project/chemical_paper.py`
- Modify: `scripts/run_vertical_review.py`

- [ ] **Step 1: 写 currentness RED 测试**

```python
def test_core_requires_current_generic_and_chemical_lanes(dual_project: Path) -> None:
    binding = write_dual_source_binding(dual_project, "study-a")
    assert binding["source_tier"] == "core"
    assert binding["status"] == "current"
    assert binding["generic"]["source_pdf_sha256"] == binding["chemical"]["source_pdf_sha256"]


def test_background_allows_generic_only_until_claim_requires_chemical(dual_project: Path) -> None:
    make_background(dual_project, "study-a")
    remove_chemical_state(dual_project, "study-a")
    assert write_dual_source_binding(dual_project, "study-a")["status"] == "current_generic_only"
    with pytest.raises(DualSourceError, match="CHEMICAL_ENHANCEMENT_REQUIRED"):
        require_dual_source_ready(dual_project, "study-a", requires_chemical=True)
```

增加 PDF drift、Generic reparse、Chemical re-import、wrong study/source、missing lane、stale binding、unknown tier。

- [ ] **Step 2: 运行 RED**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_dual_source.py
```

- [ ] **Step 3: 定义 schema 与接口**

```python
def build_dual_source_binding(project: Path, study_id: str) -> dict[str, object]: ...
def write_dual_source_binding(project: Path, study_id: str) -> dict[str, object]: ...
def load_dual_source_binding(project: Path, study_id: str) -> dict[str, object]: ...
def project_dual_source_state(project: Path) -> dict[str, object]: ...
def require_dual_source_ready(project: Path, study_id: str, *, requires_chemical: bool) -> str: ...
```

Binding 固定记录 project/study/source/tier/PDF SHA、Source Truth bundle digest、Parse gate digest、Chemical state/import digest、reaction `unavailable_not_provided`、status 和 binding digest。

- [ ] **Step 4: 实现规则**

Core 必须两 lane current 且同 PDF；background 可 Generic-only；background claim 声明 molecule/SMILES/MolBlock dependency 时强制 Chemical。写入前后在 project lock 中重验。Reaction 缺失不能投影为 0，固定为 `unavailable_not_provided`。

- [ ] **Step 5: 增加 CLI**

```text
build-dual-source --project PROJECT [--study-id STUDY]
dual-source-state --project PROJECT
```

- [ ] **Step 6: GREEN 并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_dual_source.py tests/test_source_truth.py tests/test_parse_quality.py   tests/test_chemical_paper_import.py
git add -- schemas/evidence/dual_source_binding.v1.schema.json   review_writer/project/dual_source.py review_writer/project/source_truth.py   review_writer/project/chemical_paper.py tests/test_dual_source.py   scripts/run_vertical_review.py
git diff --cached --check
git commit -m "feat: bind generic and chemical parse lanes"
```

---

### Task 3: Scientific Owner — Honest Progressive Chemical Completion 投影与批量补全

**Files:**

- Create: `schemas/evidence/chemical_completion_gate.v1.schema.json`
- Create: `review_writer/project/chemical_completion.py`
- Create: `tests/test_chemical_completion.py`
- Modify: `review_writer/project/chemical_paper.py`
- Modify: `scripts/review/chemical_paper.py`
- Modify: `scripts/run_vertical_review.py`

- [ ] **Step 1: 写完整性与 batch 原子性 RED 测试**

```python
def test_fresh_v3_without_chemical_keeps_counts_unknown(project: Path) -> None:
    gate = chemical_completion_state(project, "study-a")
    assert gate["route"] == "honest_progressive"
    assert gate["availability"] in {"unknown", "unavailable"}
    for key in (
        "core_denominator", "confirmed_count", "ai_provisional_count",
        "blocked_count", "coverage_ratio", "coverage_sufficient", "gap_registry",
    ):
        assert gate[key] is None
    assert gate["next_action"] in {
        "待 Chemical Paper 导入", "确认第一份 Chemical Paper 导入"
    }


def test_post_import_projects_server_calculated_tri_state_coverage(project: Path) -> None:
    gate = chemical_completion_state(project, "study-a")
    assert gate["core_denominator"] == 309
    assert gate["coverage_threshold"] == 0.80
    assert gate["coverage_ratio"] == (
        gate["confirmed_count"] + gate["ai_provisional_count"]
    ) / 309
    assert {row["resolved_smiles_status"] for row in gate["molecules"]} <= {
        "CONFIRMED", "AI_PROVISIONAL", "BLOCKED"
    }
    assert all(row["value"] is None for row in gate["gap_registry"])


def test_batch_is_atomic_and_researcher_attributed(project: Path) -> None:
    gate = chemical_completion_state(project, "study-a")
    result = apply_chemical_completion_batch(project, "study-a", {
        "version_token": gate["version_token"],
        "actor_type": "simulated_researcher_agent",
        "actor_label": "simulated_researcher",
        "corrections": [{
            "molecule_index": 0, "field": "mol_idt", "value": "compound 3a",
            "reason": "Label visible in Scheme 2.",
            "pdf_locator": {"page": 3, "figure_label": "Scheme 2"},
        }],
    })
    assert result["applied_count"] == 1
```

拒绝 AI/system actor 直接写入 `CONFIRMED`、空 reason、无 page、stale token、重复 field/index、明显无效 SMILES、部分 batch 失败；失败时 state bytes 不变。`AI_PROVISIONAL` 必须带 PDF locator、confidence、provenance，`BLOCKED` 必须带非空 `gap_reason` 且 value 为 null。

- [ ] **Step 2: 运行 RED**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_chemical_completion.py
```

- [ ] **Step 3: 定义 gate 与接口**

```python
def chemical_completion_state(project: Path, study_id: str) -> dict[str, object]: ...
def project_chemical_completion_state(project: Path) -> dict[str, object]: ...
def apply_chemical_completion_batch(project: Path, study_id: str, payload: object) -> dict[str, object]: ...
def require_chemical_completion_ready(project: Path, study_id: str) -> str: ...
```

正式 Chemical import 后，Core 的每个 authoritative molecule row 必须有当前
`mol_idt`（允许论文局部标签）和且仅有一个三态投影；`smiles_expanded` /
`smiles_unexpanded` 只作为候选与 provenance。Batch 在同一 lock 内先验证全部
rows，再形成逐字段 immutable events，最后一次原子写；每个研究者补录事件必须
有 PDF locator。无法由 PDF 支持的值保持 `BLOCKED`，进入 gap registry，不阻断
无关 source/evidence preparation。只有 authoritative rows 存在时项目 coverage
才以 309 为分母，按 `(CONFIRMED + AI_PROVISIONAL) / 309` 计算，阈值为 0.80。

- [ ] **Step 4: 增加 CLI**

```text
chemical-completion-state --project PROJECT [--study-id STUDY]
complete-chemical-fields --project PROJECT --study-id STUDY --input BATCH_JSON
```

- [ ] **Step 5: GREEN 并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_chemical_completion.py tests/test_chemical_paper_import.py   tests/test_chemical_paper_integration.py
git add -- schemas/evidence/chemical_completion_gate.v1.schema.json   review_writer/project/chemical_completion.py review_writer/project/chemical_paper.py   scripts/review/chemical_paper.py scripts/run_vertical_review.py   tests/test_chemical_completion.py
git diff --cached --check
git commit -m "feat: require researcher chemical completion"
```

---

### Task 4: Scientific Owner — 对象级 Reconciliation 与 Evidence prewrite gate

**Files:**

- Create: `schemas/evidence/parse_reconciliation.v1.schema.json`
- Create: `review_writer/project/parse_reconciliation.py`
- Create: `tests/test_parse_reconciliation.py`
- Create: `tests/test_dual_parse_figures.py`
- Modify: `review_writer/project/paper_evidence.py`
- Modify: `review_writer/project/workflow_projection.py`
- Modify: `review_writer/project/review_figures.py`
- Modify: `scripts/run_vertical_review.py`

- [ ] **Step 1: 写冲突、历史与局部 stale RED**

```python
def test_conflict_requires_pdf_resolution(project: Path) -> None:
    registry = write_parse_reconciliation(project, "study-a")
    conflict = next(row for row in registry["objects"] if row["status"] == "conflict")
    assert conflict["generic_candidate"] != conflict["chemical_candidate"]
    assert registry["workflow_can_continue"] is False


def test_resolution_records_pdf_actor_and_object_version(project: Path) -> None:
    registry = write_parse_reconciliation(project, "study-a")
    conflict = next(row for row in registry["objects"] if row["status"] == "conflict")
    updated = apply_reconciliation_decision(project, "study-a", {
        "object_id": conflict["object_id"],
        "registry_digest": registry["registry_digest"],
        "action": "pdf_resolved", "selected_lane": "chemical",
        "note": "Original PDF supports this structure.",
        "pdf_locator": {"page": 4, "figure_label": "Scheme 3"},
        "actor_type": "simulated_researcher_agent",
        "actor_label": "simulated_researcher",
    })
    assert updated["decision"]["action"] == "pdf_resolved"
```

测试 corroborated/complementary 不制造人工批准；Generic reparse 与 Chemical correction 只 stale 相关对象；一个 study blocked 不影响其他 study；Evidence registrar lock 前后拒绝未闭合 core gate且零写入。

另写 Source Figure RED：只有当前 Generic `images/` 资产与显式 `Figure|Fig.|Scheme|Chart` caption 可形成 Source Figure；Chemical ZIP 没有独立图片时只产生可见 gap；caption 歧义、同页碎片歧义、重复图号或 Generic/Source Truth drift 使 registry fail-closed，不能复用 stale registry。

- [ ] **Step 2: 运行 RED**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_parse_reconciliation.py tests/test_dual_parse_figures.py \
  tests/test_paper_evidence.py tests/test_review_figures.py
```

- [ ] **Step 3: 定义 registry**

对象字段固定为 object ID、kind、source/page、两条 researcher-safe candidates、status、object digest 和可选 decision。Status：`corroborated|complementary|conflict|single_lane_only|needs_review|stale|blocked`。Decision：`pdf_resolved|pdf_locator_only|reject_both`，包含 selected lane、note、PDF locator、actor/time、bound object digest。

- [ ] **Step 4: 实现接口**

```python
def build_parse_reconciliation(project: Path, study_id: str) -> dict[str, object]: ...
def write_parse_reconciliation(project: Path, study_id: str) -> dict[str, object]: ...
def load_parse_reconciliation(project: Path, study_id: str) -> dict[str, object]: ...
def apply_reconciliation_decision(project: Path, study_id: str, payload: object) -> dict[str, object]: ...
def project_reconciliation_state(project: Path) -> dict[str, object]: ...
def require_reconciliation_ready(project: Path, study_id: str) -> str: ...
```

重建时按 object digest 保留未受影响决定，不按 aggregate digest 清空全部历史。

Source Figure registry 以当前 Generic Source Truth/image/content-list digests 为主绑定，保留 Chemical import digest 仅用于 gap/currentness 审计；不得从 molecule crop、MolBlock 或无 caption 的 Chemical fragment 发明 Source Figure。Synthesis Figure 继续只允许 placeholder + human drawing brief。

- [ ] **Step 5: 接到 Evidence 写入**

```python
def require_honest_progressive_projection(
    project: Path, study_id: str, *, allow_provisional: bool
) -> str: ...

def require_dual_evidence_ready(
    project: Path,
    study_id: str,
    *,
    requires_chemical: bool,
) -> dict[str, str]:
    chemical_required = is_core(project, study_id) or requires_chemical
    bindings = {
        "dual_source_binding_digest": require_dual_source_ready(
            project, study_id, requires_chemical=chemical_required
        ),
    }
    if chemical_required:
        bindings["honest_progressive_digest"] = require_honest_progressive_projection(
            project, study_id, allow_provisional=True
        )
        bindings["reconciliation_digest"] = require_reconciliation_ready(project, study_id)
    return bindings
```

`register_paper_evidence_candidates` 和 manual registrar 从候选的显式 field dependencies 计算 `requires_chemical`，在 lock 前、lock 内各检查一次；core candidate 绑定三项 current version 和 Honest Progressive projection，Generic-only background 只绑定当前 Generic/PDF，声明 molecule/SMILES/MolBlock dependency 的 background 再绑定 Completion/Reconciliation。`BLOCKED` 行只能进入限制/gap 证据；`AI_PROVISIONAL` 行必须保留 provisional 标识，不得被 exact claim 当作 `CONFIRMED`。

- [ ] **Step 6: 更新唯一 next action**

优先级：PDF/source → Generic parse → core Chemical import → Honest Progressive Completion projection → Reconciliation → Paper Evidence → Synthesis → Manuscript → Release。正式 import 前一次只显示 `待 Chemical Paper 导入` 或 `确认第一份 Chemical Paper 导入`；import 后若 coverage < 0.80 显示 `needs_more_traceable_candidates`，不得把 unknown/missing 压成零。

- [ ] **Step 7: GREEN 并提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_parse_reconciliation.py tests/test_dual_parse_figures.py \
  tests/test_paper_evidence.py tests/test_review_figures.py \
  tests/test_workflow_projection.py tests/test_vertical_review_projection.py
git add -- schemas/evidence/parse_reconciliation.v1.schema.json \
  review_writer/project/parse_reconciliation.py review_writer/project/paper_evidence.py \
  review_writer/project/workflow_projection.py review_writer/project/review_figures.py \
  scripts/run_vertical_review.py tests/test_parse_reconciliation.py \
  tests/test_dual_parse_figures.py
git diff --cached --check
git commit -m "feat: reconcile dual parse evidence inputs"
```

---

### Task 5: Scientific Owner — 双层安全 Content Agent package

**Files:**

- Create: `tests/test_dual_parse_content_package.py`
- Modify: `review_writer/project/content_agent_handoff.py`
- Modify: `schemas/agents/content_agent_request.v1.schema.json`
- Modify: `tests/test_content_agent_handoff.py`
- Modify: `tests/test_chemical_paper_integration.py`

- [ ] **Step 1: 写双层、study-local、安全 RED**

```python
def test_core_package_has_current_dual_safe_inputs_only(project: Path, tmp_path: Path) -> None:
    package = build_content_task_package(project, paper_request("study-a"), tmp_path / "pkg")
    kinds = {row["kind"] for rows in package["inputs"].values() for row in rows}
    assert kinds == {
        "source_asset:pdf", "source_asset:canonical_markdown",
        "source_asset:content_list", "parse_quality_safe_projection",
        "chemical_paper_safe_projection", "reconciliation_safe_projection",
    }
    encoded = json.dumps(package).casefold()
    for forbidden in ("molblock", "archive_sha256", "source_pdf_sha256", "/home/"):
        assert forbidden not in encoded
```

另测 study-b package 不含 study-a Evidence；core 任一 gate 未闭合时 package 零写入；background Generic-only 合法；旧 result 在任一 lane 更新后 zero-write。

- [ ] **Step 2: 运行 RED**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_dual_parse_content_package.py tests/test_content_agent_handoff.py   tests/test_chemical_paper_integration.py
```

- [ ] **Step 3: 删除 Chemical-only 分支**

Paper Evidence package 对每个 target study 按 request 的显式 field dependencies 调用 `require_dual_evidence_ready(..., requires_chemical=...)`，再加入原始 PDF、当前 Generic safe inputs，以及仅在 Chemical-required 时加入 Chemical safe projection 和 Reconciliation safe projection。不得复制 raw Chemical state 或完整 MolBlock。

- [ ] **Step 4: 保持 request kind 隔离**

`paper_evidence` 永不含已有 Evidence；`synthesis_claims` 才含全部已批准 Paper Evidence/Comparison/Coverage；`section_draft` 再加 Synthesis/Section Contracts。三类 package currentness 分开。

- [ ] **Step 5: GREEN、Owner gate 与提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_dual_parse_bootstrap.py tests/test_dual_source.py   tests/test_chemical_completion.py tests/test_parse_reconciliation.py   tests/test_dual_parse_content_package.py tests/test_source_truth.py   tests/test_parse_quality.py tests/test_chemical_paper_import.py   tests/test_paper_evidence.py tests/test_content_agent_handoff.py
make smoke
make quality-check
git add -- review_writer/project/content_agent_handoff.py   schemas/agents/content_agent_request.v1.schema.json   tests/test_content_agent_handoff.py tests/test_chemical_paper_integration.py   tests/test_dual_parse_content_package.py
git diff --cached --check
git commit -m "feat: package current dual parse evidence inputs"
git status --short --branch
```

Handoff 返回 ordered commits、parent `eb9964a`、测试计数、smoke/quality、clean status。

---

### Task 6: Dashboard UI Owner — Dual Parse/Completion/Reconciliation 工作区

**Files:**

- Create: `view/assets/dashboard/review-dual-parse.js`
- Create: `view/assets/dashboard/review-dual-parse.css`
- Create: `tests/test_dashboard_dual_parse_ui.py`
- Modify: `view/assets/dashboard/review.html`
- Modify: `view/assets/dashboard/review-chemical-paper.js`
- Modify: `view/assets/dashboard/review-chemical-paper.css`
- Modify: `view/assets/dashboard/review-ui.css`

- [ ] **Step 1: 写 safe model、DOM、keyboard RED**

```python
def test_page_exposes_four_states_and_completion_queue() -> None:
    html = REVIEW_HTML.read_text(encoding="utf-8")
    for node_id in (
        "dual-parse-workspace", "dual-study-status", "chemical-import-preflight",
        "chemical-completion-queue", "reconciliation-list",
    ):
        assert f'id="{node_id}"' in html


def test_visible_literals_hide_internal_fields() -> None:
    script = DUAL_SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("archive_sha256", "source_pdf_sha256", "state_digest", "molblock"):
        assert forbidden not in visible_text_literals(script)
```

断言没有 credits、没有 accepted `chemical-paper-zip-only` dependency、没有默认 lane、import 两步确认、batch actor/reason/PDF locator 和 dialog keyboard contract。

- [ ] **Step 2: 运行 RED**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_dashboard_dual_parse_ui.py tests/test_dashboard_chemical_paper_ui.py
```

- [ ] **Step 3: 实现纯 model API**

```javascript
window.ReviewDualParseUI = {
  projectionModel(payload),
  importPreflightRequest(studyId, file),
  importConfirmRequest(studyId, preflightToken),
  completionBatchRequest(studyId, versionToken, rows, actor),
  reconciliationRequest(studyId, objectId, registryDigest, decision, actor),
  render(document, mount, model),
  load(projectId),
};
```

Unknown 保持未知。Opaque tokens 只存在 JS closure/request body，不写 DOM、URL 或 aria-label。JS 参数使用 camelCase，但 HTTP request body 固定序列化为 `study_id`、`preflight_token`、`version_token`、`registry_digest`、`object_id`、`actor_type`、`actor_label`。

- [ ] **Step 4: 实现 study cards 与两步 import**

每篇显示 PDF verified、Generic Parse、Chemical import/completion、Evidence availability 和 Honest Progressive Route 状态。正式 importer 的 preflight → confirm 只能由 Integration Owner/Coordinator boundary 触发；Dashboard/Researcher 只消费 safe projection，不接收 ZIP/PDF path/hash。正式 import 前 Chemical availability、309 denominator、三态计数、coverage 和 gap registry 必须保持 unknown/unavailable；3/3 current 后显示每篇 `125/109/75`、总计 `309`、`unavailable_not_provided`、`CONFIRMED/AI_PROVISIONAL/BLOCKED` 计数与可见 gap registry。

- [ ] **Step 5: 实现 batch Completion 与 Reconciliation**

Completion queue 在 authoritative rows 存在后显示三态 molecule rows、缺失名称/标签、单一 `resolved_smiles`、confidence/provenance、PDF page/bbox/reason 与 gap registry；正式 import 前必须保留 unknown/unavailable，不得把 expanded/unexpanded 变成两套输入。Stale 时保留输入并要求刷新。Reconciliation 并排显示两候选与 PDF；conflict 只允许 `pdf_resolved|pdf_locator_only|reject_both`。

- [ ] **Step 6: 响应式/键盘**

`1440x1000` 三栏，`1024x900` PDF 上方+候选双栏，`390x844` 单栏观察。Modal 支持 Tab/Shift+Tab/Escape/focus return；loading 显示真实 task/failure/retry。

- [ ] **Step 7: GREEN 与提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_dashboard_dual_parse_ui.py tests/test_dashboard_chemical_paper_ui.py   tests/test_dashboard_evidence_workspace.py tests/test_dashboard_manuscript_release_ui.py
for file in view/assets/dashboard/review*.js; do node --check "$file"; done
git add -- view/assets/dashboard/review-dual-parse.js   view/assets/dashboard/review-dual-parse.css view/assets/dashboard/review.html   view/assets/dashboard/review-chemical-paper.js   view/assets/dashboard/review-chemical-paper.css view/assets/dashboard/review-ui.css   tests/test_dashboard_dual_parse_ui.py
git diff --cached --check
git commit -m "feat: add dual parse researcher workspace"
make smoke
make quality-check
git status --short --branch
```

不运行独立 Playwright Reviewer。

---

### Task 7: Release Backend Owner — 安全 HTTP、lineage 与 Hard Fail

**Files:**

- Create: `review_writer/delivery/dual_parse_release.py`
- Create: `tests/test_dual_parse_release.py`
- Create: `tests/test_dashboard_dual_parse_api.py`
- Modify: `view/serve_review_dashboard.py`
- Modify: `review_writer/delivery/project_release.py`
- Modify: `review_writer/project/manuscript_v2.py`
- Modify: `review_writer/evaluation/review_benchmark.py`
- Modify: `schemas/delivery/manuscript_lineage.v2.schema.json`
- Modify: `schemas/delivery/project_release.v2.schema.json`
- Modify: `schemas/quality/review_benchmark_report.v1.schema.json`
- Modify: `tests/test_manuscript_v2.py`

- [ ] **Step 1: 写 preflight/confirm 安全 RED**

```python
def test_preflight_writes_no_authoritative_state(api_project: Path, chemical_zip: Path) -> None:
    before = snapshot_authoritative(api_project)
    status, body = post_zip("/chemical-paper/preflight?study_id=study-a", chemical_zip)
    assert status == 200
    assert body["status"] == "ready_for_confirmation"
    assert snapshot_authoritative(api_project) == before


def test_confirm_revalidates_and_records_actor(api_project: Path, chemical_zip: Path) -> None:
    token = preflight(api_project, chemical_zip)["preflight_token"]
    status, body = post_json("/chemical-paper/confirm", {
        "study_id": "study-a", "preflight_token": token,
        "actor_type": "simulated_researcher_agent",
        "actor_label": "simulated_researcher",
    })
    assert status == 200
    assert body["status"] == "imported"
```

拒绝 staged drift、expired token、wrong study、second confirm、oversize/unsafe ZIP、bad content type；响应无 path/hash/raw/internal error。

- [ ] **Step 2: 写 release currentness RED**

```python
def test_internal_release_requires_current_dual_bindings(project: Path) -> None:
    assert dual_parse_release_state(project)["internal_release_ready"] is True
    mutate_generic_parse(project, "study-a")
    stale = dual_parse_release_state(project)
    assert stale["internal_release_ready"] is False
    assert "DUAL_PARSE_STALE" in stale["hard_fails"]


def test_reaction_absence_is_not_zero_or_global_hard_fail(project: Path) -> None:
    release = dual_parse_release_state(project)
    assert release["reaction_data_status"] == "unavailable_not_provided"
    assert release["reaction_count"] is None


def test_manuscript_lineage_binds_current_dual_versions(project: Path) -> None:
    merge_authoritative_manuscript(project)
    lineage = json.loads(
        (project / "04_manuscript/manuscript_lineage.v2.json").read_text(encoding="utf-8")
    )
    assert len(lineage["dual_parse_bindings"]) == 3
    mutate_chemical_completion(project, "study-a")
    state = manuscript_state(project)
    assert state["workflow_can_continue"] is False
    assert state["reason_code"] == "MANUSCRIPT_DUAL_PARSE_STALE"
```

- [ ] **Step 3: 实现 routes**

```text
GET   /api/project/{id}/dual-parse
POST  /api/project/{id}/chemical-paper/preflight?study_id={study}
POST  /api/project/{id}/chemical-paper/confirm
PUT   /api/project/{id}/chemical-completion
PUT   /api/project/{id}/parse-reconciliation
```

Preflight 接受最多 64 MiB `application/zip`，只写非权威 staging；confirm 在 lock 内重验 token/bytes/PDF/Source Truth 后正式导入。GET 只返回 human labels、counts、safe fields、actor/time、PDF page URLs 和唯一 next action。

- [ ] **Step 4: 实现 release binding**

```python
def dual_parse_release_bindings(project: Path) -> dict[str, object]: ...
def validate_dual_parse_release_bindings(project: Path, bindings: object) -> dict[str, object]: ...
def dual_parse_release_state(project: Path) -> dict[str, object]: ...
```

Manuscript lineage 固定记录每篇实际依赖 study 的 Generic、Chemical、Honest Progressive Completion projection、Reconciliation versions；任一依赖对象变更只 stale 受影响 manuscript/section。Internal release 要求 core 的 dual binding、三态 projection、Reconciliation、manuscript lineage 和 claim dependencies current。Coverage < 0.80 可保留 source/evidence preparation，但受影响的 exact-claim/release path 必须显示 `needs_more_traceable_candidates` 与 gap registry；Background 仅按显式 Chemical dependency 检查。

- [ ] **Step 5: 增加 Hard Fails**

```text
CORE_GENERIC_PARSE_MISSING_OR_STALE
CORE_CHEMICAL_IMPORT_MISSING_OR_STALE
HONEST_PROGRESSIVE_COVERAGE_BELOW_THRESHOLD
HONEST_PROGRESSIVE_GAP_UNDISCLOSED
PARSE_RECONCILIATION_UNRESOLVED
DUAL_SOURCE_BINDING_MISMATCH
STALE_DUAL_PARSE_CONTENT_RESULT
AI_AUTHORED_SMILES
REACTION_ABSENCE_MISREPRESENTED
```

Optional element review 仍是 issue；`awaiting_human_figure` 只阻塞 expert release。

- [ ] **Step 6: GREEN 与提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_dashboard_dual_parse_api.py tests/test_dual_parse_release.py \
  tests/test_chemical_paper_release.py tests/test_project_release_v2.py \
  tests/test_release_evaluation_payload.py tests/test_review_benchmark.py \
  tests/test_manuscript_v2.py tests/test_docx_integrity.py
git add -- review_writer/delivery/dual_parse_release.py \
  view/serve_review_dashboard.py review_writer/delivery/project_release.py \
  review_writer/project/manuscript_v2.py review_writer/evaluation/review_benchmark.py \
  schemas/delivery/manuscript_lineage.v2.schema.json \
  schemas/delivery/project_release.v2.schema.json \
  schemas/quality/review_benchmark_report.v1.schema.json tests/test_manuscript_v2.py \
  tests/test_dashboard_dual_parse_api.py tests/test_dual_parse_release.py
git diff --cached --check
git commit -m "feat: bind dual parse release authority"
make smoke
make quality-check
git status --short --branch
```

---

### Task 8: QA Protocol Owner — 独立 Agent 全流程协议

**Files:**

- Create: `docs/qa/three-paper-dual-parse-evidence-to-release-playwright.md`
- Create: `tests/test_dual_parse_qa_protocol.py`

- [ ] **Step 1: 写角色与 checkpoint RED**

```python
def test_protocol_requires_fresh_simulated_researcher() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    for required in (
        "simulated_researcher_agent", "brand-new browser context",
        "must not read repository", "must not inspect request or response bodies",
        "must not implement or repair product code",
    ):
        assert required in text


def test_protocol_has_dual_lanes_and_two_restarts() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    for required in (
        "Generic MinerU", "Chemical Paper", "Chemical Completion", "Reconciliation",
        "READY_FOR_RESTART_1", "READY_FOR_RESTART_2", "CONTENT_AGENT_REQUEST",
        "1440x1000", "1024x900", "390x844",
    ):
        assert required in text
```

- [ ] **Step 2: 运行 RED**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_dual_parse_qa_protocol.py
```

- [ ] **Step 3: 写 19-checkpoint 协议**

顺序固定：

1. Task 10/Coordinator-only pre-run：fresh v3 只有 3 PDF + 3 fresh Generic current；记录 Chemical availability/status、分母、三态计数、coverage、coverage_sufficient 与 gap registry 均为 unknown/unavailable（不得渲染为 0），唯一 next action 为 `待 Chemical Paper 导入`；
2. Integration Owner 通过正式 preflight → confirm → importer 完成三份 approved Chemical input，验证 3/3 current、pages `6/11/11`、molecules `125/109/75=309`、`reaction_data_status=unavailable_not_provided`，生成 safe projection 和 runtime readiness；
3. readiness 完成后才创建 fresh browser/context 与 Playwright Researcher，并在可见 UI 中记录 project/stage/blocker/唯一 next action；Researcher 不接收 ZIP/PDF path/hash、不执行 importer；
4. Completion Queue 审核 `CONFIRMED`、`AI_PROVISIONAL`、`BLOCKED` 三态；分别保留 researcher confirmation/PDF locator、PDF locator+confidence+provenance、`value=null`+`gap_reason`；不得把缺失值压成零或把 expanded/unexpanded 变成两套输入；
5. Dual Parse/PDF/Reconciliation；
6. 三篇 Paper Evidence；
7. refresh persistence；
8. Comparison/Coverage/Synthesis；
9. Sections、5–8 slots、Source Figures/gaps/placeholders；
10. 高风险编辑后 `READY_FOR_RESTART_1`；
11. Restart 1 对比、internal DOCX、expert blocked；
12. benchmark/Hard Fails；
13. credits hidden/`NOT_APPLICABLE_BY_CURRENT_SCOPE`；
14. refresh release/currentness；
15. `READY_FOR_RESTART_2` 与对比；
16. `1024x900`；
17. `390x844` observational；
18. console/network；
19. final evidence、close、tri-state。

Formal preflight/confirm/import 由 Integration Owner 通过 importer 完成并留
Coordinator-only receipt；Researcher 只观察安全 projection，不使用 file chooser，
也不读取 ZIP 内容或任意文件系统。

- [ ] **Step 4: Content request 与 stop gate**

`CONTENT_AGENT_REQUEST` 包含 round/project/request kind/study/surface/visible gap/screenshot/resume checkpoint。任何 P0/P1 或 science-affecting P2 结束当前 acceptance run；修复后必须从头新跑。

- [ ] **Step 5: Artifact audit contract**

要求 bootstrap isolation、3 Generic/3 Chemical coordinator-only binding、309 authoritative molecule rows 的三态计数与 gap registry、study-local packages、DOCX pages/contact sheet、新旧内容差异、benchmark、restart ledger、Git/full regression；reaction 必须保持 `unavailable_not_provided`。

- [ ] **Step 6: GREEN 与提交**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_dual_parse_qa_protocol.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_honest_progressive_docs_contract.py
git add -- docs/qa/three-paper-dual-parse-evidence-to-release-playwright.md   tests/test_dual_parse_qa_protocol.py tests/test_honest_progressive_docs_contract.py
git diff --cached --check
git commit -m "docs: define independent dual parse QA protocol"
git status --short --branch
```

QA Owner 不运行 Playwright、不写真实项目、不宣称 PASS。

---

### Task 9: Integration Owner — 集成四个 Owner commits

**Files:**

- Integrate Scientific、Release、UI、QA commits
- Create: `tests/test_dual_parse_integration.py`

- [ ] **Step 1: 只读审计 handoffs**

```zsh
git status --short --branch
git rev-parse HEAD
for commit in "$scientific_commit" "$release_commit" "$ui_commit" "$qa_commit"; do
  git cat-file -e "$commit^{commit}"
  git merge-base --is-ancestor eb9964a "$commit"
  git show --check --oneline "$commit"
done
```

四分支必须 clean、共同 parent 正确、未 push。

- [ ] **Step 2: 创建唯一 integration worktree**

```zsh
git -C /home/kenqia/my_folder/review-writer worktree add \
  -b codex/e2r-dual-integration \
  /home/kenqia/my_folder/review-writer/.worktrees/e2r-dual-integration eb9964a
```

- [ ] **Step 3: 按顺序集成**

```zsh
git merge --no-ff "$scientific_commit" -m "merge: integrate dual parse scientific authority"
git merge --no-ff "$release_commit" -m "merge: integrate dual parse release authority"
git merge --no-ff "$ui_commit" -m "merge: integrate dual parse dashboard"
git merge --no-ff "$qa_commit" -m "merge: integrate dual parse QA protocol"
```

冲突必须保留 Generic+Chemical、PDF authority、researcher-only SMILES、safe projection、object-level stale、study-local package、internal/expert 双层 release、credits hidden 和角色隔离。

- [ ] **Step 4: 写跨合同测试**

```python
def test_cockpit_package_and_release_share_dual_currentness(realistic_project: Path) -> None:
    cockpit = project_cockpit_payload(ROOT, realistic_project.name)
    package = build_content_task_package(realistic_project, paper_request("study-a"))
    release = dual_parse_release_state(realistic_project)
    assert cockpit["dual_parse_status"] == "current"
    assert package["request_kind"] == "paper_evidence"
    assert release["dual_parse_status"] == "current"


def test_reparse_stales_ui_package_and_release_together(realistic_project: Path) -> None:
    mutate_generic_parse(realistic_project, "study-a")
    assert project_cockpit_payload(ROOT, realistic_project.name)["dual_parse_status"] == "stale"
    with pytest.raises(ContentAgentError, match="DUAL_SOURCE_STALE"):
        build_content_task_package(realistic_project, paper_request("study-a"))
    assert dual_parse_release_state(realistic_project)["internal_release_ready"] is False
```

- [ ] **Step 5: 运行 focused + Task 14 + Dashboard/release gates**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_dual_parse_bootstrap.py tests/test_dual_source.py   tests/test_chemical_completion.py tests/test_parse_reconciliation.py   tests/test_dual_parse_content_package.py tests/test_dashboard_dual_parse_ui.py   tests/test_dashboard_dual_parse_api.py tests/test_dual_parse_release.py   tests/test_dual_parse_integration.py tests/test_dual_parse_qa_protocol.py

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_parse_quality.py tests/test_paper_evidence.py   tests/test_evidence_synthesis.py tests/test_review_figures.py   tests/test_manuscript_v2.py tests/test_docx_integrity.py   tests/test_review_benchmark.py tests/test_workflow_projection.py

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider   tests/test_vertical_review_projection.py tests/test_qoderwork_native_review_writer.py   tests/test_project_release.py tests/test_project_release_v2.py   tests/test_release_evaluation_payload.py tests/test_chemical_paper_release.py
```

- [ ] **Step 6: smoke/quality/static safety**

```zsh
for file in view/assets/dashboard/review*.js; do node --check "$file"; done
make smoke
make quality-check
git diff --check eb9964a..HEAD
git show --check --oneline HEAD
git status --short --branch
```

扫描 diff：无 PDF/ZIP/MinerU output/project artifact/token/browser state/绝对 data path。全部通过才返回 `CODE_FREEZE_READY=OK`；不跑最终完整回归，不宣称 QA PASS。

---

### Task 10: Integration Owner — Fresh v3 project 与唯一 runtime

**External project:** `<DATA_ROOT>/review-projects/vis-light-olefin-difunctionalization-complete-loop-regression-v3-dual-parse`

- [ ] **Step 1: 证明 target 不存在**

目标存在时停止并选择新的非覆盖 ID，不删除或覆盖。只在 Coordinator-only
证据中记录输入 path/hash，不向 Dashboard/Researcher 暴露；不得复用 v2
Generic ZIP 或旧 Generic outputs。

- [ ] **Step 2: 用正式 CLI bootstrap**

```zsh
typeset -r E2R_DUAL_RUN_ROOT=$(mktemp -d /tmp/review-writer-e2r-dual-run.XXXXXX)
python scripts/run_vertical_review.py bootstrap-dual-parse \
  --review-root '<DATA_ROOT>/review-projects' \
  --request "$E2R_DUAL_RUN_ROOT/bootstrap-request.json"
```

审计只有 brief/discovery/sources，零 `01_evidence` 和下游对象。

- [ ] **Step 3: 在用户配置的 zsh 环境只检查 token present**

```zsh
zsh -ic 'if [[ -n ${MINERU_API_TOKEN:-} ]]; then
  print -r -- MINERU_TOKEN_PRESENT
else
  print -r -- MINERU_TOKEN_MISSING
  exit 2
fi'
```

`zsh -ic` 只用于加载用户已有的 `~/.zshrc`；不得读取文件内容、输出值、记录值或用 `--token` 参数。Missing 时停止，不创建伪解析状态。

- [ ] **Step 4: 运行 Generic MinerU precise API**

```zsh
zsh -ic 'python skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py \
  --input-dir "<FRESH_PROJECT>/00_sources/papers" \
  --output-dir "'"$E2R_DUAL_RUN_ROOT"'/generic-mineru" \
  --language en --model-version vlm --batch-size 3 \
  --poll-interval 5 --timeout-minutes 30'
```

输出目录由本轮 `mktemp` 新建，因此不使用 `--force`。保持 formula/table enabled，不启用 OCR；失败先报告，不改参数猜测。

- [ ] **Step 5: 正式绑定 Generic output**

```zsh
python scripts/run_vertical_review.py bind-generic-parse \
  --project '<FRESH_PROJECT>' \
  --mineru-output "$E2R_DUAL_RUN_ROOT/generic-mineru"
```

验证 3/3 Source Truth、3/3 Parse 自动 assessment、0 人工决定、0 Evidence。

- [ ] **Step 6: 正式 preflight/confirm/import 三份 Chemical ZIP**

Integration Owner 在 Coordinator-only boundary 内验证 approved ZIP/PDF 对应和
安全性，并通过正式 preflight → confirm → importer 完成三份 authoritative
imports；不手工解压、不使用 v2 Generic ZIP/旧 Generic outputs。Importer receipt、
3/3 current safe projection、pages `6/11/11`、molecules `125/109/75=309` 和
`reaction_data_status=unavailable_not_provided` 只进入 Coordinator evidence，
不向 Dashboard/Researcher 暴露 path/hash。Playwright Researcher 不执行 import。

- [ ] **Step 7: 记录 isolation audit**

先证明 fresh bootstrap 的 3 PDFs、3 fresh Generic、0 Chemical imports，以及
Chemical availability/status、denominator、三态 counts、coverage、gap registry
均为 unknown/unavailable（不可压成 0）；正式 importer 后再证明 3/3 Chemical
current、authoritative rows 与 server-calculated counts。两个阶段都必须证明
0 decisions/Evidence/Synthesis/Sections/Figures/Manuscript/DOCX/Release/
Evaluation/Content results/old browser state。

- [ ] **Step 8: 启动唯一 Dashboard**

```zsh
python view/serve_review_dashboard.py   --review-root '<DATA_ROOT>' --host 127.0.0.1 --port 63822
```

记录 PID/revision/project/start/readiness local+UTC；验证 `/review`、projects、progress、parse-quality、cockpit、dual-parse、review-figures 七端点 HTTP 200。写 `protocol_restart=false` integrated-start receipt，不计 Restart 1/2。

- [ ] **Step 9: QA handoff**

```text
FRESH_DUAL_PROJECT_READY=OK
INTEGRATED_REVISION=<sha>
PROJECT=vis-light-olefin-difunctionalization-complete-loop-regression-v3-dual-parse
URL=http://127.0.0.1:63822/review
PID=<pid>
VISIBLE_STAGE=<dual parse review>
UNIQUE_NEXT_ACTION=<formal import current; Researcher may now be created>
```

只有 formal import、safe projection 和 runtime readiness 全部可核验后，才
创建新 Playwright Researcher。不创建 Content package、不运行 Playwright。

---

### Task 11: Independent QA Coordinator — Playwright Researcher 与 Content Agents

**Protocol:** `docs/qa/three-paper-dual-parse-evidence-to-release-playwright.md`

**Evidence root:** `/tmp/review-writer-e2r-dual-round/`

- [ ] **Step 1: 创建全新 Playwright Researcher Agent**

仅在 Task 10 formal import、safe projection、runtime readiness 和
Coordinator-only receipt 全部核验后创建。只提供 URL、visible project、
`simulated_researcher_agent` persona 和 protocol，不提供 ZIP/PDF paths、hashes
或 raw data。Agent 未参与设计/实现/旧 Round 2。

- [ ] **Step 2: 核验三份正式 Chemical import**

Researcher 只观察并核验已完成的 3/3 current safe projection：pages
`6/11/11`、molecules `125/109/75`（总计 `309`）、backend/version、reaction
`unavailable_not_provided` 和唯一 next action。它不得查看 hashes/paths/raw
JSON，不得通过 file chooser、preflight 或 confirm 改变 authoritative state。

- [ ] **Step 3: 完成 Honest Progressive Completion**

Agent 依据可见 PDF/结构 locator 审核每个 molecule 的 `CONFIRMED`,
`AI_PROVISIONAL` 或 `BLOCKED` 状态；`CONFIRMED` 必须有 researcher
confirmation，`AI_PROVISIONAL` 必须保留 PDF locator、confidence、provenance，
`BLOCKED` 必须是 `value=null` + `gap_reason`。无法确定则保留 blocked 并写入
gap registry，禁止猜值或伪造科学批准。低于 80% 时仍可继续 source/evidence
preparation，但必须显示 `needs_more_traceable_candidates`。最终由服务端核对
每论文 `125/109/75`、总计 `309`、`confirmed_count + ai_provisional_count`、
coverage `/309`、threshold `0.80` 和 `coverage_sufficient`，不得信任客户端或
旧双字段计数。

- [ ] **Step 4: 完成 Parse/Reconciliation**

核验 PDF、Generic、Chemical、Source Figure locator，处理所有 needs-review/conflict。决定显示 `simulated_researcher_agent` 并持久。

- [ ] **Step 5: 三个独立 Evidence Content Agents**

每次 `CONTENT_AGENT_REQUEST` 后，由 Coordinator 建立该 study fresh package、派发新 Agent、验证 candidate-only/current/study-local、正式导入，再恢复原 Researcher。三篇不得共用一个 Evidence Agent。

- [ ] **Step 6: 新 Synthesis/Section Agents**

Synthesis Agent 消费已批准多 study Evidence；Section Agents 按批准 contract 起草。角色、request kind、result 分开。

- [ ] **Step 7: Figure/Manuscript 人工操作**

Researcher 选择每篇可追溯 Source Figure或记录真实 gap，确认 5–8 slots/placeholders，完成至少一次高风险正文直接编辑和逐节批准。

- [ ] **Step 8: Restart 1**

checkpoint 10 收到 `READY_FOR_RESTART_1` 后，Integration Owner 对同一 revision/project/URL 真实重启，写 `protocol_restart=true, sequence=1` receipt；Researcher 对比同一对象。

- [ ] **Step 9: DOCX/benchmark/release**

UI 下载 `SELF_REVIEWED_DRAFT`；expert release 因 placeholder 禁用；benchmark ≥80、七维 rationale、无适用 Hard Fail；credits 不可见并记录 N/A。

- [ ] **Step 10: Restart 2**

checkpoint 15 收到 `READY_FOR_RESTART_2` 后执行真实重启与 `sequence=2` receipt；再次比较 manuscript/actor/download/evaluation/blocker。

- [ ] **Step 11: Viewports/console/network**

完成 `1024x900` mandatory、`390x844` observational；console 零 warning/error；请求无异常 4xx/5xx、duplicate mutation、unbounded retry。

- [ ] **Step 12: 返回 tri-state**

只有完整 run 所有 mandatory evidence 完整、零 P0/P1 和 science-affecting P2 才可 PASS。否则 BLOCKED 或 ENVIRONMENT_UNDETERMINED；Reviewer 不修代码。

---

### Task 12: Artifact audit、最终完整回归与交付

- [ ] **Step 1: DOCX 全页视觉检查**

渲染 PDF 和逐页 PNG/contact sheet，检查 clipping、blank page、headings、formula/chemical symbols、figures、captions、page breaks、references、placeholders。

- [ ] **Step 2: 证明不是旧稿**

比较新旧 Markdown、`word/document.xml`、media hashes；验证 Markdown↔DOCX normalized text、current manuscript lineage 和 dual release binding。Hashes 仅 Coordinator 可见。

- [ ] **Step 3: 审计双层科学状态**

记录 3 PDF、3 Generic、3 Chemical、每论文 `125/109/75`（总计 309）与 `unavailable_not_provided`；审计每条 molecule 的 `CONFIRMED`/`AI_PROVISIONAL`/`BLOCKED` 状态、coverage=`(confirmed+ai_provisional)/309`、threshold=`0.80`、gap registry、uncertainty/provenance 与 actor/currentness。未知或缺失保持 unknown/null，不得压成 0；reconciliation closed/currentness 仍需核对。

- [ ] **Step 4: 最终完整回归只运行一次**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -s -q -p no:cacheprovider \
  tests/test_source_truth.py tests/test_parse_quality.py \
  tests/test_dual_parse_bootstrap.py tests/test_dual_source.py \
  tests/test_chemical_completion.py tests/test_parse_reconciliation.py \
  tests/test_dual_parse_figures.py tests/test_paper_evidence.py \
  tests/test_dual_parse_content_package.py tests/test_evidence_synthesis.py \
  tests/test_review_figures.py tests/test_manuscript_v2.py \
  tests/test_docx_integrity.py tests/test_review_benchmark.py \
  tests/test_workflow_projection.py tests/test_vertical_review_projection.py \
  tests/test_qoderwork_native_review_writer.py tests/test_dashboard_dual_parse_ui.py \
  tests/test_dashboard_dual_parse_api.py tests/test_project_release.py \
  tests/test_project_release_v2.py tests/test_release_evaluation_payload.py \
  tests/test_chemical_paper_release.py tests/test_reusable_library.py \
  tests/test_review_batch_runner.py tests/test_dual_parse_release.py \
  tests/test_dual_parse_integration.py
make smoke
make quality-check
```

记录新鲜 passed/failed/deselected 和耗时，不沿用历史计数。

- [ ] **Step 5: Git/safety**

```zsh
git status --short --branch
git log --oneline --decorate eb9964a..HEAD
git diff --check eb9964a..HEAD
git diff --stat eb9964a..HEAD
git show --check --oneline HEAD
```

确保无 PDF、ZIP、MinerU output、project data、token/env、browser storage、标准全文、自动综合图或绝对 data path。

- [ ] **Step 6: 最终报告**

包含 integrated ancestry、project/URL/PID/restarts、3+3+309、Evidence/Synthesis/Sections/Figures、actor/high-risk edit、DOCX pages/非旧稿、benchmark/Hard Fails、console/network/viewports、tests/smoke/quality/Git safety、QA tri-state，并明确 `SELF_REVIEWED_DRAFT` 不是投稿级、专家发布、真实用户接受或科学完美。

---

## 3. Owner handoff 格式

每个并行会话最终只返回：

```text
OWNER=<scientific-state|dashboard-ui|release-backend|qa-protocol>
BRANCH=<branch>
PARENT=eb9964a
COMMITS=<ordered local commits>
HEAD=<sha>
FILES=<owned paths>
FOCUSED_TESTS=<count and command>
BROADER_GATES=<count and command>
SMOKE=<pass|not-applicable>
QUALITY=<pass|not-applicable>
GIT_SHOW_CHECK=pass
GIT_STATUS=clean
PUSHED=false
PLAN_CHECKBOX_CHANGED=false
KNOWN_INTEGRATION_NOTES=<exact overlap only>
```

不得写“应该通过”或省略失败测试证据。

## 4. 集成冲突预判

高概率冲突：`view/serve_review_dashboard.py`、`review.html`、`content_agent_handoff.py`、release schemas、旧 Chemical-only route tests。Integration Owner 不得简单选择 ours/theirs；必须保留双层输入、PDF authority、researcher-only SMILES、safe projection、object-level stale、study-local package、双层 release、credits hidden、角色隔离。

## 5. 回滚边界

- 每个 Owner task 独立 commit，使用普通 `git revert` 回滚；
- integration 使用 merge commits，可逐 Owner revert；
- fresh project 非覆盖，失败时保留为 QA evidence；
- Generic MinerU output 在 `mktemp` 创建的独立 `/tmp` run root，绑定失败不污染项目；
- Chemical preflight 零权威写入；
- repair/runtime start 不计协议 restart；
- 不使用 `git reset --hard`、`git checkout --` 或递归删除回滚。

## 6. 完成判定

同时满足才完成：

1. 四 Owner commits 集成且 ancestry 可证；
2. fresh dual-parse project 隔离成立；
3. 3 Generic + 3 Chemical + 每论文 `125/109/75`（总计 309）authoritative rows 成立；每条 row 使用三态之一，coverage 按 `(confirmed+ai_provisional)/309`、threshold `0.80` 计算，gap registry 与 `unavailable_not_provided` 如实可见；
4. Playwright Researcher Agent 完成全部产品内人工操作；
5. 新 Content Agents 无跨 study/旧 result reuse；
6. checkpoints 1–19、两次真实 restart、三视口、console/network 完整；
7. internal DOCX/PDF、benchmark ≥80、无适用 Hard Fail；
8. final regression、smoke、quality、Git safety 通过；
9. 独立 QA 给出 PASS；
10. 交付仍明确为 `SELF_REVIEWED_DRAFT`。
