# Source Truth + Object-level Parse Quality First Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 WSL 中复用现有三篇可见光案例，交付每项研究独立的 Source Truth Bundle、对象级 Parse Quality Gate、可恢复的研究者复核界面，以及一次由全新独立 Agent 仅通过 Playwright MCP 完成的黑盒流程与视觉验收。

**Architecture:** 新增只读 legacy adapter，把 acquisition receipt、MinerU canonical Markdown、MinerU sidecar 与 text layers 闭合为每项研究独立的 Source Truth Bundle；旧 manifest 中的 Windows 绝对路径永不参与定位。Parse Quality 按正文顺序、章节、图文、表格、公式/化学符号、参考文献和 SI 七类对象产生确定性候选状态，再记录绑定 digest 的人工决定。Dashboard 只暴露研究者需要的标签、locator 和预览链接；`workflow_can_continue` 与 `automatic_extraction_allowed` 分开投影，选择“仅用原始 PDF”绝不放行自动证据抽取。

**Tech Stack:** Python 3.13 标准库、现有 JSON Schema 校验、`http.server` dashboard、原生 HTML/CSS/JavaScript、pytest/unittest、WSL zsh、Playwright MCP。

---

## 首轮边界与真实案例约束

本计划只实现：

```text
既有 Source Set + MinerU/text-layer 产物
→ 每项研究 Source Truth Bundle
→ 对象级 Parse Quality 候选状态
→ 研究者决定并持久化
→ 自动证据抽取 fail-closed
→ 现有 Evidence / Risk / Manuscript 只作下游回归展示
```

不在本轮实现 Typed Evidence、Synthesis Workspace、Comparison Protocol、Synthesis Claim、Figure Placeholder 或 Manuscript 高风险编辑。这些分别进入后续切片。

只读来源：

```text
/mnt/c/Users/26960/QW-RW/review-writer-e2e-acceptance-20260728-01/review-projects/vis-light-olefin-difunctionalization
```

WSL 外部副本：

```text
/home/kenqia/my_folder/review-writer-data/review-projects/vis-light-olefin-difunctionalization-wsl-v1
```

三篇主文固定为：

```text
10_1002_anie_202101775.pdf
10_1021_acscatal_2c03805.pdf
10_1021_jacs_3c06936.pdf
```

已确认的迁移事实必须进入测试：

1. acquisition `study_id` 是 `scholarly-*`，text-layer `source_id` 是 `stud-*`，MinerU 用 DOI slug；只能通过 receipt 中的 PDF 路径/hash 闭合，不能按相似字符串猜测。
2. `01_evidence/parses/manifest.json` 含失效的 Windows 绝对路径；adapter 必须忽略这些值并从受限项目相对位置重建路径。
3. 原始主文只认 `00_sources/papers/*.pdf`；`extracted/*_origin.pdf` 与其字节不同，不得替代。
4. canonical Markdown 只认 `01_evidence/mineru/markdown/<slug>.md`；它与 `01_evidence/parses/markdown/<slug>.md` 一致，但与 `extracted/<slug>/full.md` 不同，差异必须记录为 `duplicate_parse_drift` 警告。
5. 三篇仅有 MAIN，页数为 6、11、11；SI policy 均为 `NOT_REQUIRED`。这只是当前案例事实，代码仍须支持 receipt 中的 SI。
6. 项目已有 evidence、draft 和 release，不能证明 gate 位于抽取之前；该性质必须由 synthetic `prepare-study` 测试证明。

## 状态与决定合同

每项研究固定检查七类对象：

```python
PARSE_OBJECT_KINDS = (
    "body_order",
    "section_boundaries",
    "figure_caption_links",
    "table_structure",
    "formula_chemistry",
    "reference_boundary",
    "supplement_completeness",
)

AUTOMATIC_STATUSES = frozenset({
    "usable",
    "usable_with_review",
    "incomplete",
    "failed",
})

HUMAN_ACTIONS = frozenset({
    "approve_candidate_extraction",
    "pdf_locator_only",
    "reparse_required",
})
```

投影规则固定为：

| 对象情况 | 是否必须人工决定 | 可选动作 | `workflow_can_continue` | `automatic_extraction_allowed` |
| --- | --- | --- | --- | --- |
| `usable` 且无警告 | 否 | 无 | 是 | 是 |
| `usable_with_review` | 是 | 三选一 | 除 `reparse_required` 外是 | 仅 `approve_candidate_extraction` 是 |
| `incomplete` / `failed` | 是 | `pdf_locator_only` / `reparse_required` | 仅前者是 | 否 |
| 无决定、stale、未知值 | 是 | 无 | 否 | 否 |

`pdf_locator_only` 代表关闭解析复核并转人工 PDF locator；本轮不实现 locator 录入。因此 dashboard 可以进入 Evidence 工作区查看既有成果，但 `prepare-study` 必须返回 `PARSE_PDF_LOCATOR_ONLY`，不得创建新的 provider packet。

## 文件结构

新增：

- `review_writer/project/source_truth.py`：legacy adapter、受限路径、每项研究 bundle 构建/加载。
- `review_writer/project/parse_quality.py`：对象级自动检查、决定、gate 投影和失效。
- `schemas/evidence/source_truth_bundle.v1.schema.json`：持久 bundle 合同。
- `schemas/evidence/parse_quality_gate.v1.schema.json`：对象状态和人工决定合同。
- `tests/test_source_truth.py`：身份闭合、canonical 选择、hash、路径和真实案例只读兼容测试。
- `tests/test_parse_quality.py`：对象状态、动作约束、两种 continue 投影和 stale 测试。
- `docs/qa/vis-light-parse-quality-playwright.md`：独立 Agent 黑盒协议。

修改：

- `scripts/run_vertical_review.py`：`build-source-truth`、`record-parse-quality`、`prepare-study` fail-closed 和 gate digest 绑定。
- `tests/test_vertical_review_projection.py`：CLI、packet 失效和三研究投影测试。
- `view/serve_review_dashboard.py`：安全 GET/PUT、受限 Markdown/PDF 资产和 progress 真源。
- `view/assets/dashboard/review.html`：对象级解析复核工作区。
- `view/assets/dashboard/review-ui.css`：桌面/平板/手机布局。
- `tests/test_qoderwork_native_review_writer.py`：API、状态、恢复和 UI 接线。

外部数据只允许写 WSL 副本下的新 artifact，不提交真实 PDF、Markdown、图片、项目输出或 manifest。

---

### Task 1: 固化可审计基线并建立 WSL 案例副本

**Files:**

- Preserve: 当前 34 modified + 5 untracked 既有成果
- External create: `/home/kenqia/my_folder/review-writer-data/review-projects/vis-light-olefin-difunctionalization-wsl-v1`

- [ ] **Step 1: 重新确认精确基线**

```zsh
git status --short --branch
git diff --check
git diff --stat
git diff --cached --stat
```

Expected: 计划文档以外仍是已交接的 34 modified + 5 untracked，0 staged，`git diff --check` exit 0。若集合变化，先区分用户新增内容，不覆盖、不清理、不 stash。

- [ ] **Step 2: 运行既有成果的局部基线测试**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -s -q -p no:cacheprovider \
  tests/test_project_release.py \
  tests/test_qoderwork_native_review_writer.py \
  tests/test_reusable_library.py \
  tests/test_review_batch_runner.py
make smoke
make quality-check
```

Expected: 全部 PASS，且不调用 provider、MinerU 或网络。

- [ ] **Step 3: 审查既有成果的提交边界**

```zsh
git diff --name-status
git ls-files --others --exclude-standard
```

只把交接中明确归为 Product Rescue 的路径列入基线提交；计划文档、外部数据、`.env`、handoff 和未知新增内容排除。路径集合与交接不一致时暂停提交并向肯恰大人报告。

- [ ] **Step 4: 创建独立本地基线提交**

逐路径 `git add -- <reviewed paths>`，然后：

```zsh
git diff --cached --check
git diff --cached --name-status
git commit -m "chore: preserve review workbench e2e baseline"
```

Expected: 只有审查过的既有成果进入提交；不包含本计划、真实项目数据或秘密。该本地提交可用普通 `git revert` 回滚，不做远端写。

- [ ] **Step 5: 创建不覆盖的 WSL 副本**

```zsh
source_case=/mnt/c/Users/26960/QW-RW/review-writer-e2e-acceptance-20260728-01/review-projects/vis-light-olefin-difunctionalization
wsl_case=/home/kenqia/my_folder/review-writer-data/review-projects/vis-light-olefin-difunctionalization-wsl-v1
test -d "$source_case"
test ! -e "$wsl_case"
mkdir -p /home/kenqia/my_folder/review-writer-data/review-projects
cp -a "$source_case" "$wsl_case"
find "$wsl_case/00_sources/papers" -maxdepth 1 -type f -name '*.pdf' | wc -l
du -sh "$wsl_case"
```

Expected: 3 PDF，约 31 MB。目标已存在时只比较，不覆盖。

---

### Task 2: 实现每项研究 Source Truth Bundle

**Files:**

- Create: `schemas/evidence/source_truth_bundle.v1.schema.json`
- Create: `review_writer/project/source_truth.py`
- Create: `tests/test_source_truth.py`

- [ ] **Step 1: 写失败测试锁定身份闭合与路径选择**

测试 helper 构造 receipt、identity audit、coverage、MinerU manifest、canonical Markdown、parse sidecars 和 text-layer manifest。核心断言：

```python
def test_bundle_closes_study_slug_and_source_id_by_verified_pdf(tmp_path: Path) -> None:
    project = source_truth_fixture(tmp_path)
    bundle = build_source_truth_bundle(project, "scholarly-a")
    assert bundle["study_id"] == "scholarly-a"
    assert bundle["sources"][0]["source_id"] == "stud-a"
    assert bundle["sources"][0]["mineru_slug"] == "10_1000_example"
    assert bundle["sources"][0]["pdf"]["path"] == "00_sources/papers/10_1000_example.pdf"
    assert bundle["sources"][0]["canonical_markdown"]["path"] == (
        "01_evidence/mineru/markdown/10_1000_example.md"
    )


def test_bundle_ignores_absolute_parse_manifest_paths(tmp_path: Path) -> None:
    project = source_truth_fixture(tmp_path, parse_manifest_root=r"C:\\stale\\project")
    bundle = build_source_truth_bundle(project, "scholarly-a")
    visible = json.dumps(bundle)
    assert "C:\\\\" not in visible
    assert "/home/" not in visible


def test_bundle_rejects_hash_mismatch_links_and_ambiguous_binding(tmp_path: Path) -> None:
    project = source_truth_fixture(tmp_path)
    (project / "00_sources/papers/10_1000_example.pdf").write_bytes(b"changed")
    with pytest.raises(SourceTruthError, match="SOURCE_PDF_HASH_MISMATCH"):
        build_source_truth_bundle(project, "scholarly-a")


def test_bundle_marks_duplicate_markdown_drift_without_switching_canonical(tmp_path: Path) -> None:
    project = source_truth_fixture(tmp_path, extracted_markdown=b"different")
    bundle = build_source_truth_bundle(project, "scholarly-a")
    assert "duplicate_parse_drift" in bundle["warnings"]
    assert bundle["sources"][0]["canonical_markdown"]["path"].startswith(
        "01_evidence/mineru/markdown/"
    )
```

- [ ] **Step 2: 运行失败测试**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_source_truth.py
```

Expected: collection FAIL，模块和 schema 尚不存在。

- [ ] **Step 3: 定义 schema 和公开接口**

`source_truth_bundle.v1` 顶层必须是：

```python
{
    "schema_version": "source-truth-bundle.v1",
    "project_id": str,
    "study_id": str,
    "study_identity": {"doi": str | None, "title": str | None},
    "sources": [
        {
            "source_id": str,
            "document_role": "MAIN" | "SI",
            "source_type": "primary_study",
            "mineru_slug": str,
            "pdf": FileDescriptor,
            "canonical_markdown": FileDescriptor,
            "content_list": FileDescriptor,
            "layout": FileDescriptor,
            "reading_layer": FileDescriptor,
            "layout_layer": FileDescriptor,
            "page_count": int,
            "images": {"count": int, "digest": str},
        }
    ],
    "warnings": [str],
    "bundle_digest": str,
}
```

`FileDescriptor` 只含 `path`、`sha256`、`size_bytes`。schema 所有 object 均设置 `additionalProperties: false`，digest 使用 `^[0-9a-f]{64}$`，路径禁止绝对路径和 `..`。

根路径常量固定为 `SOURCE_TRUTH_ROOT = Path("01_evidence/source_truth")`。公开接口及返回合同固定为：

- `canonical_digest(value: object) -> str`：返回 canonical JSON 的 64 位小写 SHA-256。
- `build_source_truth_bundle(project: Path, study_id: str) -> dict[str, object]`：只读构建并完成 schema 校验，不写磁盘。
- `write_source_truth_bundle(project: Path, study_id: str) -> dict[str, object]`：调用 builder 后原子写单个 bundle，并返回写入值。
- `load_source_truth_bundle(project: Path, study_id: str) -> dict[str, object]`：读取、schema 校验并重新计算 digest；任何不一致抛 `SourceTruthError`。
- `build_all_source_truth(project: Path) -> list[dict[str, object]]`：按 receipt 中 `study_id` 排序构建全部 bundle，重复 id fail-closed。
- `source_truth_asset(project: Path, study_id: str, source_id: str, kind: str) -> Path`：`kind` 只允许 `pdf` 或 `parsed-markdown`，返回已重新校验 descriptor hash 的受限 Path。

`SourceTruthError(ValueError)` 构造器只接收稳定 `code: str`，同时把它保存为 `.code`；不得把绝对路径或底层异常文本放入 code。

- [ ] **Step 4: 实现确定性 legacy adapter**

实现顺序固定为：receipt 唯一匹配 `study_id` → receipt PDF 项目相对路径与 hash → MinerU row 以该相对 PDF 唯一匹配 → slug 仅允许 `[A-Za-z0-9_.-]+` → canonical Markdown 固定重建为 `01_evidence/mineru/markdown/<slug>.md` → extracted sidecar 固定重建为 `01_evidence/parses/extracted/<slug>/` → text layer 以 PDF hash 唯一匹配。所有路径用 `lstat` 拒绝 symlink，resolve 后必须仍在项目根内；parse manifest 的 `full_md`、`extracted_dir`、`markdown_copy`、`input_dir`、`output_dir` 全部不作为路径输入。

非 v2 content list 必须恰好一个；`layout.json`、canonical Markdown、reading/layout layer 必须存在。images digest 对排序后的 `{relative_path, sha256, size_bytes}` 计算，不把整张图片清单暴露到 bundle。先构建和 schema 校验完整 payload，再原子写 `01_evidence/source_truth/<study_id>/bundle.json`。

- [ ] **Step 5: 加入真实三篇只读兼容测试**

测试在目录存在时运行，否则 `pytest.skip`：断言 3 个 bundle、source id 唯一、页数 6/11/11、所有 artifact 路径相对、三份 bundle 均有 `duplicate_parse_drift`，且 Windows 来源目录没有任何 mtime 变化。

- [ ] **Step 6: 验证并提交 Source Truth 单元**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_source_truth.py
git add -- review_writer/project/source_truth.py schemas/evidence/source_truth_bundle.v1.schema.json tests/test_source_truth.py
git diff --cached --check
git commit -m "feat: add per-study source truth bundles"
```

Expected: PASS；提交不含真实 artifact。

---

### Task 3: 实现对象级 Parse Quality Gate

**Files:**

- Create: `schemas/evidence/parse_quality_gate.v1.schema.json`
- Create: `review_writer/project/parse_quality.py`
- Create: `tests/test_parse_quality.py`

- [ ] **Step 1: 写失败测试锁定对象粒度和双投影**

```python
@pytest.mark.parametrize(
    ("action", "workflow", "automatic"),
    (
        ("approve_candidate_extraction", True, True),
        ("pdf_locator_only", True, False),
        ("reparse_required", False, False),
    ),
)
def test_review_action_has_separate_workflow_and_extraction_projection(
    parse_project: ParseProject,
    action: str,
    workflow: bool,
    automatic: bool,
) -> None:
    gate = write_parse_quality_gate(parse_project.path, "scholarly-a")
    target = next(row for row in gate["objects"] if row["status"] == "usable_with_review")
    updated = apply_parse_quality_decision(parse_project.path, "scholarly-a", {
        "object_id": target["object_id"],
        "gate_digest": gate["gate_digest"],
        "action": action,
        "note": "Compared with the original PDF page.",
    })
    assert updated["workflow_can_continue"] is workflow
    assert updated["automatic_extraction_allowed"] is automatic


def test_gate_contains_all_required_object_kinds(parse_project: ParseProject) -> None:
    gate = write_parse_quality_gate(parse_project.path, "scholarly-a")
    assert {row["kind"] for row in gate["objects"]} == set(PARSE_OBJECT_KINDS)


def test_incomplete_object_cannot_be_approved_for_automatic_extraction(
    parse_project: ParseProject,
) -> None:
    gate = write_parse_quality_gate(parse_project.path, "scholarly-a")
    target = next(row for row in gate["objects"] if row["status"] == "incomplete")
    with pytest.raises(ParseQualityError, match="ACTION_NOT_ALLOWED"):
        apply_parse_quality_decision(parse_project.path, "scholarly-a", {
            "object_id": target["object_id"],
            "gate_digest": gate["gate_digest"],
            "action": "approve_candidate_extraction",
            "note": "Not valid for incomplete content.",
        })


def test_bundle_change_makes_decisions_stale(parse_project: ParseProject) -> None:
    gate = approve_all_review_objects(parse_project)
    parse_project.change_canonical_markdown()
    write_source_truth_bundle(parse_project.path, "scholarly-a")
    state = parse_quality_state(parse_project.path, "scholarly-a")
    assert state["status"] == "stale"
    assert state["workflow_can_continue"] is False
    assert state["automatic_extraction_allowed"] is False
```

- [ ] **Step 2: 运行失败测试**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_parse_quality.py
```

Expected: collection FAIL，模块和 schema 尚不存在。

- [ ] **Step 3: 定义 gate 合同与公开接口**

每个对象固定包含：

```python
{
    "object_id": str,       # canonical_digest({study_id, source_id, kind})[:24]
    "source_id": str,
    "kind": str,
    "status": str,
    "issues": [{"code": str, "severity": str, "message": str, "page": int | None}],
    "decision": None | {
        "action": str,
        "note": str,
        "decided_at": str,
        "bound_gate_digest": str,
    },
}
```

顶层固定包含 `schema_version`、`study_id`、`bundle_digest`、`objects`、`gate_digest`、`status`、`workflow_can_continue`、`automatic_extraction_allowed`。人工 note 去除首尾空白后必须为 1–2000 字符；时间使用 UTC ISO 8601。`gate_digest` 只覆盖自动 assessment 和 bundle digest，不覆盖决定，避免每次 PUT 令同 gate 的其他决定 stale。

公开接口及返回合同固定为：

- `build_parse_quality_gate(project: Path, bundle: dict[str, object]) -> dict[str, object]`：只读生成七类对象和自动 assessment，不复用旧决定。
- `write_parse_quality_gate(project: Path, study_id: str) -> dict[str, object]`：加载当前 bundle、构建 assessment、只保留仍绑定当前 gate 的决定，再原子写 `parse_quality.json`。
- `apply_parse_quality_decision(project: Path, study_id: str, payload: object) -> dict[str, object]`：严格校验 payload 和 action/object 状态组合，单文件原子 upsert 后返回完整 gate state。
- `parse_quality_state(project: Path, study_id: str) -> dict[str, object]`：重验 schema、bundle digest、gate digest 和决定绑定，返回 fail-closed 投影。
- `project_parse_quality_state(project: Path) -> dict[str, object]`：按 receipt 的研究集合汇总，缺任一 study artifact 即 `needs_review` 或 `needs_attention`。
- `require_parse_quality_ready(project: Path, study_id: str) -> str`：只有自动抽取获准时返回当前 gate digest，否则抛稳定 reason code。

`ParseQualityError(ValueError)` 与 `SourceTruthError` 使用相同的稳定 `.code` 约定，不包含路径和底层异常文本。

`require_parse_quality_ready` 只返回当前 `gate_digest`；缺失、stale、未决定、`reparse_required` 或 `pdf_locator_only` 均抛出稳定 reason code。只有 `automatic_extraction_allowed=True` 才返回。

- [ ] **Step 4: 实现七类确定性检查**

首轮检查规则固定：

- `body_order`：canonical Markdown 非空、content list 是 list、`page_idx` 非负且不能逆序跨页；异常为 `incomplete` 或 `usable_with_review`。
- `section_boundaries`：识别 Markdown headings；零 heading 为 `usable_with_review`，明显仓储 front matter 为 `usable_with_review`。
- `figure_caption_links`：content list 中 image/table 与 caption 的页码和引用资产存在；缺资产为 `incomplete`，邻接不稳定为 `usable_with_review`。
- `table_structure`：存在 table block 时一律 `usable_with_review`；结构 JSON 无效为 `incomplete`；无 table 为 `usable`。
- `formula_chemistry`：存在 inline/display equation、异常 Unicode replacement 或化学上下标模式时一律 `usable_with_review`；解析失败为 `incomplete`。
- `reference_boundary`：需要找到 references 起点且其后不能重新出现正文 heading；未找到为 `usable_with_review`。
- `supplement_completeness`：按 `source_coverage.json`；`NOT_REQUIRED` 为 `usable`，声明需要但缺失为 `failed`。

自动检查只能描述结构，不得出现“科学正确”“机制成立”或 LLM 结论。对 `usable` 不制造人工决定；重建 gate 时仅保留 `bound_gate_digest` 与新 gate 相同且 object id 仍存在的决定。

- [ ] **Step 5: 验证并提交 Parse Quality 单元**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_source_truth.py tests/test_parse_quality.py
git add -- review_writer/project/parse_quality.py schemas/evidence/parse_quality_gate.v1.schema.json tests/test_parse_quality.py
git diff --cached --check
git commit -m "feat: add object-level parse quality gate"
```

Expected: PASS。

---

### Task 4: 接入 CLI、prepare-study 与 sealed job 失效

**Files:**

- Modify: `scripts/run_vertical_review.py`
- Modify: `tests/test_vertical_review_projection.py`

- [ ] **Step 1: 写 CLI 和 fail-closed 测试**

```python
def test_build_source_truth_writes_one_gate_per_study(tmp_path: Path) -> None:
    project = three_study_source_truth_project(tmp_path)
    result = run_cli("build-source-truth", "--project", str(project))
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "command": "build-source-truth",
        "project_id": project.name,
        "study_count": 3,
        "needs_review": 3,
        "status": "NEEDS_REVIEW",
    }


def test_prepare_study_requires_automatic_extraction_permission(tmp_path: Path) -> None:
    project = canonical_prepare_project(tmp_path)
    build_and_choose_pdf_locator_only(project)
    status = prepare_status(project, STUDY_ID)
    assert status["status"] == "NOT_READY"
    assert status["reason_code"] == "PARSE_PDF_LOCATOR_ONLY"
    assert not (project / f"01_evidence/{STUDY_ID}/sealed_job.json").exists()


def test_gate_digest_changes_sealed_job_id(tmp_path: Path) -> None:
    project = canonical_prepare_project(tmp_path)
    first = approve_parse_gate_and_prepare(project)
    change_parse_input_and_reapprove(project)
    remove_prepare_output_fixture_only(project)
    second = prepare_status(project, STUDY_ID)
    assert first["job_id"] != second["job_id"]
```

测试清理只删除 tmp fixture 中由测试创建的 packet，不运行仓库破坏性命令。

- [ ] **Step 2: 运行目标测试并确认失败**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_vertical_review_projection.py -k 'source_truth or parse_quality or gate_digest'
```

Expected: FAIL，新命令和 gate 接线不存在。

- [ ] **Step 3: 添加两个短时幂等 CLI 命令**

```text
build-source-truth --project <path> [--study-id <id>]
record-parse-quality --project <path> --study-id <id> \
  --object-id <id> --gate-digest <digest> --action <action> --note <text>
```

stdout 只输出 project/study 数量、研究者状态和 reason code；不输出路径、hash、token、完整异常或 MinerU/provider 配置。构建时先在内存完成全部 bundle/gate/schema 校验，再逐 study 原子替换；任一 validation error 时不替换任何既有 study artifact。

- [ ] **Step 4: 将 gate 接到 prepare-study**

在 `_verify_source_identity()` 后调用 `require_parse_quality_ready(project, study_id)`，获得 `gate_digest`。随后 `_bind_source_layers()` 改为只消费已校验 bundle 的 reading/layout descriptor，不再独立解释 MinerU manifest。把 digest 放入现有 contract：

```python
semantic_target_contract = {
    "allowed_target_kinds": ["ELIGIBILITY", "REACTION_UNIT", "CLAIM"],
    "denied_claim_ids": coverage["blocked_claim_ids"],
    "parse_quality_gate_digest": gate_digest,
    "policy": "ALLOW_EXCEPT_DECLARED_SI_DEPENDENT_CLAIMS",
}
```

`canonical_sealed_job_id()` 已绑定整个 contract，无需改其字段投影。缺 gate、stale、未决定、reparse 和 PDF locator 分别返回稳定 `PARSE_*` reason code。

- [ ] **Step 5: 验证并提交 CLI 接线**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_source_truth.py tests/test_parse_quality.py tests/test_vertical_review_projection.py
git add -- scripts/run_vertical_review.py tests/test_vertical_review_projection.py
git diff --cached --check
git commit -m "feat: enforce parse gate before evidence preparation"
```

Expected: PASS。

---

### Task 5: 实现 researcher-safe Dashboard API 与持久状态投影

**Files:**

- Modify: `view/serve_review_dashboard.py`
- Modify: `tests/test_qoderwork_native_review_writer.py`

- [ ] **Step 1: 写 GET/PUT、资产和 progress 失败测试**

```python
def test_parse_quality_payload_is_safe_and_object_level(self) -> None:
    payload = dashboard.project_parse_quality_payload(review_root, "parse-review")
    assert set(payload) == {
        "project_id", "status", "workflow_can_continue", "summary", "studies"
    }
    obj = payload["studies"][0]["objects"][0]
    assert set(obj) == {
        "object_id", "kind", "label", "automatic_status", "issues",
        "decision", "actions", "note_required", "decision_token",
    }
    visible = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("sha256", "schema_version", "gate_digest", ".json", "/home/", "C:\\\\", "Agent", "Prompt"):
        assert forbidden not in visible


def test_parse_quality_put_rejects_stale_token_without_writing(self) -> None:
    before = project_file_bytes(project)
    status, payload = put_parse_decision(decision_token="stale")
    assert status == 409
    assert payload == {"error": "解析内容已更新，请重新核对"}
    assert project_file_bytes(project) == before


def test_bound_assets_cannot_escape_bundle(self) -> None:
    assert get_source_asset("parsed-markdown", source_id="stud-a").status == 200
    assert get_source_asset("../../00_sources", source_id="stud-a").status == 404


def test_progress_uses_parse_gate_and_never_falls_back_to_brief(self) -> None:
    assert progress_for_missing_gate()["active_stage"] == "parsing"
    assert progress_for_unknown_gate()["status"] == "needs_attention"
```

- [ ] **Step 2: 运行目标测试并确认失败**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_qoderwork_native_review_writer.py -k 'parse_quality or bound_assets or progress_uses_parse_gate'
```

Expected: FAIL，API 与投影不存在。

- [ ] **Step 3: 实现安全 API**

固定路由：

```text
GET /api/project/<project_id>/parse-quality
PUT /api/project/<project_id>/parse-quality
GET /api/project/<project_id>/source/<source_id>/pdf
GET /api/project/<project_id>/source/<source_id>/parsed-markdown
```

公开 `decision_token` 为 `sha256(project_id + "\0" + study_id + "\0" + object_id + "\0" + gate_digest)`；它只防 stale，不是身份验证秘密。PUT 只接收 `study_id`、`object_id`、`decision_token`、`action`、`note`，服务端解析当前隐藏 digest 后调用 domain API。输入错误 400，stale/缺 artifact 409，未知项目/来源 404；响应不得包含原始异常文本。

PDF 和 Markdown route 只能调用 `source_truth_asset()` 返回当前 bundle 已绑定文件；设置正确 content type、`X-Content-Type-Options: nosniff` 和下载/inline disposition，不接受 path 参数。

- [ ] **Step 4: 替换 progress 真源**

`project_progress_payload()` 用 `project_parse_quality_state(project)` 投影解析子流程：无 gate、stale、未决定或 reparse 显示 `parsing`；全部异常对象已关闭后才可显示下游已有阶段。`pdf_locator_only` 不伪装成自动抽取许可，推荐动作明确为“从原始 PDF 人工定位证据”。未知/损坏状态显示 `needs_attention` 和真实原因，禁止回落到“确认研究范围”。

- [ ] **Step 5: 验证 restart persistence 并提交**

测试必须重新导入 dashboard module 并对同一临时项目 GET，确认决定来自磁盘而非内存。

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_qoderwork_native_review_writer.py -k 'parse_quality or source_asset or progress or restart'
git add -- view/serve_review_dashboard.py tests/test_qoderwork_native_review_writer.py
git diff --cached --check
git commit -m "feat: expose persistent parse quality review"
```

Expected: PASS。

---

### Task 6: 实现对象级 Parse Quality 工作区与三视口布局

**Files:**

- Modify: `view/assets/dashboard/review.html`
- Modify: `view/assets/dashboard/review-ui.css`
- Modify: `tests/test_qoderwork_native_review_writer.py`

- [ ] **Step 1: 写静态 UI 接线失败测试**

```python
def test_parse_quality_workspace_has_object_controls_and_safe_copy(self) -> None:
    html = (ROOT / "view/assets/dashboard/review.html").read_text(encoding="utf-8")
    assert 'id="parse-quality-stage-panel"' in html
    assert 'id="parse-quality-study-list"' in html
    assert "renderParseQualityStage" in html
    assert "允许机器从该部分提取候选证据" in html
    assert "仅回到原始 PDF 人工定位" in html
    assert "必须重新解析" in html
    for forbidden in ("Source Truth Bundle", "schema", "digest", "hash", "JSON"):
        assert forbidden not in VisibleTextParser.visible_text(html)
```

- [ ] **Step 2: 运行失败测试**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_qoderwork_native_review_writer.py -k 'parse_quality_workspace'
```

Expected: FAIL，工作区尚不存在。

- [ ] **Step 3: 添加工作区结构和交互**

解析面板位于 Source Set 内部、Evidence 前，不新增第六个全局阶段。每项研究显示 citation、PDF 与解析文本两个预览按钮、七类对象状态、具体问题/page locator、互斥动作、必填理由和单对象保存。所有动态内容用 `textContent`；按钮使用现有 icon library，陌生图标有 tooltip。

固定前端状态与错误行为：

```javascript
let parseQualityPayload = {
  status: 'unavailable',
  workflow_can_continue: false,
  summary: {},
  studies: [],
};
let parseQualityBusy = new Set();
```

`loadProject()` 与 progress 并行 GET；`renderStageWorkspace()` 在 active stage 为 parsing 或 gate 需要注意时显示。PUT 成功后以响应替换 payload 并重载 progress；409 显示“解析内容已更新，请重新核对”并重新 GET，绝不静默重试旧决定。保存中只禁用当前对象，稳定尺寸避免布局跳动。

- [ ] **Step 4: 添加工程化响应式布局**

桌面使用左侧论文/对象列表与右侧预览区；1024 宽保持双列但缩小预览；390 宽改为单列，预览在新标签打开，动作纵向排列。卡片圆角不超过 8px，沿用现有颜色 token，不新增单色主题或装饰背景；radio/checkbox 用原生语义控件，按钮文本不溢出。

必须为以下稳定尺寸写 CSS：对象状态 badge、动作控件、保存按钮、preview toolbar。三视口均不得出现横向滚动、重叠或因动态文案改变高度导致工具栏跳动。

- [ ] **Step 5: 验证并提交前端切片**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_qoderwork_native_review_writer.py -k 'parse_quality or progress'
git add -- view/assets/dashboard/review.html view/assets/dashboard/review-ui.css tests/test_qoderwork_native_review_writer.py
git diff --cached --check
git commit -m "feat: add object-level parse review workspace"
```

Expected: PASS。

---

### Task 7: 用三篇 WSL 案例运行完整人工循环并独立黑盒验收

**Files:**

- Create: `docs/qa/vis-light-parse-quality-playwright.md`
- External modify: WSL 副本下 `01_evidence/source_truth/`

- [ ] **Step 1: 写独立 Agent 黑盒合同**

合同必须限定：Agent 只拿 URL、化学研究者 persona 和操作步骤；只用 Playwright MCP 的 navigate、snapshot/find、click、fill/type、resize、screenshot、console_messages、network_requests、wait_for、close；不得读仓库、shell、内部 JSON、cookie/localStorage/sessionStorage，不得修改项目文件，不得使用 `browser_run_code_unsafe`。报告字段固定为 ID、viewport、action、expected、observed、severity、category、screenshot、blocks release。

测试序列固定为：理解当前阶段 → 比较 PDF/parsed preview → 逐对象决定 → 刷新 → 主 Agent 重启 dashboard → 再刷新 → 1440×1000、1024×900、390×844 → accessibility/focus → console/network。Pass rule：零 P0/P1、console 零 error/warning、无横向滚动、决定恢复、普通用户看不到 path/hash/schema/JSON/Agent/Prompt。

- [ ] **Step 2: 在 WSL 副本构建三项研究 artifact**

```zsh
case_root=/home/kenqia/my_folder/review-writer-data/review-projects/vis-light-olefin-difunctionalization-wsl-v1
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_vertical_review.py \
  build-source-truth --project "$case_root"
```

Expected: `study_count=3`、`status=NEEDS_REVIEW`；不重新调用 MinerU、模型或网络。

- [ ] **Step 3: 运行确定性回归和项目门禁**

```zsh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -s -q -p no:cacheprovider \
  tests/test_source_truth.py \
  tests/test_parse_quality.py \
  tests/test_vertical_review_projection.py \
  tests/test_qoderwork_native_review_writer.py \
  tests/test_project_release.py
make smoke
make quality-check
```

Expected: 全部 PASS。

- [ ] **Step 4: 启动 dashboard 并分发全新独立 Agent**

```zsh
python3 view/serve_review_dashboard.py \
  --review-root /home/kenqia/my_folder/review-writer-data \
  --host 127.0.0.1 \
  --port 52738
```

创建一个未参与实现的新 Agent，只给 `http://127.0.0.1:52738/review` 和 QA 合同。它只模拟人工操作并报告，不修代码、不代表肯恰大人的科学验收。

- [ ] **Step 5: 主 Agent 审查、精确重启并回归**

主 Agent 复核截图、console、network、磁盘/API/progress 一致性。只向自己启动的 session 发送 Ctrl+C，不使用 `pkill`；重启同一命令后验证决定保持。P0/P1 与影响科研判断的 P2 采用失败测试 → 最小修复 → 局部测试 → 新 commit；修复后由第二个全新 Agent 回归，不能让原 Agent 自我确认。

- [ ] **Step 6: 提交 QA 合同**

```zsh
git add -- docs/qa/vis-light-parse-quality-playwright.md
git diff --cached --check
git commit -m "docs: add visible-light parse review protocol"
```

---

### Task 8: 最终验证与肯恰大人人工验收门

**Files:**

- Review: all commits since `a6d67db`
- No implementation expansion

- [ ] **Step 1: 运行新鲜验证**

```zsh
git diff --check a6d67db..HEAD
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -s -q -p no:cacheprovider \
  tests/test_source_truth.py \
  tests/test_parse_quality.py \
  tests/test_vertical_review_projection.py \
  tests/test_qoderwork_native_review_writer.py \
  tests/test_project_release.py \
  tests/test_reusable_library.py \
  tests/test_review_batch_runner.py
make smoke
make quality-check
```

Expected: 全部 PASS。

- [ ] **Step 2: 提交级和数据边界审查**

```zsh
git log --oneline --decorate a6d67db..HEAD
git diff --stat a6d67db..HEAD
git status --short --branch
```

确认无真实 PDF/Markdown/图片/项目 artifact、无 token/env、无自动科学批准、无 Windows 绝对路径依赖、无 watcher、无自动图路径；确认 `pdf_locator_only` 不创建 provider packet，gate 变化令旧 sealed job 失效。

- [ ] **Step 3: 交付人工验收入口**

向肯恰大人报告 WSL URL、三篇来源的对象级问题和人工处置、两轮独立 Agent findings、三视口截图、测试/console/network/restart 结果，以及本轮未实现的 Typed Evidence、Synthesis 和 Figure Placeholder。只有肯恰大人亲自检查并明确批准后，才为下一切片编写独立计划。
