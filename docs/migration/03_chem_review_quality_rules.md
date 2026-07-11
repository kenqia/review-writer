# Chemistry Review Quality Rules

## 结论

现有 final audit 已覆盖基础格式 gate。Phase 2 已新增离线 validator：`scripts/validators/validate_review_quality.py`，把引用顺序、重复图注、图片路径、prompt/workflow 泄漏、参考文献弱检查、化学式风险提示落成 static/heuristic check；标题与正文一致性仍作为 LLM judge placeholder 输出，不调用真实 API。

## 证据

- `final_audit_scan.py` 已检查图片、引用、参考文献、占位符、标题层级等。
- 已知问题包括 P106 源图定位、引用升序、重复图注、化学式上下标、参考文献格式、标题概括性、规则泄漏。

## 规则表

| 规则 | Static | LLM judge | Human | 输入 | 输出 | 通过标准 |
|---|---|---|---|---|---|---|
| 源图定位 | 检查 `source_image_path` 存在、caption/label/page hint 非空 | 判断图是否支持段落 claim | 对照 PDF | `figure_candidates.json` | `figure_quality_scan.json` | 无 missing/broken source |
| 引用数字升序 | regex 解析 `[n]`、范围、首次出现顺序 | 无 | 抽查 | draft md | `quality_scan.md` | 同一 citation group 升序，reference list 对齐 |
| 图注重复 | normalize caption 去重 | 语义重复判断 | 抽查 | draft md/manifest | `quality_scan.md` | 无重复 caption 或有合理说明 |
| 化学式上下标 | 扫疑似 `CO2`, `H2O`, `R2N`, `CuCl2` plain text | 判断是否需下标/上标 | 终稿人工 | draft md/docx | `formula_scan.md` | 风险项已改或列入 remaining issues |
| 文末引用格式 | reference parser | ACS/目标格式 judge | Word/PDF check | draft md | `reference_scan.md` | 编号连续、字段完整、无未引用编号 |
| 小节标题对应内容 | 粗检标题非空/重复 | 标题-正文一致性 | 人审 | section md/blueprint | `heading_judge.md` | 标题概括 section thesis |
| 大标题对应内容 | 粗检标题长度/禁用词 | 标题-abstract-outline 一致 | 人审 | final draft | `title_judge.md` | 大标题能概括主题和范围 |
| 写作思路泄漏 | 扫 rule pack/template instruction phrases | 判断是否为 editor instruction | 人审 | draft md + rule pack | `leakage_scan.md` | 正文无 workflow/prompt 指令 |

## 失败示例

```text
[5, 2]                         # 引用未升序
Figure 3. Same caption...       # 重复图注
CO2/H2O                         # 可能需要 CO₂/H₂O 或 LaTeX
TODO verify mechanism           # editor note 泄漏
Use this pattern when...         # rule pack 泄漏
```

## Phase 2 落地状态

已实现：

- `CRQ001_SOURCE_FIGURE_TRACEABILITY`: Markdown image path 和 manifest source path 存在性检查。
- `CRQ002_CITATION_CALLOUT_ORDER`: `[3,1]`、`[5, 2, 4]`、`[7-5]` 检查。
- `CRQ003_DUPLICATE_CAPTIONS`: `Figure X.` / `图 X` caption 规范化重复检查。
- `CRQ004_CHEMICAL_FORMULA_TYPOGRAPHY`: `CO2`、`H2O`、`Fe3+`、`SO4 2-` 等风险提示与人工任务。
- `CRQ005_REFERENCE_FORMAT_COMPLETENESS`: references.md / references.bib 非空与 author/year/DOI 弱检查。
- `CRQ008_PROMPT_WORKFLOW_LEAKAGE`: workflow、rule pack、blueprint、请生成、本节应当等泄漏词检查。

placeholder：

- `CRQ006_SECTION_HEADING_FIT`: 生成 `llm_judge_tasks`，不调用 LLM。
- `CRQ007_REVIEW_TITLE_FIT`: 生成 `llm_judge_tasks`，不调用 LLM。

## 推荐放置

- CLI: `scripts/validators/validate_review_quality.py`。
- Tests: `tests/test_quality_validators.py` and `tests/fixtures/quality/*`.
- Future integration: `review-final-audit-release` can call the validator and surface `quality_report.md` in the dashboard.

## 验收标准

- static scan 无项目数据时能显示用法或清楚的 missing-file 错误。
- 有 draft 时输出 JSON + Markdown 报告。
- blocking issues 会阻止 release ready。
- LLM judge 缺 provider 时降级为 warning，不阻塞 offline smoke。
