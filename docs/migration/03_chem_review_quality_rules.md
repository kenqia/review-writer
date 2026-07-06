# Chemistry Review Quality Rules

## 结论

现有 final audit 已覆盖基础格式 gate，但化学综述质量需要拆成 static check、LLM judge、human audit 三层。第一阶段应先把可确定规则脚本化，再把标题对应、化学准确性、prompt leakage 等交给 LLM/human。

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

## 推荐放置

- 新增 `scripts/validators/chem_review_static_scan.py`。
- `review-final-audit-release` 调用 static validators 后再进行 LLM judge。
- dashboard `Final` 页面显示 `quality_scan.md`。

## 验收标准

- static scan 无项目数据时能显示用法。
- 有 draft 时输出 JSON + Markdown 报告。
- blocking issues 会阻止 release ready。
- LLM judge 缺 provider 时降级为 warning，不阻塞 offline smoke。
