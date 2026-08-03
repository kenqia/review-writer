# review-writer

review-writer 是一个面向化学研究者的、本地优先、证据可追溯的综述工作台。
当前收敛目标只有一件事：让用户提交一组已经选好的论文后，系统能清楚地说明
哪些 MAIN、SI、Generic Parse 和 Chemical Parse 属于同一篇论文，哪些证据仍需
人工判断，以及任何结果为什么被阻断。

## 现在用户能得到什么

当前主入口支持一个权威的 `20–40` 篇语料项目：

- 每篇论文必须同时提交 MAIN 和 SI，系统会复制并记录它们的 SHA-256；
- Generic Parse 必须为 `2N` 份（每篇 MAIN 一份、SI 一份），不能用同名文件猜测归属；
- 每篇论文会生成包含 MAIN/SI 的 Source Truth 和 Parse Quality 绑定；
- 输入 provenance 会按实际 `N` 和核心论文数 `K` 计算数量，不再固定三篇或 309；
- 缺文件、错 hash、跨论文复用、过期或不完整输入会在发布前失败，并尽量保持零写入；
- Dashboard、Evidence、Synthesis、DOCX/PDF 只能消费 current 且有来源链的结果。

这是一条可验证的输入与证据基础线，不是已经完成科学综述的证明。当前仓库没有
真实 `20–40` 篇主题语料的完整科学运行、研究者确认或可宣称的 DOCX/PDF 发布结果。

## 用户最短流程

在仓库根目录执行。真实论文、SI、Generic 输出、Chemical ZIP 和项目目录建议放在
仓库之外。

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
  --review-root /data/review-projects \
  --request /data/requests/visible-light-review.json
```

用户变化：得到一个全新的、只含输入边界和来源记录的项目；旧项目状态不会被复制。
如果项目 ID 已存在，命令会拒绝覆盖。

### 3. 绑定 Generic Parse

先对项目中 `00_sources/` 下的全部 MAIN/SI 运行已批准的 Generic/MinerU 流程，输出
目录必须包含完整的 `manifest.json`、Markdown、extracted sidecar 和 raw ZIP。然后执行：

```bash
python scripts/run_vertical_review.py bind-generic-parse \
  --project /data/review-projects/visible-light-review \
  --mineru-output /data/mineru/visible-light-review
```

用户变化：每个 study 会得到 MAIN 与 SI 两个不冲突的解析身份，并生成 Source Truth
和 Parse Quality。变量语料必须绑定 `2N` 个 Generic 文档；任何缺失或错绑都会失败。

### 4. 检查并发布输入 provenance

另准备一个输入 manifest。每个 study 需要声明 MAIN 页数、SI 原始文件及 hash、Chemical
ZIP 及页数。详情见[用户使用说明](docs/用户使用说明.md)。先只读检查：

```bash
python scripts/run_vertical_review.py preflight-corpus-inputs \
  --project /data/review-projects/visible-light-review \
  --manifest /data/requests/visible-light-inputs.json
```

确认输出为 `status=ready_for_import` 后，才发布 provenance：

```bash
python scripts/run_vertical_review.py import-corpus-inputs \
  --project /data/review-projects/visible-light-review \
  --manifest /data/requests/visible-light-inputs.json \
  --actor-type human_researcher \
  --actor-label "肯恰大人"
```

这里的“发布”只表示输入绑定和 currentness 已记录，不表示 Chemical 分子已被研究者
确认，也不把 `AI_PROVISIONAL` 变成 `CONFIRMED`。

## 用户应如何理解结果

`CONFIRMED` 只能来自真实合格研究者对原始 MAIN/SI 的明确决定；`AI_PROVISIONAL`
是带定位和来源的未确认候选；`BLOCKED` 表示不能唯一确定，必须保留原因。SHA-256
只能证明文件字节一致，不能证明化学结论正确。

## 当前明确不承诺

- 不开放式发现论文，不自动扩展语料，不默认联网或上传文件；
- 不猜测 SMILES、机制或作者意图；
- 不把 raw Chemical 候选、Dashboard 数字或历史报告当成科学确认；
- 尚未宣称真实 `20–40` 篇运行成功、金标准通过、研究者授权或 DOCX/PDF 可发布；
- 不在当前收敛中增加新 Provider、RAG、SaaS、多用户、数据库或通用设计系统。

## 文档入口

- [用户使用说明](docs/用户使用说明.md)：按用户任务说明准备、运行、错误和恢复。
- [项目规格](docs/项目规格.md)：当前支持什么、禁止什么、成功标准是什么。
- [2026-08-03 收敛说明](docs/CONVERGENCE_2026-08-03.md)：本次整合的用户结果和停车边界。
- [产品路线图](docs/product/PRODUCT_ROADMAP.md)：将历史 M0、当前 variable-N 基础线和未来工作分开。
- [Deliverable-First Core Contract](docs/product/DELIVERABLE_FIRST_CORE_CONTRACT.md)：证据和用户价值的最高项目内约束。

## 本地验证

```bash
make smoke
make quality-check
```

这些命令只做确定性本地检查，不代表真实主题语料已经完成科学审阅。没有运行命令时，
报告不得写成“测试通过”。
