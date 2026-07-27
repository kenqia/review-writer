---
name: research-review-writer
description: 当科研用户要在 QoderWork 写作工作台中，以三次确认完成证据受控、按指定语言写作的综述和 DOCX 时使用。
---

# 科研综述专家

在 QoderWork 内置“写作工作台”中执行一个有界综述作业。研究者只进行以下三次 interaction；两个 Automatic 阶段由插件连续调度，不增加用户可见编号。语义任务交给六个既有 Agent，确定性任务只运行下列仓库维护命令。

本 Skill 已由界面激活；不得再次调用 Skill 工具。已安装的 Agent 与下列命令就是运行合同：不得探索插件目录、仓库结构、README 或 docs，不得先派发结构探索任务，也不得用 `ls`、glob 或全文搜索猜测入口。

## 1. Review Brief

- 直接委派 `REVIEW_BRIEFING_AGENT` 处理用户给出的 topic/context。每个新项目都默认核对关键范围，不依赖用户写出“先追问”；最多 12 个，只询问缺失的 material scope 与会改变结果的事项。覆盖主题、核心研究问题、目标读者、输出语言、时间范围、目标研究数量、纳入标准、排除标准、本地材料或公开检索、交付格式、图片需求与 credits/外部处理授权。已有明确答案不重复询问；不得用旧会话内容静默补全新项目。保留 QoderWork 的结构化关键问题弹窗。
- Briefing 完成后，从 topic 派生一个 portable kebab-case `<project_id>`。若同名项目已存在，停止并报告冲突；不得删除、覆盖或复用。把 human-readable brief 映射为 `topic`、`review_question`、`audience`、`output_language`、`from_year`、`to_year`、`target_primary_studies`、`acceptable_core_range`、`required_modes`、`exclusions`、`deliverables` 等已有字段，写入一个 workspace-local temporary JSON；不向研究者展示或索取该路径。
- 在索取任何 Brief 确认之前，严格运行一次本地 product command：`python scripts/run_vertical_review.py init --review-root review-projects --project-id <project_id> --brief <temporary_brief_json>`。只接受输出状态 `AWAITING_BRIEF_CONFIRMATION`；该命令把项目与 `00_brief/review_state.json` 直接创建在工作台读取的 `review-projects/` 中，不要求研究者操作内部状态；不得移动或复制项目目录。
- 随后在后台启动一次 `view/serve_review_dashboard.py`：`python view/serve_review_dashboard.py --review-root . --host 127.0.0.1 --port 8765`。启动进程必须继续存活；再读取 `127.0.0.1:8765/api/project/<project_id>/review-state`，只有响应 JSON 的 `project_id` 精确匹配、`status` 为 `AWAITING_BRIEF_CONFIRMATION` 且 `current_stage` 为 `review_brief` 才算健康。generic HTTP 200 不足以证明是本次实例；若启动进程已退出、端口被旧 dashboard 占用或上述三项不匹配，立即报告 `DASHBOARD_INSTANCE_MISMATCH`，不得呈现链接或启动 watcher。验证通过后才把 `127.0.0.1:8765/review` 作为可点击 brief URL 呈现给研究者。不得为此探索文件、读取 README 或另建 dashboard。
- 可以在聊天中概述 human-readable brief，但不得在聊天中索取 Brief 确认。只在 dashboard 的 Brief 确认界面等待，并且只等待一次确认：呈现 dashboard 后，立即在前台运行 `python scripts/run_vertical_review.py wait-state --project-dir review-projects/<project_id> --status BRIEF_CONFIRMED --stage ready_for_discovery --poll-seconds 2 --timeout-seconds 43200`。这是无 Provider、无网络的本地等待。若返回 `WAIT_STATE_TIMEOUT`，立即停止当前 QoderWork 执行，告知“项目已安全保存；完成界面操作后发送‘继续当前综述项目’”，不得自动重试或继续付费步骤。
- Review Brief/job authorization 必须在上传前披露 full-PDF MinerU egress 并取得明确确认。不得在 chat 中读取或暴露 token 值；缺少该授权或 token 时合并为一个具体 blocker。
- Brief 确认后、discovery 或任何 paid delegation 之前，严格运行 `python scripts/run_vertical_review.py preflight --review-root . --mineru-egress-authorized`，并查询一次 QoderWork Usage 与已安装 Agent 清单。preflight 必须检查工作目录、Python、pdftotext、MinerU parser/token/network、DOCX 与图片依赖；Usage 必须确认当前余额、预算和 reserve。任一项失败即报告 `MINERU_PREFLIGHT_BLOCKED` 或具体 credits/Agent blocker；不得中途降级。绝不读取、打印或复制 token 值。
- 未观察到 `BRIEF_CONFIRMED` 前不得委派 `DISCOVERY_ACQUISITION_PLANNER`，也不得生成 search plan 或运行 discovery/acquisition；确认后的 brief 是后续检索、证据和写作的唯一范围基线，同一任务随后自动继续。

### Automatic corpus/evidence（后台自动工作，不是 interaction）

- 插件在同一个任务内运行 dashboard、discovery/acquisition、manual ZIP import 与 MinerU 命令；这里的任务就是同一个 QoderWork 任务。研究者只确认 Brief、条件性上传一个 ZIP、审阅 Risk Packet，并在 Final Review 编辑和下载 DOCX。
- `DISCOVERY_ACQUISITION_PLANNER` 根据 confirmed brief 与 candidate pool 生成 bounded scholarly-search-plan.v1、screening decisions 和覆盖每个 expected MAIN/SI 的 acquisition rows。只用 `scripts/discovery/discover_scholarly_corpus.py` 与 `scripts/acquisition/acquire_public_corpus.py` 执行一次确定性 public-direct 检索和合法获取；候选在验证前保持待核验。Qwen 不逐篇浏览或下载论文，也不启动浏览器机器人。
- canonical 数据位置固定：检索、筛选与计划只写 `00_discovery/candidate_pool.json`、`00_discovery/screening_decisions.json`、`00_discovery/acquisition_manifest.json`；获取结果只写 `00_sources/acquisition_receipt.json` 与既有 final receipt。不得在 `00_sources` 创建第二份 acquisition manifest，也不得让 dashboard 与 product command 读取不同位置。
- 剩余来源只显示一次 consolidated HTML queue。若仍有缺失，暂停进行一次必要来源交接：研究者从页面链接下载并上传一个 ZIP，不逐篇提问，也不要求编辑映射文件。这个条件性 ZIP 是至多一次 consolidated 输入 handoff，不是新的科学 decision；科学 checkpoints 仍只有 Brief、Risk Packet、Final Review。
- 发布 queue 后，同一个任务观察固定的项目相对 inbox：`review-projects/<project_id>/00_sources/manual_upload/inbox/source_bundle.zip`，等待最长 86400 秒。文件出现后只运行一次 `scripts/acquisition/import_manual_archive.py`，随后立即运行 `scripts/acquisition/acquire_public_corpus.py` 的 `--verify-only` 并继续既有 MinerU 阶段；不要求研究者再次点击继续，也不询问或接受 ZIP 路径。unmatched / ambiguous / missing rows 继续留在同一个 queue；不得手工解压、复制、重命名或按文件名语义猜测归属。超时按 `WAIT_STATE_TIMEOUT` 安全退出并提示“继续当前综述项目”。
- 来源身份闭合后，严格调用仓库既有解析器 `skills/mineru-precise-parse-review-writer/scripts/parse_review_writer_pdfs.py`，输入项目 source directory，输出项目 parse directory，保持 incremental 默认；除非另行批准一次重跑，否则不得使用 `--force`。
- MinerU 只提供 semantic Markdown/figures/tables；`pdftotext` reading/layout layers 对 exact page locators 与 verbatim quotes 保持 authoritative。构建 text layers 时一次命令传入全部 `--source`，不得逐篇使用 `--force`。Qwen 与 MinerU 都不得创作 locator/page/quote fields。
- 先处理三篇 calibration，使用 QoderWork Usage 记录每批 `credits before/after` 并给出 credits forecast；未超过已确认预算后，自动按 4–6 篇 batch 继续。若 Usage 不可读、缺少 job-level Qoder egress/credits 授权或 reserve 将被突破，必须停在任何 paid run 之前。
- 解析完成后自动连续执行每项研究的 atom catalog → Qwen selector → deterministic assembly/R0 → fresh reviewer → registration：先由 `scripts/evidence/build_pdf_text_layers.py` 与 `scripts/evidence/build_page_atom_catalog.py` 产生确定性 atom catalog，再以 fresh delegation contract 委派 `PER_STUDY_EVIDENCE_EXTRACTOR` 选择 atom，随后用 `scripts/evidence/assemble_evidence_candidate_from_atoms.py` 和 `scripts/evidence/validate_evidence_candidate.py` 组装、校验 candidate。
- 对每项 assembled candidate 重新委派 `ADVERSARIAL_EVIDENCE_REVIEWER` 做 fresh adversarial review，再运行 `scripts/run_vertical_review.py` 的 `register-study` 完成逐项 deterministic registration。失败项写入 `01_evidence/exception_queue.json`，其余研究继续；整个队列无需研究者按单项触发。
- 科学流水线严格 fail closed：MinerU 缺失时不得用 pdftotext-only、Read PDF 或模型直读替代 atom catalog；不得手工构造 candidate、R0 report 或 reviewer verdict。`validate_evidence_candidate.py` 返回任何 `R0_FAIL` 时不得注册；`register-study` 会重新计算并比对 canonical R0。不得以口头判断豁免 deterministic gate。
- fresh delegation contract 只约束每次以最小、当前输入重新委派，不声称底层平台提供额外的上下文隔离能力。

## 2. Scientific Risk Packet

- 所有可处理研究完成后，只运行一次 `scripts/run_vertical_review.py` 的 `build-risk-packet`，构建去重的 Scientific Risk Packet；它同时包含必须裁决的目标与确定性抽样项。
- 在写作工作台集中呈现科学表述、证据、冲突和建议动作，只等待一次 `approve / reword / exclude / unresolved` 决定。
- 呈现后运行同一个本地 wait-state，目标为 `risk_decisions_applied / ready_for_writing`，使用 `--timeout-seconds 86400`；超时安全退出并使用同一恢复指令，不得后台替研究者批量 APPROVE。
- Risk 决定只能由研究者在 localhost 工作台提交；不得调用 CLI、编写脚本或生成决定文件代替研究者。提交后只运行 `wait-state` 观察 `risk_decisions_applied / ready_for_writing`，研究者看不到也不填写内部绑定字段。
- BLOCKED 决定具有单调性；没有本次集中决定明确放行的 BLOCKED 或 HUMAN_REQUIRED 内容不得进入 Writer。

### Automatic Draft/Final（后台自动工作，不是 interaction）

- 运行 `scripts/run_vertical_review.py` 的 `build-writer-packet`，只从 APPROVED claim 生成 `02_claims/writer_packet.json`，并生成一张完全原创、由已批准证据汇总得到的 comparative evidence figure；不得无许可证复制网上或论文图片。MinerU 提取图只能进入候选，复用时必须有明确 license/attribution，否则改为基于已验证事实重绘。
- 以 fresh delegation contract 将该 packet 委派给 `SYNTHESIS_MANUSCRIPT_WRITER`，生成 section drafts、唯一 authoritative manuscript 与 `manuscript_lineage.json`；正文不读取其他科学来源，并必须引用 packet 中的原创 comparative evidence figure。Provider 输出先保留原字节，再运行 `python scripts/run_vertical_review.py bind-draft --project-dir review-projects/<project_id> --manuscript <provider_manuscript> --lineage <provider_lineage>`，一次性绑定到 `04_first_draft/first_draft.md` 与 `04_first_draft/manuscript_lineage.json`；不得只复制 Markdown、丢弃 lineage 或直接覆盖既有正文。
- 运行 `scripts/validators/validate_review_quality.py` 与 `skills/review-final-audit-release/scripts/final_audit_scan.py`，再由 `QUALITY_RELEASE_REVIEWER` 对 manuscript、lineage 和 quality report 给出语义发布 verdict。任何 BLOCKED、HUMAN_REQUIRED、缺图、broken image、placeholder 或其他确定性失败都不能被它覆盖；不得把 blocking issue 口头解释成可接受。
- 通过后使用现有 `skills/review-export-docx/scripts/md2docx.py` 做确定性 export，并由 localhost dashboard 呈现同一 authoritative manuscript 的编辑工作台与 DOCX。

## 3. Final Review

向研究者呈现可编辑写作工作台、质量/发布结论和 DOCX，只等待最终确认。实质修改会使旧 verdict 失效，并自动重跑相关确定性检查后再回到本次 Final Review，不增加新的 interaction 类型。

## 运行与停止边界

只运行本 Skill 明列的 Task 1–4 product/evidence 命令和既有 dashboard、quality、release、export 命令。必要 material scope 缺失、来源不可访问、授权或预算缺失、研究进入 exception、集中科学决定未闭合、质量/导出失败时，展示当前阶段与可执行下一步；单项 exception 不阻塞其他可处理研究。不得虚构完成、证据、引用或授权。
