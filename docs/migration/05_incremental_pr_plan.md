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

Phase 4b controlled hello Qwen scope:

```text
scripts/hello_qwen_openai_compatible.py
tests/test_hello_qwen_safety.py
docs/providers/hello_qwen_runbook.md
```

Gate:

```bash
make qwen-hello-dry-run
```

The only permitted real call is a single fixed prompt expecting `QWEN_HELLO_OK`. The call is blocked unless the user explicitly replies `allow hello qwen`; missing env or dependency failures are classified without modifying config.

Phase 4c Qwen judge quality gate scope:

```text
review_writer/judges/
scripts/llm_judges/qwen_review_quality_judge.py
tests/test_qwen_judge_safety.py
docs/providers/qwen_judge_runbook.md
```

Gate:

```bash
make judge-check
```

The validator now supports `--judge-mode offline|qwen`, `--allow-network`, and judge report outputs. Offline remains the default. Qwen judge is limited to title alignment, semantic prompt leakage, and formula review assistance tasks; it does not generate review prose, read PDFs, upload papers, create Bailian knowledge bases, or call image APIs.

Phase 4c-bis timeout hardening:

- First real Qwen judge call reached the provider path but timed out.
- Hello Qwen had already passed, so key/endpoint connectivity is not treated as the primary suspect.
- Judge request hardening added compact prompt mode, `--timeout-seconds`, `--max-output-tokens`, `--task-limit`, prompt-size telemetry, elapsed-time telemetry, and `client_timeout` / `server_overloaded_503` classification.
- Any real retry must be limited to one attempt and must wait for the exact confirmation: `allow qwen judge retry once`.

Phase 4 closeout:

- Phase 4b hello Qwen passed with the fixed hello prompt.
- Phase 4c first real judge call timed out.
- Phase 4c-bis hardening was added.
- The single controlled retry passed with compact prompt, 90 second timeout, 128 max output tokens, and task limit 1.
- The bad title alignment fixture received `verdict=fail`, matching the expected quality-gate direction.
- Safety boundaries held: no key printing, no paper正文/PDF read, no upload, no Bailian knowledge base creation, no image API, and no automatic retry.
- Conclusion: Alibaba OpenAI-compatible provider and Qwen-backed judge are usable, but every real call must remain explicitly user-authorized.

## PR 4: Tiny Offline E2E Demo

目标：

- Add a tiny synthetic allene-review demo project.
- Exercise workflow skeleton from Library through Export.
- Keep the run offline and deterministic.
- Verify checkpoint log, final quality gate, figure manifest, and Markdown export.

Implemented Phase 5a files:

```text
demo_projects/tiny_allene_review/
scripts/demo/run_tiny_e2e.py
tests/test_tiny_e2e_workflow.py
docs/demo/tiny_e2e_runbook.md
docs/pr/phase5a_tiny_e2e_demo_pr.md
```

Gate:

```bash
make tiny-e2e-check
```

Safety boundary:

- no full `chem_papers` scan
- no real PDF body read
- no MinerU API
- no Qwen call
- no upload
- no Bailian knowledge base
- no image generation

Next:

- Phase 5b: real-lite run with 3-5 already parsed MinerU markdown files.
- Phase 5c: promptfoo or custom eval baseline.

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
