# 2026-08-03 大收敛说明

状态：`VERIFIED_CANDIDATE_NOT_YET_ON_MAIN`

## 1. 这次收敛给用户带来的实际变化

此前项目同时保留 M0、三篇 dual-parse、309 分母、Honest Progressive、旧
Dashboard、Provider/RAG 和多个历史修复波次，用户很难判断哪个入口是真的。

本次先把最有直接用户价值的一条路径收拢出来：

> 用户准备一个主题、五个问题和 20–40 篇论文的 MAIN/SI 后，系统先用可验证的
> 输入和 provenance 检查保护后续综述，不把旧项目状态、同名文件或 AI 候选冒充成
> 当前科学证据。

用户现在可以依次使用：

1. `bootstrap-corpus` 创建全新 variable-N 项目；
2. `bind-generic-parse` 绑定每篇论文的 MAIN 与 SI，要求 `2N` 份 Generic Parse；
3. `preflight-corpus-inputs` 只读检查 MAIN/SI/Generic/Chemical 四条输入 lane；
4. `import-corpus-inputs` 发布 hash-bound provenance，且明确 actor 身份。

这些改变减少了用户的猜测和返工；它们不等于系统已经完成科学综述或导出发布物。

## 2. 本轮真正整合的内容

### 输入层

- 权威 corpus 支持 `20–40` 篇，不再把 `3` 或 `309` 当成公共分母；
- 每个 study 强制 MAIN/SI 成对输入；
- 复制后的 MAIN/SI 都记录 hash、大小和路径；
- 重复 study/source、重复 PDF 字节和 hash 错误在发布前失败；
- 新项目使用独立目录与 external anchor，已存在目标拒绝覆盖。

### 解析与 provenance 层

- Generic Parse 的 variable-N 完成数量是 `2N`；
- MAIN/SI 通过完整相对路径、角色和 hash 绑定；
- MAIN identity 为 `source_id`，SI identity 为 `<source_id>__SI`；
- Source Truth 每个 study 同时包含 MAIN/SI；
- Parse Quality 会覆盖两种文档，input provenance 会再次校验 SI Source Truth、
  页数、hash 和 currentness；
- preflight/import 的失败保持 fail-closed，已有项目状态不被错误请求覆盖。

### 用户文档与入口层

- README、用户使用说明和项目规格改为中文用户视角；
- 报告规则明确先说明用户变化、使用方式和限制；
- 新增 `preflight-corpus-inputs` 与 `import-corpus-inputs` CLI；
- 旧三篇入口保留为 fixture 兼容路径，但不再作为当前用户文档主入口；
- 旧 M0、Provider、RAG、QoderWork 迁移、Phase 8 和历史 worktree 只停车，不删除
  可能仍有恢复价值的对象。

## 3. 仍然没有完成的事情

当前工作树没有真实 20–40 篇主题语料的完整运行证据，也没有因此宣称：

- `SCALED_INPUT_READY=OK`；
- 真实 Dashboard/Playwright 路径完成；
- 5 个 Review-Question Synthesis Matrix 已 current；
- Gold benchmark 达标；
- 同源 DOCX/PDF 已生成并通过 audit；
- 真实合格研究者已确认具体结构或授权发布。

原因不是代码可以“补一个字段”解决，而是这些结论需要真实输入、合法解析、可见
用户 checkpoint 和新鲜 artifact 审计。当前阶段不读外部 PDF、不修改外部项目、不把
synthetic fixture 当作科学运行。

## 4. 减法边界

当前只把低价值入口停车，不做没有恢复证据的删除：

- 旧 Makefile 目标、旧三篇案例、旧 Phase 8、Provider、RAG、QoderWork、历史
  dashboard 和旧 release 波次不出现在用户主流程；
- 它们保留为回归/历史证据，避免误删用户仍需恢复的内容；
- 清理 worktree、branch、外部项目、PDF、SI 或 ignored runtime 前，必须先做精确
  inventory、备份/恢复路径和单独授权。

因此本轮“减法”的用户可见结果是入口更少、说明更清楚；文件物理删除仍不是本轮
交付的一部分。

## 5. 当前验收结果和下一步

本轮候选已经完成本地可重复验证：

- focused variable-N/SI 与 QoderWork 文档回归：`136 passed`；
- `make smoke`：exit 0，包含 `52 passed` 的 variable-N/SI 回归；
- `make quality-check`：exit 0；
- `TMPDIR=/tmp make scaled-review-check`：exit 0，包含输入、证据、投影、维护者
  回归和发布/垂直 review 回归。

这些结果说明用户主路径的本地合同可运行、错误输入会停在对应边界，不能说明真实
20–40 篇主题语料已经完成综述。按照本文件的变更准入，下一步仍需独立 Reviewer
只审当前候选 hash；在该复核有新鲜结果前，不把本候选宣称为已合并到 `main`。

如果任一 gate 失败，报告用户能看到的阻断和唯一恢复动作，不把历史通过记录搬到
当前候选上。
