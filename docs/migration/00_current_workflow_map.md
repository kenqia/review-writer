# Current Workflow Map

## 结论

当前主入口是 `review-writing-orchestrator`。仓库已经具备从文献入库、主题检索、矩阵/大纲、章节草稿、图片候选/重绘、初稿合并、终稿审查到 DOCX 导出的完整 workflow 骨架，但准备阶段和主写作阶段混在同一个 repo 语境里，且生成数据曾被跟踪。

## 证据

- `skills/技能工作流说明.md` 明确主入口和阶段顺序。
- `skills/review-writing-orchestrator/SKILL.md` 定义 8 个主阶段。
- `view/serve_review_dashboard.py` 提供 `Library -> Discovery -> Matrix -> Blueprint -> Sections -> Figures -> Draft -> Final` 本地人审台。
- `review-library/metadata/papers/P001-P205.metadata.json` 曾被 Git 跟踪，已迁移出 repo 跟踪范围。

## Workflow

| 阶段 | 输入 | 输出 | 人审 | 形态 |
|---|---|---|---|---|
| MinerU parse | PDFs | `mineru-outputs/*` | 否 | API script |
| metadata prep | MinerU/PDF | `review-library/*` | 是 | script + optional LLM |
| discovery | topic/metadata | `00_discovery/*` | 是 | deterministic + retrieval |
| matrix/outline | selected papers | `01_matrix_outline/*` | 是 | LLM-heavy |
| blueprint | outline/matrix/rules | `section_blueprint.json` | 是 | script seed + LLM |
| section drafting | blueprint/matrix | `02_section_drafting/*` | 是 | LLM-heavy + scripts |
| figure redraw | candidates/source images | `03_figure_redraw/*` | 是 | image adapter |
| merge | section drafts/figures | `04_first_draft/*` | 是 | script seed + LLM |
| final audit | first draft/evidence | `05_final_audit/*` | 是 | static + LLM/human |
| export | final markdown | docx/PDF-ready output | 是 | deterministic |

## 风险

- 历史版本曾有多个 skill 文档和脚本默认值使用旧机器绝对路径；迁移后应持续阻止该类路径回归。
- LLM-heavy 阶段缺少统一 adapter 和离线 mock。
- 当前 final audit 的 deterministic gate 仍偏格式，化学质量规则尚未完全脚本化。

## 推荐修改

1. 用 `review_root`/`data_root` 配置替代硬编码路径。
2. 保持人审 checkpoint，不做全自动闭环。
3. 把 metadata/PDF/MinerU/project outputs 固定为外部数据。
4. 把 validators 纳入 `quality-check`。

## 验收标准

- clean clone 不包含示例 metadata、PDF、真实 token。
- 没有真实 API key 被 Git 跟踪。
- 无项目数据时 `make smoke` 仍可运行。
- 每个阶段有输入、输出、人审条件和失败报告。
