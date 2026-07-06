# QoderWork Gap Analysis

## 结论

QoderWork 迁移建议使用 5 个 skill：`chem-review-orchestrator`、`chem-review-library-prep`、`chem-review-planning`、`chem-review-drafting`、`chem-review-quality-release`。repo 内已建立 `qoderwork/skills/` 作为可版本化 skill source，不自动安装到全局。

## 证据

- 原 Codex skill 数量较多，阶段粒度适合 agent 内部路由，但不适合作为用户直接入口。
- QoderWork 目标目录为 `~/.qoderwork/skills/<skill-name>/SKILL.md`。
- 用户确认使用 symlink 处理 Codex repo-scoped discovery，并保持大量人工介入。

## 风险

- 过多 QoderWork skills 会让入口混乱。
- 过少 skills 会把 library prep、drafting、quality release 的职责混在一起。
- 全局安装会产生漂移和覆盖风险。

## 推荐修改

| Skill | Trigger description |
|---|---|
| `chem-review-orchestrator` | Orchestrate an AI Scientist chemistry review workflow from topic to audited deliverables, preserving human checkpoints. |
| `chem-review-library-prep` | Prepare local PDFs/MinerU outputs into review metadata with validation and human audit. |
| `chem-review-planning` | Turn topic and local metadata into discovery, matrix, outline, and blueprint. |
| `chem-review-drafting` | Draft sections, select source-grounded figures, redraw figures, and merge first draft. |
| `chem-review-quality-release` | Validate citations, figures, captions, formulas, headings, leakage, and export deliverables. |

Configuration should pass:

```text
project_id
review_root
data_root
topic
paper_library
output_format
provider_config
```

## Skill UI

Keep local dashboard first. QoderWork UI can later provide:

- project status
- next action
- blocking issues
- checkpoint confirmation buttons

## Installer

Use `scripts/install_qoderwork_skills.py`. Default is dry-run. `--apply` must require explicit user confirmation before use.

## 验收标准

- `qoderwork/skills/*/SKILL.md` exists for the five skills.
- Installer dry-run prints source/target and copies nothing.
- No writes to `~/.qoderwork` happen without `--apply`.
- Human checkpoints remain documented in the orchestrator.
