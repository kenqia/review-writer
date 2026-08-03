# 2026-08-03 收敛 inventory

状态：`VERIFIED_CANDIDATE_NOT_YET_ON_MAIN`

这份清单服务于恢复和减法，不是产品验收，也不是删除授权。当前整合候选位于
独立 worktree；`main` 尚未因此自动改变。

## 当前保留对象

- 当前整合候选代码、schema、测试和中文用户文档；
- 旧 branch/worktree，直到确认没有未跟踪数据、ignored runtime 或用户修改；
- 外部论文、SI、MinerU、Chemical ZIP 和 review-projects；
- 历史 M0、三篇 fixture、Phase 8、Provider、RAG、QoderWork 和 dashboard 代码，
  作为回归或恢复证据。

## 当前用户主路径

```text
bootstrap-corpus
bind-generic-parse
preflight-corpus-inputs
import-corpus-inputs
```

其他命令和 Makefile 目标不是当前默认入口。停车不代表删除，也不代表它们已经通过
当前 `20–40` 篇真实运行验收。

## 目前不能据此宣称

- 当前 `main` 已经合并本轮候选；
- 真实 20–40 篇综述已完成；
- Dashboard/Playwright、五个综合矩阵、Gold benchmark、DOCX/PDF audit 已通过；
- 任何具体分子已获得真实研究者确认。

## 当前 fresh verification

- focused variable-N/SI 与 QoderWork 文档回归：`136 passed`；
- `make smoke`：exit 0；
- `make quality-check`：exit 0；
- `TMPDIR=/tmp make scaled-review-check`：exit 0。

上述证据只证明仓库内合同、回归和用户入口可重复运行。独立 Reviewer 尚未对本候选
hash 给出新鲜结果，因此 `main` 仍保持未变，真实主题综述和科学发布仍未宣称。

## 未来物理清理的闸门

删除、移动、重命名或覆盖前必须同时具备：

1. 精确目标清单；
2. 文件和 hash inventory；
3. 可恢复备份或明确的 Git 恢复路径；
4. 确认没有 dirty/untracked/ignored 用户数据；
5. 单独明确授权。

在这些条件满足前，减法以“从用户入口和文档中停车”为主，不对历史对象做不可逆
删除。任何清理报告都先说明用户会失去什么、如何恢复，再说明删除结果。
