# 当前 canonical contract

状态：`CURRENT_CANDIDATE_CONTRACT`

本文件只说明当前整合候选的用户入口和证据边界；旧 workspace map、旧 execution
authority、旧 handoff 和旧项目报告不能覆盖最新 Approved Spec 或 Core Contract。

## 当前用户入口

```text
20–40 篇 corpus request
  -> bootstrap_corpus_project
  -> bind_generic_parse_outputs（2N 个 MAIN/SI Generic 文档）
  -> preflight_corpus_inputs
  -> import_corpus_inputs
```

`bootstrap_dual_parse_project` 和三篇 fixture 只为兼容回归保留，不能作为当前大语料
入口，也不能恢复固定 `3` 或固定 `309` 的公共语义。

## 当前不变量

- `20 <= N <= 40`；core 数为当前请求中 `tier=core` 的实际 `K`；
- 每篇 study 必须有一份 MAIN 和一份 SI；
- MAIN/SI PDF 都复制到 fresh project 并记录 hash、大小和角色；
- Generic Parse 必须有 `2N` 个完成项，并按完整相对路径和 hash 绑定；
- MAIN source identity 为 `source_id`，SI source identity 为 `<source_id>__SI`；
- Source Truth 每个 study 必须同时闭合 MAIN/SI；
- 输入 provenance 必须再次验证 SI hash、页数、Source Truth 和 currentness；
- 失败路径 fail-closed，不把缺失或错绑降级为 warning，也不手改 JSON 伪造 READY；
- `CONFIRMED` 只能由真实合格研究者产生，模拟 actor 不能冒充真实用户。

## 当前明确不是的东西

- 不是一场真实主题综述的成功证据；
- 不是 Gold benchmark、研究者授权或 DOCX/PDF 发布证明；
- 不是对旧项目、旧 external project、旧 runtime 或旧 branch 的继承授权；
- 不是删除历史 worktree、外部 PDF/SI 或候选 artifact 的授权。

## 变更准入

任何后续修改都要从最新用户目标出发，写清用户变化、GOLD_DELTA、TRACE_DELTA、
测量方式和停止线。没有直接用户价值或证据链增量的修改停车。需要真实科学内容
或外部运行时的工作，必须另有 fresh input 和独立验收，不能靠 synthetic fixture 代替。
