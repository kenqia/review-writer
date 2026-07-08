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

## PR 5: Real-Lite Data Preflight

目标：

- Inventory existing parsed real assets without reading PDFs.
- Build a 3-5 paper allene real-lite input package.
- Keep the package small enough for Git.
- Preserve source paths for traceability.

Implemented Phase 5b-preflight files:

```text
scripts/demo/build_real_lite_manifest.py
tests/test_real_lite_manifest.py
demo_projects/real_lite_allene_review/
docs/demo/real_lite_preflight_runbook.md
docs/pr/phase5b_real_lite_preflight_pr.md
```

Gate:

```bash
make real-lite-preflight
```

Latest preflight found MinerU markdown, content_list JSON, image directories, metadata JSON, and registry JSONL. It selected 5 allene-related parsed records from 410 registry/metadata records.

Safety boundary:

- no full `chem_papers` scan beyond file count
- no real PDF body read
- no MinerU API
- no Qwen/API call
- no upload
- no Bailian knowledge base
- no image generation

Next:

- Phase 5b: run real-lite E2E using `demo_projects/real_lite_allene_review`.
- Phase 5c: promptfoo or custom eval baseline.
- Phase 6: Bailian knowledge-base RAG preflight.

## PR 6: Real-Lite Offline E2E Run

目标：

- Run a small offline end-to-end skeleton with the prepared real-lite allene package.
- Validate stage artifacts from Library through Export.
- Enforce the Final quality gate in offline mode.
- Keep figure handling explicit with a non-empty pointer/placeholder manifest.

Implemented Phase 5b files:

```text
scripts/demo/run_real_lite_e2e.py
tests/test_real_lite_e2e_workflow.py
docs/demo/real_lite_e2e_runbook.md
docs/pr/phase5b_real_lite_e2e_pr.md
```

Gate:

```bash
make real-lite-e2e-check
```

Selected papers:

```text
P410, P406, P405, P403, P401
```

Safety boundary:

- no PDF body read
- no MinerU API
- no Qwen/API call
- no upload
- no Bailian knowledge base
- no image generation

Current limits:

- text is trimmed excerpt based rather than a full review
- figure output is a pointer placeholder, not a real redraw
- judge mode is offline

Next:

- Phase 5c: real-lite dashboard QA.
- Phase 5d: promptfoo or custom eval baseline.
- Phase 6: Bailian knowledge-base RAG preflight.

## PR 7: Real-Lite Dashboard QA

目标：

- Serve the real-lite output root directly in the dashboard.
- Verify Final, Figures, Matrix, Blueprint, Sections, and Checkpoint payloads.
- Regress `/file?path=` sandbox behavior.
- Keep the run local and offline.

Implemented Phase 5c files:

```text
tests/test_dashboard_real_lite_payload.py
docs/demo/real_lite_dashboard_qa.md
docs/pr/phase5c_real_lite_dashboard_qa_pr.md
```

Updated dashboard files:

```text
view/serve_review_dashboard.py
view/assets/dashboard/final.html
view/assets/dashboard/figures.html
view/assets/dashboard/matrix.html
view/assets/dashboard/blueprint.html
```

Gate:

```bash
make dashboard-real-lite-check
```

Validated payload coverage:

- `final_draft_md`
- `quality_report` and `quality_report_md`
- `figure_manifest`
- `literature_matrix.rows`
- `section_blueprint`
- `section_files`
- 9 checkpoint records

Safety boundary:

- no network except localhost loopback
- no PDF body read
- no MinerU API
- no Qwen/API call
- no upload
- no Bailian knowledge base
- no image generation

Next:

- Phase 5d: eval baseline.
- Phase 5e: Codex-simulated QoderWork manual flow QA.
- Phase 5i: Actual QoderWork CN product-run validation.
- Phase 6: Bailian RAG preflight.

## PR 8: Real-Lite Eval Baseline

目标：

- Add an offline custom eval baseline for the real-lite output package.
- Score workflow completeness, artifact completeness, quality gate health, figure integrity, citation/reference structure, prompt leakage absence, evidence coverage, and safety boundary.
- Keep promptfoo as a future-compatible draft only; do not install or run it.

Implemented Phase 5d files:

```text
evals/README.md
evals/baselines/real_lite_v1.yaml
evals/fixtures/real_lite_expected_metrics.json
evals/reports/.gitkeep
evals/promptfoo/real_lite_v1.promptfooconfig.yaml
scripts/eval/run_eval_baseline.py
tests/test_eval_baseline.py
docs/eval/real_lite_eval_baseline.md
docs/pr/phase5d_eval_baseline_pr.md
```

Gate:

```bash
make eval-baseline-check
```

Metrics:

- `workflow_completeness`
- `artifact_completeness`
- `quality_gate_health`
- `figure_integrity`
- `citation_and_reference_integrity`
- `prompt_leakage_absence`
- `evidence_coverage`
- `safety_boundary`

Current real-lite v1 result:

```text
status: pass
score_total: 100.0
```

Safety boundary:

- no promptfoo dependency
- no network/API call
- no PDF body read
- no Qwen call
- no upload
- no Bailian knowledge base
- no image generation

Next:

- Phase 5e: Codex-simulated QoderWork manual flow QA.
- Phase 5f: portability hardening.
- Phase 5h: reality audit for data provenance and output quality limits.
- Phase 5i: Actual QoderWork CN product-run validation.
- Phase 5j: Clean 3-paper human-verified dataset.
- Phase 6: Bailian RAG preflight.

## PR 9: Portability Hardening

目标：

- Remove personal paths from generic QoderWork docs, skills, scripts, and demo assets.
- Keep Kenqia-specific local validation notes isolated under `docs/local/`.
- Add a portability checker that fails on machine-specific paths in generic files.

Implemented Phase 5f files:

```text
docs/local/KENQIA_LOCAL_VALIDATION.md
docs/portability/portable_skill_guidelines.md
docs/pr/phase5f_portability_hardening_pr.md
scripts/check_portability.py
tests/test_portability.py
```

Gate:

```bash
make portability-check
```

Default placeholder strategy:

- `<REPO_ROOT>`
- `<REVIEW_ROOT>`
- `<PAPER_LIBRARY>`
- `<OUTPUT_ROOT>`
- `<PROVIDER_CONFIG>`
- `<QODERWORK_SKILLS_DIR>`

Safety boundary:

- no PDF body read
- no MinerU API
- no Qwen/API call
- no upload
- no Bailian knowledge base
- no image generation

Next:

- Phase 5g: PR review / merge readiness.
- Phase 5h: Reality audit / data provenance / output quality inspection.
- Phase 5i: Actual QoderWork CN product-run validation.
- Phase 5j-A: Clean 3-paper candidate recommendation.
- Phase 5j-B: User approves Top 3 or requests replacements.
- Phase 5j-C: Read-only parsing for only the approved 3 PDFs.
- Phase 6a: Bailian RAG no-upload preflight.

## PR 10: Reality Audit / Data Provenance / Output Quality Inspection

目标：

- Separate engineering pass from scientific-quality pass.
- Audit the committed real-lite input package for DOI gaps, metadata
  human-check status, page-chrome pollution, trimmed excerpts, pointer-only
  content lists, pointer-only figures, and placeholder source paths.
- Audit the generated real-lite E2E output for draft size, section/reference
  structure, paper signals, skeleton/placeholder signals, matrix/blueprint
  completeness, figure manifest quality, quality gate result, eval result, and
  checkpoint count.

Implemented Phase 5h files:

```text
scripts/audit/audit_real_lite_inputs.py
scripts/audit/audit_real_lite_outputs.py
tests/test_real_lite_input_audit.py
tests/test_real_lite_output_audit.py
docs/audit/real_lite_reality_audit.md
docs/pr/phase5h_reality_audit_pr.md
```

Gate:

```bash
make reality-audit-check
```

Current conclusion:

- real-lite inputs are trusted for engineering fixture use.
- real-lite inputs are not trusted for final scientific review quality.
- real-lite outputs are trusted for demo workflow and dashboard payload QA.
- real-lite outputs need human review and are not citation-accurate review
  evidence.

Safety boundary:

- no PDF body read
- no MinerU API
- no Qwen or Bailian call
- no upload
- no image generation

Next:

- Phase 5i: Actual QoderWork CN product-run validation. The user later ran the
  installed skill in QoderWork CN and pasted the result. That run validates
  product loading/execution for the offline real-lite flow, but used HEAD
  `7b9a8af`, before the Phase 5h commit.
- Phase 5j: Clean 3-paper human-verified dataset.
- Phase 6a: Bailian RAG no-upload preflight.

## PR 11: Actual QoderWork CN Product-Run Validation Record

目标：

- Record actual QoderWork CN product-environment validation separately from
  Codex-simulated manual-flow QA.
- Clarify checkpoint interpretation for mock/demo output versus a true
  production review start.
- Preserve the Phase 5h reality-audit conclusion that engineering pass does not
  imply scientific quality pass.

Implemented Phase 5i files:

```text
docs/qoderwork/actual_qoderwork_cn_product_run_validation.md
docs/pr/phase5i_actual_qoderwork_cn_validation_pr.md
```

Validation record:

- Product: QoderWork CN.
- Skill: `chem-review-orchestrator`.
- Repo: WSL path `<REPO_ROOT_IN_WSL>`; Kenqia's concrete local path is kept in
  `docs/local/KENQIA_LOCAL_VALIDATION.md`.
- Runtime branch: `feat/chem-review-quality-gates`.
- Runtime HEAD: `7b9a8af docs: add merge readiness audit`.
- 11 offline make gates passed.
- real-lite output root existed.
- checkpoint count was 9.
- all checkpoints had `human_review_required=True`.
- eval score was `100.0`.
- safety fields were `not_used` for network, PDF read, Qwen, MinerU API, and
  upload.

Checkpoint conclusion:

- Mock/demo output can be inspected at Export because generated real-lite
  artifacts already exist.
- True production review should stop at Library until paper inputs, MinerU
  parse outputs, metadata, and human checks are trustworthy.

Limits:

- This validation was not run at the latest Phase 5h HEAD.
- It does not prove scientific review quality.
- It does not prove full `chem_papers` readiness.

Next:

- Optional latest-HEAD QoderWork CN read-only revalidation.
- Phase 5j-A: Clean 3-paper candidate recommendation.
- Phase 5j-B: User approves Top 3 or requests replacements.
- Phase 5j-C: Read-only parsing for only the approved 3 PDFs.
- Phase 6a: Bailian RAG no-upload preflight only after or alongside clean
  dataset work; no upload or knowledge-base creation.

## PR 12: Clean 3-Paper Candidate Recommendation

目标：

- Help a non-specialist user choose three candidate papers without manually
  reading 205 PDFs.
- Recommend a balanced Top 3 from PDF filenames, committed real-lite metadata,
  topic-match heuristics, and verifiability signals.
- Keep every item as a candidate only; do not mark any paper as clean or
  human-verified.

Implemented Phase 5j-A files:

```text
scripts/demo/recommend_clean_3paper_candidates.py
tests/test_clean_3paper_recommendation.py
demo_projects/clean_3paper_allene_review/
docs/demo/clean_3paper_candidate_recommendation.md
docs/pr/phase5j_clean_3paper_candidate_recommendation_pr.md
```

Gate:

```bash
make clean-3paper-recommend-check
```

Recommended Top 3:

- `F3I`: review/background candidate.
- `F47A`: representative asymmetric/chiral allene method candidate.
- `P403`: 2025 recent-progress candidate from real-lite metadata.

Safety boundary:

- no PDF body read
- no MinerU API
- no Qwen or Bailian call
- no upload
- no knowledge-base creation
- no image generation
- all candidates remain `human_verified=false`

Next:

- Phase 5j-B: User approves Top 3 or requests replacements.
- Phase 5j-C: Read-only parsing of only the approved 3 PDFs to generate a
  verified metadata draft.
- Phase 5k: Clean 3-paper E2E.

## PR 13: Clean 3-Paper Candidate Approval Pack

目标：

- Convert the Phase 5j-A recommendation into a lightweight approval pack.
- Let the user choose Option A/B/C without acting as a chemistry domain expert.
- Keep all papers as candidates; do not mark anything as human-verified.
- Explicitly define the next authorization text before any PDF verification.

Implemented Phase 5j-B files:

```text
demo_projects/clean_3paper_allene_review/inputs/candidate_approval_pack.json
demo_projects/clean_3paper_allene_review/inputs/candidate_approval_pack.md
scripts/demo/check_clean_3paper_approval_pack.py
tests/test_clean_3paper_approval_pack.py
docs/demo/clean_3paper_candidate_approval.md
docs/pr/phase5j_clean_3paper_candidate_approval_pr.md
```

Gate:

```bash
make clean-3paper-approval-check
```

User options:

```text
Option A: accept Top 3
Option B: replace candidate ___ with alternative ___
Option C: regenerate candidates with changed topic focus
```

Next-stage authorization text:

```text
allow read-only verify top 3 PDFs
```

Safety boundary:

- no PDF body read
- no MinerU API
- no Qwen or Bailian call
- no upload
- no knowledge-base creation
- no image generation
- all candidates remain `human_verified=false`

Next:

- Wait for the user to choose Option A/B/C.
- Only after explicit authorization, Phase 5j-C may read only the approved 3
  PDFs and generate a verified metadata draft that still requires human review.

## PR 14: Clean 3-Paper PDF Verification Draft

目标：

- Use the user-approved Top 3 candidates from Phase 5j-B.
- Perform a narrow read-only PDF existence and filename/metadata verification.
- Generate `verified_draft` metadata, excerpt notes, and figure notes.
- Keep all entries outside final scientific trust until human review.

Implemented Phase 5j-C files:

```text
scripts/demo/verify_clean_3paper_pdfs.py
scripts/audit/audit_clean_3paper_dataset.py
tests/test_clean_3paper_pdf_verification.py
tests/test_clean_3paper_audit.py
demo_projects/clean_3paper_allene_review/inputs/selected_papers.verified_draft.json
demo_projects/clean_3paper_allene_review/inputs/verified_metadata/
demo_projects/clean_3paper_allene_review/inputs/verified_excerpts/
demo_projects/clean_3paper_allene_review/inputs/figure_notes/
docs/demo/clean_3paper_pdf_verification.md
docs/pr/phase5j_clean_3paper_pdf_verification_pr.md
```

Gate:

```bash
make clean-3paper-pdf-verify-check
```

Top 3 verification status:

- `F3I`: `verified_draft`
- `F47A`: `verified_draft`
- `P403`: `verified_draft`

Safety boundary:

- no full `chem_papers` read
- only approved Top 3 paths are touched
- no MinerU API
- no Qwen or Bailian call
- no upload
- no knowledge-base creation
- no image generation
- all entries remain `human_verified=false`

Next:

- Phase 5j-D: optional manual metadata correction.
- Phase 5k: Clean 3-paper E2E using this verified-draft package.

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
