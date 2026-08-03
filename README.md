# review-writer

review-writer 是一个面向化学研究者的、本地优先、证据可追溯的综述工作台。
当前主入口先处理“输入是否可靠”这件事：让用户提交一组已经选好的论文后，系统
能清楚地说明哪些 MAIN、SI、Generic Parse 和 Chemical Parse 属于同一篇论文，
哪些输入仍需修复，以及任何结果为什么被阻断。

当前主入口是仓库中的 `scripts/run_vertical_review.py`。QoderWork 目录和旧技能仍
作为历史/备用兼容材料保留，但不是本版用户的启动入口。

## 现在用户能得到什么

当前主入口支持一个权威的 `20–40` 篇语料项目。令论文总数为 `N`，其中
`tier=core` 的核心论文数为 `K`：

- 每篇论文必须同时提交 MAIN 和 SI，系统会复制并记录它们的 SHA-256；
- Generic Parse 必须为 `2N` 份（每篇 MAIN 一份、SI 一份），不能用同名文件猜测归属；
- 每篇论文会生成包含 MAIN/SI 的 Source Truth 和 Parse Quality 绑定；
- 输入 provenance 会按实际 `N` 和 `K` 计算数量，不再固定三篇或 309；
- `preflight-corpus-inputs`/`import-corpus-inputs` 还会检查每篇论文的 Chemical ZIP；
  它是输入绑定，不是分子确认；
- 缺文件、错 hash、跨论文复用、过期或不完整输入会在发布前失败，并尽量保持零写入；
- Dashboard、Evidence、Synthesis、DOCX/PDF 只能消费 current 且有来源链的结果。

这是一条可验证的输入与证据基础线，不是已经完成科学综述的证明。当前仓库没有
真实 `20–40` 篇主题语料的完整科学运行、研究者确认或可宣称的 DOCX/PDF 发布结果。

## 用户最短流程

在仓库根目录执行。请求 JSON 和运行后的项目目录放在仓库内，真实论文、SI、Generic
输出和 Chemical ZIP 可以继续放在仓库之外。例如：

```text
review-writer/                           # 本仓库
├── inputs/visible-light-review.json     # bootstrap 请求
├── inputs/visible-light-inputs.json     # provenance manifest
└── projects/                            # 用户项目目录

/data/review-inputs/                     # 仓库外的原始输入
├── papers/study-001-main.pdf           # MAIN
├── papers/study-001-si.pdf             # SI
├── mineru/visible-light-review/        # 2N 个 Generic 输出
└── chemical/study-001.zip              # 每篇 study 的 Chemical ZIP
```

上面的 `/data` 只是示意，请替换成自己的本地路径。`bootstrap-corpus` 会创建
`projects/<project_id>/`，不要先手工复制旧项目到该目录。

### 1. 准备请求文件

准备一个 JSON 请求，包含主题和 `20–40` 条 `sources`。每条必须有唯一的
`study_id`、`source_id`、`doi`、`title`、`tier`，以及 MAIN/SI 文件路径和对应 hash：

```json
{
  "schema_version": "corpus-manifest.v1",
  "project_id": "visible-light-review",
  "brief": {
    "topic": "可见光驱动烯烃双官能化",
    "review_questions": ["问题 1", "问题 2", "问题 3", "问题 4", "问题 5"]
  },
  "sources": [
    {
      "study_id": "study-001",
      "source_id": "source-001",
      "doi": "10.example/one",
      "title": "论文标题",
      "tier": "core",
      "document_role": "MAIN",
      "pdf_input_path": "/data/papers/study-001-main.pdf",
      "expected_pdf_sha256": "<64 位小写 SHA-256>",
      "si_pdf_input_path": "/data/papers/study-001-si.pdf",
      "expected_si_pdf_sha256": "<64 位小写 SHA-256>"
    }
  ]
}
```

`tier=core` 的论文会进入核心论文分母 `K`；不能为了通过检查临时缩小核心清单。
hash 可以用 `sha256sum 文件路径` 计算。请求文件中的路径只用于读取和复制，系统
不会把原始绝对路径写进项目产物。

### 2. 创建全新项目

```bash
python scripts/run_vertical_review.py bootstrap-corpus \
  --review-root projects \
  --request inputs/visible-light-review.json
```

用户变化：得到一个全新的、只含输入边界和来源记录的项目；旧项目的 Evidence、
Synthesis、Manuscript 或 Release 状态不会被复制。项目中会出现
`00_brief/`、`00_sources/papers/`、`00_sources/supplements/imported/`、
`00_sources/acquisition_final_receipt.json` 和 `00_sources/source_coverage.json`。
如果项目 ID 已存在，命令会拒绝覆盖；请修正请求后换一个新的 `project_id`。

### 3. 绑定 Generic Parse

先对项目中 `00_sources/` 下的全部 MAIN/SI 运行你所使用的 Generic/MinerU 流程，输出
目录必须包含完整的 `manifest.json`、Markdown、extracted sidecar 和 raw ZIP。这个
仓库命令只负责校验并绑定已有输出，不负责替你调用解析器或上传 PDF。然后执行：

```bash
python scripts/run_vertical_review.py bind-generic-parse \
  --project projects/visible-light-review \
  --mineru-output /data/mineru/visible-light-review
```

用户变化：每个 study 会得到 MAIN 与 SI 两个不冲突的解析身份，并生成 Source Truth
和 Parse Quality。变量语料必须绑定 `2N` 个 Generic 文档；任何缺失、错绑、过期或
hash 不匹配都会失败。

### 4. 只读检查输入 provenance

另准备一个输入 manifest。每个 study 需要声明 MAIN 页数、SI 原始文件及 hash、Chemical
ZIP 及页数。详情见[用户使用说明](docs/用户使用说明.md)。先只读检查：

```bash
python scripts/run_vertical_review.py preflight-corpus-inputs \
  --project projects/visible-light-review \
  --manifest inputs/visible-light-inputs.json
```

用户变化：在写入正式 provenance 之前，先看到实际 `N`、`K`、MAIN/SI/Generic/Chemical
的绑定数量和具体阻断原因。确认输出为 `status=ready_for_import` 后，才进入下一步。

### 5. 发布输入 provenance

```bash
python scripts/run_vertical_review.py import-corpus-inputs \
  --project projects/visible-light-review \
  --manifest inputs/visible-light-inputs.json \
  --actor-type human_researcher \
  --actor-label "my-researcher-label"
```

将 `my-researcher-label` 换成能识别本次操作的标签。这里的“发布”只表示输入绑定和
currentness 已记录，不表示 Chemical 分子已被研究者确认，也不把 `AI_PROVISIONAL`
变成 `CONFIRMED`。如果命令返回 `status=unchanged`，表示已有相同的 current provenance，
不要为了改变文字而覆盖项目。

### 6. 失败时先恢复输入，不重写项目

- bootstrap 失败：修正请求、路径或 hash，使用新的 `project_id` 重试；不要覆盖已有目录。
- Generic 绑定失败：修复外部 `manifest.json` 或输出文件，确认项目还没有
  `01_evidence/` 后再重试；不要用 basename 猜归属。
- `preflight-corpus-inputs` 失败：按错误代码修复对应 MAIN、SI、Generic 或 Chemical 输入，再重复只读
  检查；这一步不会替你发布状态。
- `import-corpus-inputs` 失败：保留错误报告，重新计算 hash 并再次运行
  `preflight-corpus-inputs`；不要手改项目 JSON 或把
  缺失项改成 `READY`。

更多错误代码、恢复边界和科学状态见[用户使用说明](docs/用户使用说明.md)。

## 用户应如何理解结果

`CONFIRMED` 只能来自真实合格研究者对原始 MAIN/SI 的明确决定；`AI_PROVISIONAL`
是带定位和来源的未确认候选；`BLOCKED` 表示不能唯一确定，必须保留原因。SHA-256
只能证明文件字节一致，不能证明化学结论正确。

## 当前明确不承诺

- 不开放式发现论文，不自动扩展语料，不默认联网或上传文件；
- 不猜测 SMILES、机制或作者意图；
- 不把 raw Chemical 候选、Dashboard 数字或历史报告当成科学确认；
- 尚未宣称真实 `20–40` 篇运行成功、研究者确认、金标准通过、研究者授权、真实综述
  完成或 DOCX/PDF 已生成/可发布；
- 不在当前收敛中增加新 Provider、RAG、SaaS、多用户、数据库或通用设计系统。

## 文档入口

- [用户使用说明](docs/用户使用说明.md)：按用户任务说明准备、运行、错误和恢复。
- [项目规格](docs/项目规格.md)：当前支持什么、禁止什么、成功标准是什么。

## 本地验证

```bash
make smoke
make quality-check
```

这些命令只做确定性本地检查，不代表真实主题语料已经完成科学审阅。没有运行命令时，
报告不得写成“测试通过”。
