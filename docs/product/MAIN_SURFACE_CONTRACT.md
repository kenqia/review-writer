# Main 用户面边界合同

状态：`CURRENT_CANDIDATE_BOUNDARY`
版本：`main-surface-contract.v0.1`

这份合同只解决一个产品问题：用户打开当前候选时，能否清楚知道真正应该运行
什么，以及哪些对象只是开发者轨迹或历史恢复资产。它不删除、移动或覆盖任何
代码、worktree、项目、PDF、SI 或运行时。

## 结论

当前用户入口只有四个命令，顺序也是用户实际运行顺序：

```text
bootstrap-corpus
  -> bind-generic-parse
  -> preflight-corpus-inputs
  -> import-corpus-inputs
```

它们都通过 `scripts/run_vertical_review.py` 执行。`README.md`、`docs/用户使用说明.md`
和 `docs/项目规格.md` 是用户理解和恢复这条路径的必要说明；输入 schema 和当前
CLI 的运行时闭包必须随主面保留。

### 用户变化

无新的运行时命令或科学能力；用户得到的是一个可验证的“应该从哪里开始”的边界。
主面只承诺 20–40 篇 MAIN/SI 语料输入基础线，不把旧三篇入口、309 分母、Dashboard、
Phase 8、Provider、RAG、QoderWork 或旧 release 波次展示成当前产品流程。

### 使用方式

在候选工作树中运行：

```bash
python scripts/validators/validate_main_surface.py --mode candidate
```

这会核对当前候选的主入口、用户文档、输入 schema、实际 import 运行时闭包，以及
开发/历史资产清单是否仍存在。它不会读取外部论文、SI、项目输出或认证信息。

当未来准备一个真正只含用户产品的 `main` 工作树时，从保留本合同和脚本的
`core-development` 工作树指向它运行：

```bash
python scripts/validators/validate_main_surface.py --root /path/to/main --mode main
```

`--mode main` 会在缺少任一主面必需路径、仍暴露非公开命令，或把开发/历史目录带入
主面时 fail-closed。

## 边界清单

### 必须留在 main 的用户入口

- 用户说明、项目规格和 README：告诉用户准备什么、运行什么、如何恢复，以及当前
  不承诺什么。
- `scripts/run_vertical_review.py`：唯一当前 CLI 入口。
- `bootstrap-corpus`、`bind-generic-parse`、`preflight-corpus-inputs`、
  `import-corpus-inputs`：当前公共命令集合。
- `requirements.txt`、当前输入 schema，以及 CLI 实际 import 的 `review_writer/`、
  `scripts/evidence/`、`scripts/review/` 和对应 schema 目录：它们是当前代码能启动并
  完成输入绑定的运行时闭包，不等于都应该出现在用户说明里。

### 应留在 core-development 的开发轨迹

代理编排、测试、评测、CI、验证器、QoderWork/skill source、内部 handoff、ops、QA、
superpowers、provider 配置和维护脚本属于开发面。它们可以继续被开发者使用，但不得
成为用户主流程或当前科学结果的证据。

### 应留在 core-development 的历史资产

`demo_projects/`、`view/`、`rag/`、Phase 8 schema/script/template、Provider/RAG/旧
QoderWork 文档、旧 demo/eval/migration/release 资料和旧 allene 规则只作为回归或恢复
证据保留。保留不等于 current、READY、科学确认，也不授权物理清理。

当前 CLI 的 `review_writer/` 仍是一个较宽的 import 闭包，其中可能包含尚未拆出的
历史模块；本合同把它视为运行时依赖而不是用户入口。若要把其中的历史子模块真正
移出 main，必须先做独立的 import 解耦和新鲜验证，本任务不扩大到那里。

## 验证准则与停止线

`candidate` 模式必须证明清单与当前候选相符；`main` 模式必须证明主面没有开发/历史
目录，也没有非公开 CLI 命令。任何缺失、错类、文档未说明或帮助输出泄露都报告为
失败，不能降级为 warning。该检查只约束仓库内路径和 CLI 帮助，不证明真实语料、
MinerU/Chemical 输入、研究者确认、综述质量或 DOCX/PDF 发布。

任务准入记录：

```text
BASELINE=b5c14960a4955121b8c2b7ae237fe1d0fd297028
TARGET=可执行的 main 用户面与 core-development 开发面边界
AFFECTED_DELIVERABLE=当前候选的用户入口与可追溯开发边界
GOLD_DELTA=DIRECT
TRACE_DELTA=DIRECT
DIRECT_TARGET=四个当前用户命令、运行时闭包和非公开资产边界
MEASUREMENT_OR_ARTIFACT=本清单、validator JSON 报告、聚焦测试与 git diff --check
STOP_LINE=只修改本合同、独立检查脚本及其测试；不删除、移动、覆盖或远端写入
```

## 机器可读清单

下面的 JSON 是本合同唯一的可执行清单来源。路径均相对于仓库根目录；`kind` 为
`file` 或 `dir`。`main_runtime_closure` 是当前 CLI 的技术依赖，不代表公开用户 API。

```json
{
  "contract_id": "main-surface-contract.v0.1",
  "admission": {
    "GOLD_DELTA": "DIRECT",
    "TRACE_DELTA": "DIRECT"
  },
  "main_commands": [
    "bootstrap-corpus",
    "bind-generic-parse",
    "preflight-corpus-inputs",
    "import-corpus-inputs"
  ],
  "main_user_surface": [
    {"path": "README.md", "kind": "file"},
    {"path": "docs/用户使用说明.md", "kind": "file"},
    {"path": "docs/项目规格.md", "kind": "file"},
    {"path": "requirements.txt", "kind": "file"},
    {"path": "scripts/run_vertical_review.py", "kind": "file"},
    {"path": "schemas/project/corpus_manifest.v1.schema.json", "kind": "file"},
    {"path": "schemas/project/input_provenance_manifest.v1.schema.json", "kind": "file"}
  ],
  "main_documentation": [
    "README.md",
    "docs/用户使用说明.md",
    "docs/项目规格.md"
  ],
  "main_runtime_closure": [
    {"path": "review_writer", "kind": "dir"},
    {"path": "scripts/evidence", "kind": "dir"},
    {"path": "scripts/review", "kind": "dir"},
    {"path": "schemas/agents", "kind": "dir"},
    {"path": "schemas/delivery", "kind": "dir"},
    {"path": "schemas/evidence", "kind": "dir"},
    {"path": "schemas/figures", "kind": "dir"},
    {"path": "schemas/operations", "kind": "dir"},
    {"path": "schemas/project", "kind": "dir"},
    {"path": "schemas/quality", "kind": "dir"},
    {"path": "schemas/synthesis", "kind": "dir"}
  ],
  "core_development_paths": [
    {"path": ".agents", "kind": "dir"},
    {"path": ".codex", "kind": "dir"},
    {"path": ".github", "kind": "dir"},
    {"path": "config", "kind": "dir"},
    {"path": "docs/agent-contracts", "kind": "dir"},
    {"path": "docs/agent-memory.md", "kind": "file"},
    {"path": "docs/agent-orchestration", "kind": "dir"},
    {"path": "docs/agent-roles", "kind": "dir"},
    {"path": "docs/agent-tasks", "kind": "dir"},
    {"path": "docs/audit", "kind": "dir"},
    {"path": "docs/CONVERGENCE_2026-08-03.md", "kind": "file"},
    {"path": "docs/CONVERGENCE_INVENTORY_2026-08-03.md", "kind": "file"},
    {"path": "docs/decisions", "kind": "dir"},
    {"path": "docs/handoff", "kind": "dir"},
    {"path": "docs/local", "kind": "dir"},
    {"path": "docs/ops", "kind": "dir"},
    {"path": "docs/portability", "kind": "dir"},
    {"path": "docs/pr", "kind": "dir"},
    {"path": "docs/product/MAIN_SURFACE_CONTRACT.md", "kind": "file"},
    {"path": "docs/qa", "kind": "dir"},
    {"path": "docs/quality", "kind": "dir"},
    {"path": "docs/superpowers", "kind": "dir"},
    {"path": "evals", "kind": "dir"},
    {"path": "Makefile", "kind": "file"},
    {"path": "qoderwork", "kind": "dir"},
    {"path": "requirements-ci.txt", "kind": "file"},
    {"path": "scripts/acquisition", "kind": "dir"},
    {"path": "scripts/agent-orchestration", "kind": "dir"},
    {"path": "scripts/discovery", "kind": "dir"},
    {"path": "scripts/delivery", "kind": "dir"},
    {"path": "scripts/llm_judges", "kind": "dir"},
    {"path": "scripts/validators", "kind": "dir"},
    {"path": "skills", "kind": "dir"},
    {"path": "tests", "kind": "dir"}
  ],
  "historical_asset_paths": [
    {"path": "allene_classification_rules.py", "kind": "file"},
    {"path": "demo_projects", "kind": "dir"},
    {"path": "docs/competition", "kind": "dir"},
    {"path": "docs/demo", "kind": "dir"},
    {"path": "docs/eval", "kind": "dir"},
    {"path": "docs/migration", "kind": "dir"},
    {"path": "docs/phase8", "kind": "dir"},
    {"path": "docs/pipeline", "kind": "dir"},
    {"path": "docs/providers", "kind": "dir"},
    {"path": "docs/qoderwork", "kind": "dir"},
    {"path": "docs/rag", "kind": "dir"},
    {"path": "rag", "kind": "dir"},
    {"path": "requirements-phase8.txt", "kind": "file"},
    {"path": "requirements-qwen.txt", "kind": "file"},
    {"path": "schemas/phase8_ai_adjudication", "kind": "dir"},
    {"path": "schemas/phase8_source_first_v3", "kind": "dir"},
    {"path": "schemas/phase8_source_first_v3_1", "kind": "dir"},
    {"path": "schemas/phase8_source_first_v3_1_1_layer_b", "kind": "dir"},
    {"path": "scripts/phase8", "kind": "dir"},
    {"path": "scripts/provider-qualification", "kind": "dir"},
    {"path": "scripts/rag", "kind": "dir"},
    {"path": "template", "kind": "dir"},
    {"path": "templates", "kind": "dir"},
    {"path": "view", "kind": "dir"}
  ],
  "non_public_runtime_paths": [
    {"path": "review_writer/phase8", "kind": "dir"}
  ],
  "non_public_commands": [
    "bootstrap-dual-parse",
    "build-dual-source",
    "dual-source-state",
    "build-parse-reconciliation",
    "parse-reconciliation-state",
    "record-parse-reconciliation",
    "preflight",
    "init",
    "wait-state",
    "audit-reusable-library",
    "build-source-truth",
    "record-parse-quality",
    "register-paper-evidence",
    "register-manual-pdf-evidence",
    "record-paper-evidence",
    "prepare-study",
    "prepare-batch",
    "run-batch",
    "record-credits",
    "register-study",
    "build-risk-packet",
    "build-writer-packet",
    "bind-draft",
    "metrics",
    "import-chemical-paper",
    "chemical-paper-state",
    "chemical-completion-state",
    "complete-chemical-fields",
    "correct-chemical-paper-field",
    "review-chemical-paper-elements"
  ]
}
```

## 限制/风险与后续整合

- 当前候选的 CLI help 仍会列出若干兼容/开发命令，所以 `--mode main` 预期会失败；
  这不是本任务直接修改入口实现的授权。
- `review_writer/` 作为当前 import 闭包仍比用户功能宽，不能仅凭目录名把其中模块
  删除或移动。后续应由独立 Owner 做 import 解耦，重新验证四个命令和零写入失败路径。
- 本合同不证明真实 20–40 篇输入、Generic/MinerU、Chemical、科学确认、Dashboard、
  综合矩阵、Gold calibration 或 DOCX/PDF release。
- 整合建议：先在新的 main 候选上运行 `--mode main`，只接受报告为 `PASS` 的边界；
  若仍有 `MAIN_HELP_EXPOSES_NON_PUBLIC_COMMAND` 或运行时闭包缺失，退回入口/运行时
  Owner 修复，不通过物理删除历史目录来“消除”检查。
