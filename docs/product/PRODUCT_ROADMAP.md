# review-writer 产品路线图

状态：`CURRENT_USER_FACING_ROADMAP`

更新日期：2026-08-03

本路线图只保留能改善用户结果、信任或恢复能力的工作。历史模块仍可能保留在仓库
中作为证据和回归测试，但“存在代码”不等于“当前用户入口”，更不等于科学发布就绪。

## 产品北极星

用户应能从一个综述结论回到：它来自哪篇论文、哪一版 MAIN/SI、哪条证据、哪个决定、
哪个页码/图表定位和哪个导出文件。遇到不确定时，系统要明确告诉用户“不能确定”和
下一步，而不是用流畅文字遮住空缺。

## 当前主线：20–40 篇输入与证据基础线

### 用户问题

用户已经选好主题和论文，却无法可靠区分 MAIN、SI、Generic Parse、Chemical ZIP
是否属于同一 study，也无法知道旧结果是否仍然 current。

### 已交付的用户变化

- 可以创建 20–40 篇的新鲜 variable-N 项目；
- 每篇 MAIN/SI 都被复制、hash-bound 并保留来源身份；
- Generic Parse 要求 `2N`，MAIN/SI identity 分开；
- Source Truth、Parse Quality 和输入 provenance 由实际 `N/K` 计算；
- 缺失、错 hash、过期和跨 study 复用会阻断，不降级为 warning；
- 中文文档说明用户准备什么、得到什么和不能相信什么。

### 当前使用

```text
bootstrap-corpus
  -> bind-generic-parse
  -> preflight-corpus-inputs
  -> import-corpus-inputs
```

### 当前限制

这条线还没有真实 20–40 篇科学运行、研究者确认、Gold benchmark、同源 DOCX/PDF
和无人值守 12 小时证据。因此它是可验证的输入基础线，不是最终综述发布线。

## 下一阶段：一次真实主题的纵向闭环

只有当用户提供完整合法的 MAIN/SI/Generic/Chemical 输入，并通过输入 currentness
后，才进入这一阶段：

1. fresh project 和 Dashboard 主路径；
2. 每篇论文独立 Paper Evidence；
3. 五个 Review-Question Synthesis Matrix；
4. 单一权威 manuscript；
5. claim/source audit、gap disclosure 和同源 DOCX/PDF；
6. 独立 Gold review 和真实研究者 checkpoint。

用户得到的目标变化是：从“输入边界可靠”推进到“得到可读、可审计、清楚披露不确定性
的综述交付物”。这阶段的任何成功都必须用新鲜真实 artifact 证明，不能沿用 synthetic
fixture 或旧项目状态。

## 历史资产的处理方式

| 历史资产 | 仍有价值的部分 | 当前处理 |
| --- | --- | --- |
| M0/PR A | 案例中立、离线、路径和配置保护 | 作为兼容回归证据，不是当前大语料入口 |
| 三篇 dual-parse fixture | 测试 MAIN/SI、Source Truth 和失败零写入 | 仅测试/legacy adapter |
| Honest Progressive | `CONFIRMED/AI_PROVISIONAL/BLOCKED` 和 gap 可见性 | 作为科学状态约束，不能绕过 researcher decision |
| Dashboard/Evidence/Synthesis | 为未来纵向闭环保留的用户价值代码 | 需 fresh runtime/review 验收后才可宣称可用 |
| Phase 8、Provider、RAG、QoderWork | 历史实验和部分可复用脚本 | 停车，不进入当前主流程 |
| 旧 worktree/外部项目 | 可能含恢复证据 | 不自动删除；先 inventory、备份和授权 |

## 永不自动进入主线的内容

- 新 Provider、RAG、SaaS、多用户、数据库或部署；
- 开放式 discovery 或第二主题；
- 猜 SMILES、自动确认机制、把 candidate 变成事实；
- 仅增加代理数量、页面数量、抽象层或测试数量，却不改善用户结果的工作；
- 没有可复核恢复路径的递归删除、worktree 清理或外部数据迁移。

## 进入新工作包的门槛

每个新工作包必须先写清：

```text
用户问题=
用户变化=
输入与输出=
GOLD_DELTA=
TRACE_DELTA=
失败时如何恢复=
停止线=
```

如果不能说明用户结果或证据链增量，工作包进入停车场。具体规则见
`docs/product/DELIVERABLE_FIRST_CORE_CONTRACT.md`。
