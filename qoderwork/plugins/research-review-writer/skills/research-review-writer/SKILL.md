---
name: research-review-writer
description: 当科研用户要在 QoderWork 写作工作台中，以三次确认完成证据受控的中文综述和 DOCX 时使用。
---

# 科研综述专家

在 QoderWork 内置“写作工作台”中执行一个有界综述作业。研究者只进行以下三次 interaction；两个 Automatic 阶段由插件连续调度，不增加用户可见编号。语义任务交给六个既有 Agent，确定性任务只运行下列仓库维护命令。

## 1. Review Brief

- 把用户给出的 topic/context 委派给 `REVIEW_BRIEFING_AGENT`，只询问缺失的 material scope：研究问题、目标读者与语言、时间/纳排边界、可用本地材料和交付形式。已有信息不重复询问。
- 展示 human-readable brief；内部将待确认字段交给本地 product command `scripts/run_vertical_review.py` 的 `init` 子命令，由它写入状态为 `AWAITING_BRIEF_CONFIRMATION` 的 `00_brief/review_state.json`，不要求研究者操作内部状态。
- 启动 `view/serve_review_dashboard.py` 的 localhost dashboard，并呈现该项目的 brief URL。
- 此处只等待一次确认；留在同一个 QoderWork 任务中观察通用状态接口，直到状态为 `BRIEF_CONFIRMED` 且阶段为 `ready_for_discovery`。确认动作不得改写 brief，也不得自身触发检索、Provider 或网络操作。
- 未观察到 `BRIEF_CONFIRMED` 前不得委派 `DISCOVERY_ACQUISITION_PLANNER`，也不得生成 search plan 或运行 discovery/acquisition；确认后的 brief 是后续检索、证据和写作的唯一范围基线，同一任务随后自动继续。

### Automatic corpus/evidence（后台自动工作，不是 interaction）

- `DISCOVERY_ACQUISITION_PLANNER` 根据 confirmed brief 与 candidate pool 生成 bounded scholarly-search-plan.v1、screening decisions 和 acquisition rows。只用 `scripts/discovery/discover_scholarly_corpus.py` 与 `scripts/acquisition/acquire_public_corpus.py` 执行 Task 1/2 的检索和合法获取；候选在验证前保持待核验。
- 先处理三篇 calibration，记录实测消耗并给出 credits forecast；未超过已确认预算后，自动按 4–6 篇 batch 继续。若缺少 job-level Qoder egress/credits 授权，必须停在任何 paid run 之前。
- 每项研究先由 `scripts/evidence/build_pdf_text_layers.py` 与 `scripts/evidence/build_page_atom_catalog.py` 产生确定性 atom catalog，再以 fresh delegation contract 委派 `PER_STUDY_EVIDENCE_EXTRACTOR` 选择 atom，随后用 `scripts/evidence/assemble_evidence_candidate_from_atoms.py` 和 `scripts/evidence/validate_evidence_candidate.py` 组装、校验 candidate。
- 对每项 assembled candidate 重新委派 `ADVERSARIAL_EVIDENCE_REVIEWER` 做 fresh adversarial review，再运行 `scripts/run_vertical_review.py` 的 `register-study` 完成逐项 deterministic registration。失败项写入 `01_evidence/exception_queue.json`，其余研究继续；整个队列无需研究者按单项触发。
- fresh delegation contract 只约束每次以最小、当前输入重新委派，不声称底层平台提供额外的上下文隔离能力。

## 2. Scientific Risk Packet

- 所有可处理研究完成后，只运行一次 `scripts/run_vertical_review.py` 的 `build-risk-packet`，构建去重的 Scientific Risk Packet；它同时包含必须裁决的目标与确定性抽样项。
- 在写作工作台集中呈现科学表述、证据、冲突和建议动作，只等待一次 `approve / reword / exclude / unresolved` 决定。
- 应用决定时运行同一 product command 的 `apply-risk-decisions`。系统在后台自动携带当前 `review_target_digest`；研究者看不到也不填写 hash。
- BLOCKED 决定具有单调性；没有本次集中决定明确放行的 BLOCKED 或 HUMAN_REQUIRED 内容不得进入 Writer。

### Automatic Draft/Final（后台自动工作，不是 interaction）

- 运行 `scripts/run_vertical_review.py` 的 `build-writer-packet`，只从 APPROVED claim 生成 `02_claims/writer_packet.json`。
- 以 fresh delegation contract 将该 packet 委派给 `SYNTHESIS_MANUSCRIPT_WRITER`，生成 section drafts、唯一 authoritative manuscript 与 `manuscript_lineage.json`；正文不读取其他科学来源。
- 运行 `scripts/validators/validate_review_quality.py` 与 `skills/review-final-audit-release/scripts/final_audit_scan.py`，再由 `QUALITY_RELEASE_REVIEWER` 对 manuscript、lineage 和 quality report 给出语义发布 verdict。任何 BLOCKED、HUMAN_REQUIRED 或确定性失败都不能被它覆盖。
- 通过后使用现有 `skills/review-export-docx/scripts/md2docx.py` 做确定性 export，并由 localhost dashboard 呈现同一 authoritative manuscript 的编辑工作台与 DOCX。

## 3. Final Review

向研究者呈现可编辑写作工作台、质量/发布结论和 DOCX，只等待最终确认。实质修改会使旧 verdict 失效，并自动重跑相关确定性检查后再回到本次 Final Review，不增加新的 interaction 类型。

## 运行与停止边界

只运行本 Skill 明列的 Task 1–4 product/evidence 命令和既有 dashboard、quality、release、export 命令。必要 material scope 缺失、来源不可访问、授权或预算缺失、研究进入 exception、集中科学决定未闭合、质量/导出失败时，展示当前阶段与可执行下一步；单项 exception 不阻塞其他可处理研究。不得虚构完成、证据、引用或授权。
