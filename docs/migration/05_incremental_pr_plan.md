# Incremental PR Plan

## 结论

迁移应拆成三阶段：安全瘦身与文档、质量 validators、QoderWork/阿里云 adapter。不要一次性把所有技能、UI、云 API、生成逻辑混成大改。

## PR 1: Safety And Migration Baseline

目标：

- repo clean-room 化
- 数据外置
- token 示例化
- Codex discovery symlink
- QoderWork skill source skeleton
- migration docs

验收：

```bash
make smoke
make quality-check
python3 scripts/install_qoderwork_skills.py
```

## PR 2: Chemistry Validators

目标：

- 新增 static validators
- 输出 `quality_report.json/md`
- 增加 fixture tests
- 接入 `make quality-check`

验收：

- 引用乱序失败。
- 重复图注报告。
- broken/missing source image 报告。
- prompt leakage 示例被捕获。
- good minimal fixture 通过。
- 标题一致性作为 LLM judge task 输出但不调用 API。

Phase 2 first batch implemented:

```text
scripts/validators/validate_review_quality.py
tests/test_quality_validators.py
tests/fixtures/quality/*.md
docs/quality/chem_review_quality_rules.md
```

## PR 3: Adapter And Export Expansion

目标：

- LLM/retrieval/image adapter
- DashScope/Qwen/Bailian/Wan no-op stubs
- PDF/LaTeX skeleton
- QoderWork installer apply path

验收：

- 无 key offline smoke 通过。
- 有 key 时只通过 adapter 调用。
- 不配置图像 provider 时终稿不能假装图文并茂。

Phase 4a adapter skeleton implemented:

```text
review_writer/providers/
review_writer/retrieval/
review_writer/image/
review_writer/config/load_providers.py
scripts/check_providers.py
tests/test_provider_adapters.py
config/providers.example.yaml
docs/providers/alibaba_adapter_design.md
```

New gate:

```bash
make provider-check
```

Phase 4b should stay narrow: one controlled hello-Qwen call with temporary env only, no key printing, no shell rc changes, no paper upload, and explicit user approval before network access.

## 风险

- PR 过大导致 review 困难。
- 全局 skill 安装造成漂移。
- LLM judge 无 deterministic fallback。
- 图像生成改变化学含义。

## 推荐修改

保持每个 PR 可独立验证；远端 push、全局安装、真实 API smoke 都必须人工确认。

## 验收标准

- 每个 PR 都有命令级验证。
- 每个 PR 都能在无真实 API key 环境下给出明确结果。
- 每个 PR 都不触碰 Codex/QoderWork 全局配置。
