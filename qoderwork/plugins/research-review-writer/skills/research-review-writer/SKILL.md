---
name: research-review-writer
description: 当用户要在 QoderWork 写作工作台中，用一个任务将中文综述主题和本地来源推进为可审计草稿、动态状态与 DOCX 时使用。
---

# 科研综述专家

在 QoderWork 的内置“写作工作台”中执行一个综述任务。语义判断、证据阅读、审查与写作由本专家插件中的 Agents 使用当前工作台模型完成；确定性脚本只负责项目路径、状态、校验与导出。没有直接模型接口、Provider/API 回退或自定义 Workbench SDK。

## 只问必要问题

首次仅补齐以下缺失项：综述主题/问题、目标读者和语言、时间或范围边界、本地工作文件夹、可用本地来源的位置、期望交付（草稿或 DOCX）。若用户已经给出，直接开始；不得猜测个人路径或要求凭据。

## 单任务工作流

1. 由 `REVIEW_BRIEFING_AGENT` 写入 `00_brief/review_state.json` 与简报，状态为 `briefing`。
2. 由 `DISCOVERY_ACQUISITION_PLANNER` 建立来源获取与纳入计划；候选始终是待核验状态。
3. 对每一项已提供研究调用 `PER_STUDY_EVIDENCE_EXTRACTOR`，把可定位证据、风险与缺失写入项目状态计数和证据产物。
4. 由 `ADVERSARIAL_EVIDENCE_REVIEWER` 审查高风险主张、定位、外推和冲突；存在实质性问题即把状态设为 `needs_human_review` 并列出 blockers。
5. 只有可写证据足够时，调用 `SYNTHESIS_MANUSCRIPT_WRITER` 写入 `04_first_draft/first_draft.md`；不能支持的内容不写成事实。
6. 由 `QUALITY_RELEASE_REVIEWER` 形成发布条件。随后运行已有确定性质量检查；仅在人工门通过后使用既有 DOCX 导出端点。

## 项目状态契约

状态文件固定为 `<工作文件夹>/review-projects/<项目标识>/00_brief/review_state.json`，至少包含：`project_id`、`brief`、`current_stage`、`status`、`blockers`、`counts` 和 `updated_at`。`counts` 只记录 `sources`、`evidence`、`claims`。动态仪表盘读取这一文件及现有草稿/终稿目录；不要新建第二份稿件库或证据库。

## 停止条件

仅在以下真实门槛停止：用户未提供必要范围或本地来源；来源不可访问；高风险证据/冲突需专家或人工决定；人工检查点未通过；确定性校验或导出失败。每次停止时说明当前阶段、阻塞项和用户可执行的下一步。不得因模型不确定而虚构完成、虚构引用或切换替代模型。
