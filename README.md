# Review Writer

Review Writer 是面向化学研究者的本地优先、证据可追溯综述工作台。研究者在 Codex
中说明主题、明确项目目录和获授权的本地 PDF folder；Agent 负责调用本地工具，研究者
只在 Dashboard 中阅读、判断、编辑、批准和导出。

## 研究者入口

### 前置条件

- 已安装本仓库所需的 Python 3 依赖和项目本地 `review-orchestrator` Skill。
- 有一个明确的综述项目目录，以及仅允许本次综述读取的本地 PDF folder。新项目应使用
  空目录；恢复项目必须使用其原有目录。
- Dashboard 只监听 `127.0.0.1`，不要求账号、云端数据库或上传文件。

在 Codex 中使用下面的自然语言入口。用户通过 `$review-orchestrator` 的隐式本地能力与
Agent 对话，不需要输入 Skill 名称或任何终端命令。不要手工运行内部 CLI、cURL、pytest、
`generator-start` 或 `generator-continue`；它们由 Agent 在同一个项目 authority 内调用。

> 请使用 Review Writer 为《<topic>》创建或恢复综述项目。项目目录为
> `<explicit project root>`，允许读取 PDF 文件夹 `<authorized PDF folder>`。需要我作出
> MAIN/SI 身份或 Evidence 判断时，请打开 Dashboard 并暂停。

Agent 创建或恢复项目后，负责启动或复用其拥有的本地 Dashboard，并返回可点击的
`http://127.0.0.1:<port>/review?project_id=<project ID>` URL。研究者只打开这个 URL；旧
`?project=<project ID>` 仍兼容，首屏会规范化为 `project_id`，并保留该项目的
current/version 上下文。冷恢复时回到 Codex 说“从 `<explicit project root>` 继续”，由 Agent
读取同一 authority、复用或重启其拥有的 Dashboard，再返回新的可点击 URL。

## 四层产品包

1. **本地安装与运行层**：Review Writer 安装目录、项目本地 `review-orchestrator` Skill、
   本地 Python/kernel/CLI、Dashboard server/assets 与 `setup`/`doctor`。这一层只提供
   能力，不保存某篇综述的 current。
2. **Generator Agent/session 层**：可见的 Generator Agent、`GeneratorSession` 和既有
   local tools/helpers 调用生产者并在人工 gate 暂停/恢复；没有平行 workflow store。
3. **综述项目层**：每篇综述的项目目录及其 `.review-writer/version_context` 是 sources、
   Evidence、正文、图件、导出、current 和版本的唯一 durable authority。
4. **Dashboard 研究工作台层**：Dashboard 承担人类的阅读、判断、编辑、批准、发布与历史
   展示，不是第二事实源，也不替研究者批准科学结论。

Dashboard 使用五组顶级工作区：**首页**（紧凑 Overview）、**来源与证据**（Corpus、Evidence、
Matrix）、**正文**（写作大纲、Sections、Draft）、**图表**（attribution、许可、正文绑定）、
**发布与历史**（Quality、Release、Markdown、DOCX、History）。旧页面、URL 和 API 仍可访问，
但 legacy cockpit、原始 JSON 和诊断信息不构成默认工作区。

## 项目 Authority 与产物

项目目录是唯一长期事实源。不要另建 workspace、手工编辑 JSON，或把 Dashboard 的显示状态
当作 current。实际项目会按阶段出现下列路径：

```text
<project root>/
├── .review-writer/version_context/
│   ├── current.json                 # 唯一 current 指针：project/version/revision
│   ├── versions/<version ID>.json   # immutable version node 与 snapshot digest
│   └── branches/<branch ID>.json    # History/branch 的 current head
├── 00_brief/                        # 综述主题与状态
├── 00_discovery/                    # 已获授权来源的发现/获取记录（如适用）
├── 00_sources/                      # MAIN/SI 与来源身份
├── 01_evidence/                     # parse、locator、Evidence decision/projection
├── 02_synthesis/                    # Comparison Protocol、Synthesis、Section Contract
├── 03_figures/                      # attribution、许可上下文、正文绑定
├── 04_manuscript/                   # authoritative manuscript 与 section drafts
└── 05_release/
    ├── self_reviewed_draft.md       # Markdown release artifact
    ├── self_reviewed_draft.docx     # 同版本 DOCX release artifact
    ├── release_snapshot.json        # release binding/currentness
    └── quality_report.json          # Quality 结果
```

定位规则如下：

- `current.json` 的 `version_id`/`revision` 与对应 `versions/<version ID>.json` 的
  `snapshot_digest` 定义当前版本；project ID 与项目根目录由同一 authority 记录。
- Markdown、DOCX、`release_snapshot.json` 和 `quality_report.json` 位于 `05_release/`，且
  必须绑定同一个 current。正文变化后，旧 release 必须 stale，下载返回受保护的 stale/403
  结果；先在 Dashboard regenerate，不能复用旧文件冒充新版本。
- History、compare、branch 和 undo 通过 Dashboard 读取或生成 `version_context` 的 immutable
  node。查看历史或 compare 不移动 current；undo 建立新的版本节点而不是覆盖历史。
- resume 从同一项目根目录和 `version_context/current.json` 恢复。它不创建第二个 session
  store，且不得覆盖 `USER_EDITED` 或 `RESEARCHER_AUTHORED` 内容。

### 实测隔离样例

以下仅是 2026-08-20 新隔离 native Agent bootstrap 的 authority 读取结果，位于
`/tmp/review-writer-gating-fresh.R5t7uJ/fresh-native-gating-review`，不是 Stable 项目，也不
代表科学有效性或用户验收。该次 Agent 返回的 Dashboard URL 为
`http://127.0.0.1:47240/review?project_id=fresh-native-gating-review`：

| 字段 | 实测值 |
| --- | --- |
| project ID | `fresh-native-gating-review` |
| current/version | `agent-bootstrap-6b8da4ffb13e7f7f3d8cecbc` |
| revision | `1` |
| snapshot digest | `0b33e548e91349277d1f3ea31c2faecbd4febd81f01ac07e55695d91db4aa068` |
| Evidence digest | 未生成；当前停在 `SOURCE_ROLE_HUMAN_ACTION_REQUIRED` |
| release binding | 未生成；没有 Markdown/DOCX release artifact |

该实例的 project ID、root、current/version、revision、snapshot digest 和人工暂停点均从同一
项目 authority 读取；它只证明自然语言 fresh bootstrap 会返回可用 Dashboard URL，不证明
后续科学判断、release 或用户验收。

## 5-10 分钟人工检查

1. 在 Codex 发送上面的自然语言入口，等待 Agent 返回可点击 Dashboard URL。
2. 打开该 URL，确认项目与 current/version 上下文及唯一下一动作。
3. 在“来源与证据”核对 PDF、MAIN/SI 身份、locator 和 Evidence decision；无法确认时保留
   `AI_PROVISIONAL` 或 `BLOCKED`，不猜测。
4. 在“正文”编辑并批准一段内容，确认 `USER_EDITED` 标记和理由仍被保留。
5. 在“图表”核对来源署名、许可上下文和正文绑定；缺失时保持 GAP。
6. 在“发布与历史”查看 Quality/Release，下载同版本 Markdown/DOCX；再编辑正文，确认旧
   release stale 后通过 Dashboard regenerate。
7. 在 History 查看旧版、compare 或 branch/undo；确认仅查看不会移动 current。
8. 回到 Codex 说“从该项目根目录继续”，确认 Agent 从自己的 authority 恢复并返回 Dashboard URL。

顺序为：PDF -> 人工 MAIN/SI 与 Evidence 决定 -> 正文编辑/批准 -> Figure/Quality ->
Markdown/DOCX -> stale/regenerate -> History -> 停止/冷恢复。

## 质量边界

- **Engineering**：代码、focused regression、fail-closed/zero-write 与 Candidate 主链测试。
- **Independent Quality**：独立 fresh browser 三视口、DOM/console、旧 URL 与 release stale
  证据。
- **Product Use**：隔离项目中 Evidence 到 Draft、DOCX/Release、History、resume 的代表性路径。
- **PUBLIC_E2E**：普通研究者以自然语言、空 project root 和授权 PDF folder 做的独立重验。
- **HUMAN_ACCEPTANCE**：由肯恰大人作出，不由本地测试或 Agent 推断。当前为
  `FAIL/REVOKED`。
- **scientific validity**：不由产品自动建立。当前为 `HOLD`。
- **PROMOTE/B2**：不属于本次默认结果；在各项独立通过前保持不执行。

当前产品状态为 `NOT_READY`。本 README 是普通研究者的唯一事实入口；
[`docs/handoff/REVIEW_WRITER_HANDOFF.md`](docs/handoff/REVIEW_WRITER_HANDOFF.md) 只保留
兼容索引，不重复入口、样例或验收结论。内部维护和故障诊断命令不属于研究者验收路径。
