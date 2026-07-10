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

## PR 15: Clean 3-Paper Bibliographic Metadata Verification

目标：

- Verify bibliographic metadata for the approved Top 3 without making the user
  act as a chemistry metadata expert.
- Use Crossref, OpenAlex, and Semantic Scholar only as optional public metadata
  aids, not as a single source of truth.
- Record source matches, confidence, missing fields, and conflicts.
- Keep final scientific trust gated on human review.

Implemented Phase 5j-D files:

```text
review_writer/metadata_sources/
scripts/demo/verify_clean_3paper_bibliography.py
tests/test_clean_3paper_bibliography_verification.py
demo_projects/clean_3paper_allene_review/inputs/bibliography_verification_summary.json
demo_projects/clean_3paper_allene_review/inputs/bibliography_verification_summary.md
docs/demo/clean_3paper_bibliography_verification.md
docs/pr/phase5j_clean_3paper_bibliography_verification_pr.md
```

Offline gate:

```bash
make clean-3paper-biblio-check
```

Manual public metadata gate:

```bash
make clean-3paper-biblio-web-check
```

Current metadata draft:

- `F3I`: `bibliographic_verified_draft`, medium confidence.
- `F47A`: `bibliographic_verified_draft`, medium confidence.
- `P403`: `bibliographic_verified_draft`, medium confidence; authors and DOI still need human confirmation.

Safety boundary:

- no full `chem_papers` read
- no non-Top-3 PDF access
- no PDF upload
- no MinerU API
- no Qwen or Bailian call
- no knowledge-base creation
- no image generation
- all entries remain `human_verified=false`

Next:

- Phase 5j-E: key claims and figure notes extraction from only the Top 3 PDFs.
- Phase 5k: Clean 3-paper E2E after accepting remaining metadata caveats.

## PR 16: Clean 3-Paper Claims and Figure Notes Draft

目标：

- Generate a small, human-reviewable claim and figure-note draft package for the
  approved Top 3 papers.
- Avoid pretending metadata/title cues are final scientific evidence.
- Keep every claim and figure note gated by human review.
- Prepare inputs for a later clean 3-paper E2E run.

Implemented Phase 5j-E files:

```text
scripts/demo/extract_clean_3paper_claims_figures.py
tests/test_clean_3paper_claims_figures.py
demo_projects/clean_3paper_allene_review/expected/expected_claims.draft.json
demo_projects/clean_3paper_allene_review/expected/expected_figures.draft.json
docs/demo/clean_3paper_claims_figures_extraction.md
docs/pr/phase5j_clean_3paper_claims_figures_pr.md
```

Gate:

```bash
make clean-3paper-claims-check
```

Current draft counts:

- `F3I`: 3 claim drafts, 1 figure note draft.
- `F47A`: 2 claim drafts, 1 figure note draft.
- `P403`: 2 claim drafts, 1 figure note draft.

Safety boundary:

- no full `chem_papers` read
- only approved Top 3 PDF paths are touched
- no long PDF body text saved
- no MinerU API
- no Qwen or Bailian call
- no upload
- no knowledge-base creation
- no image generation
- all claims and figure notes remain `human_verified=false`
- all claims and figure notes remain `needs_human_review=true`

Next:

- Phase 5j-F: user review / accept metadata and claims draft.
- Phase 5k: Clean 3-paper E2E.

## PR 17: Clean 3-Paper Vertical Slice E2E

目标：

- Move from real-lite engineering proof to a curated clean 3-paper vertical
  slice.
- Use only the approved Top 3 draft package from Phase 5j-A/B/C/D/E.
- Generate a complete offline run with checkpoints, quality report, eval,
  dashboard payload, export skeleton, and user-facing review pack.
- Keep scientific trust gated on human acceptance.

Implemented Phase 5k files:

```text
scripts/demo/run_clean_3paper_e2e.py
tests/test_clean_3paper_e2e_workflow.py
scripts/eval/run_clean_3paper_eval.py
tests/test_clean_3paper_eval.py
tests/test_dashboard_clean_3paper_payload.py
evals/baselines/clean_3paper_v1.yaml
evals/fixtures/clean_3paper_expected_metrics.json
docs/demo/clean_3paper_e2e_runbook.md
docs/eval/clean_3paper_eval_baseline.md
docs/pr/phase5k_clean_3paper_vertical_slice_pr.md
```

Gates:

```bash
make clean-3paper-e2e-check
make clean-3paper-eval-check
make dashboard-clean-3paper-check
```

Current result:

- clean E2E: pass
- clean eval score: 100
- dashboard QA: pass
- quality report: warn because metadata warnings remain visible

Safety boundary:

- no full `chem_papers` read
- no long PDF body text saved
- no MinerU API
- no Qwen or Bailian call
- no upload
- no knowledge-base creation
- no image generation
- all entries remain `human_verified=false`
- `trusted_for_scientific_quality=false`

Next:

- Phase 5l: user-facing review pack and manual acceptance.
- Phase 6a: Bailian RAG no-upload preflight.

## PR 18: Bailian RAG No-upload Preflight

目标：

- 为后续百炼 RAG 小样本 pilot 建立上传前的离线门禁。
- 从 clean 3-paper draft package 生成极小 corpus manifest。
- 明确保留 `needs_human_review=true` 和 `trusted_for_scientific_quality=false`。
- 禁止在 Phase 6a 中上传文件、创建知识库、调用 Qwen/百炼/MinerU/生图 API。

Implemented Phase 6a files:

```text
rag/README.md
rag/bailian/README.md
rag/bailian/data_policy.md
rag/bailian/preflight_config.example.yaml
rag/bailian/no_upload_corpus_manifest.example.json
scripts/rag/bailian_preflight.py
tests/test_bailian_preflight.py
evals/fixtures/rag_expected_questions.json
docs/rag/bailian_rag_preflight.md
docs/pr/phase6a_bailian_rag_preflight_pr.md
```

Gate:

```bash
make bailian-rag-preflight-check
```

Current result:

- no-upload preflight: pass
- selected_count: 3
- allowed_items: F3I, F47A, P403
- blocked_items: 0
- temporary manifest: `/tmp/bailian_no_upload_corpus_manifest.json`

Safety boundary:

- no PDF read
- no raw image or raw MinerU markdown included
- no local absolute paths in the generated manifest
- no secret-like values in the generated manifest
- no Qwen, Bailian, MinerU, or image API call
- no upload
- no knowledge-base creation

Next:

- Phase 6b: optional small Bailian KB pilot only after explicit user authorization.
- Phase 6c: retrieval-answer eval with citation checks, still gated by data policy.

## PR 19: Local RAG Retrieval Baseline

目标：

- 在任何百炼 KB pilot 前，先用本地简单检索验证 no-upload corpus 是否能找回预期 paper。
- 使用 clean 3-paper manifest 和 RAG expected questions。
- 输出 recall@1、recall@3、citation coverage、missed questions。
- 保持 offline-first，不上传、不建库、不调用 Qwen/百炼/MinerU。

Implemented Phase 6b files:

```text
scripts/rag/local_retrieval_baseline.py
tests/test_local_retrieval_baseline.py
evals/baselines/rag_local_retrieval_v1.yaml
evals/fixtures/rag_expected_metrics.json
docs/rag/local_retrieval_baseline.md
docs/pr/phase6b_local_retrieval_baseline_pr.md
```

Gate:

```bash
make rag-local-retrieval-check
```

Current result:

- local retrieval status: pass
- recall@1: 0.8125
- recall@3: 1.0
- citation coverage: 1.0
- missed questions: none
- recommendation: proceed_to_bailian_pilot

Safety boundary:

- no network
- no Qwen, Bailian, MinerU, or image API call
- no upload
- no knowledge-base creation
- no PDF read
- `trusted_for_scientific_quality=false`

Next:

- Phase 6c: Bailian small KB pilot only after the exact authorization `allow bailian small kb pilot`.

## PR 20: Bailian Small KB Pilot Wrapper

目标：

- 生成只包含允许字段的 small KB sanitized payload。
- 默认 dry-run，不联网、不上传、不创建知识库。
- 只有同时传 `--allow-network` 和 `--allow-upload` 才进入真实 pilot wrapper。
- 如果百炼 KB API 合同未实现，安全阻塞为 `blocked_manual_console_required`，不乱传文件。

Implemented Phase 6c files:

```text
scripts/rag/build_bailian_small_kb_payload.py
scripts/rag/bailian_small_kb_pilot.py
tests/test_bailian_small_kb_payload.py
tests/test_bailian_small_kb_pilot_safety.py
docs/rag/bailian_small_kb_pilot_runbook.md
docs/pr/phase6c_bailian_small_kb_pilot_pr.md
```

Gates:

```bash
make bailian-small-kb-payload-check
make bailian-small-kb-pilot-dry-run
```

Current result:

- payload check: pass
- sanitized records: 3
- dry-run: pass
- real-mode wrapper: `blocked_manual_console_required`
- error type: `missing_dependency_or_api_contract`
- real upload: not attempted
- KB id: not created and not written to repo

Safety boundary:

- no PDF/raw image/full markdown/local path/secret in payload
- no default network call
- no default upload
- no default knowledge-base creation
- `trusted_for_scientific_quality=false`

Next:

- Phase 6d: retrieval QA after an actual small KB exists, either via reviewed API contract or manual console run.

## PR 21: Official Bailian SDK-gated Pilot Path

目标：

- 明确百炼 KB 管理 API 不等同于 Qwen OpenAI-compatible / DashScope key。
- 增加官方 SDK dependency/env gate。
- 生成 `/tmp/bailian_small_kb_upload_payload.md` 作为唯一允许上传的 sanitized markdown。
- 增加 `--use-official-sdk` 三重门控路径。
- 缺 SDK/env/API 合同时 fail closed，不上传、不建库。

Implemented Phase 6c-bis files:

```text
review_writer/retrieval/bailian_official_client.py
docs/rag/bailian_official_api_contract.md
```

Updated:

```text
scripts/rag/bailian_small_kb_pilot.py
scripts/rag/build_bailian_small_kb_payload.py
tests/test_bailian_small_kb_pilot_safety.py
Makefile
README.md
docs/rag/bailian_small_kb_pilot_runbook.md
docs/pr/phase6c_bailian_small_kb_pilot_pr.md
```

Gate:

```bash
make bailian-small-kb-official-sdk-dry-run
```

Current result:

- official SDK dry-run: pass
- official SDK modules: checked, no values printed
- KB required env: checked as SET/MISSING only
- real upload: not run by default
- KB id: not written to repo

Next:

- Real SDK pilot only after exact authorization: `allow official bailian sdk pilot`.

## PR 22: Bailian SDK Environment Bridge

目标：

- 解释为什么 Codex 非交互 shell 看不到只写在 `~/.zshrc` 的云环境变量。
- 明确不建议把 AccessKey 移到 `~/.zshenv`。
- 增加官方 SDK/env SET-MISSING 检查脚本。
- 增加默认非 strict gate，避免普通贡献者必须有阿里云 key。
- 记录本机 `zsh -ic` manual bridge 可看到官方 KB env。

Implemented Phase 6c-ter files:

```text
scripts/rag/check_bailian_sdk_env.py
tests/test_bailian_sdk_env_check.py
docs/rag/bailian_sdk_environment.md
docs/pr/phase6c_ter_bailian_sdk_environment_pr.md
```

Gates:

```bash
make bailian-sdk-env-check
make bailian-sdk-env-strict-check
```

Current result:

- default env check: pass/warn and returns 0
- strict env check: may return nonzero when SDK/env missing
- current Codex shell: official SDK/env missing
- `zsh -ic` manual bridge: official KB env SET
- no key values printed
- no API call, upload, or KB creation

Next:

- User may create isolated conda env and install official SDK.
- Real SDK pilot still waits for exact authorization: `allow official bailian sdk pilot`.

## PR 23: Official Bailian SDK Pilot Implementation

目标：

- 按官方 SDK contract 实现 create/upload/index/retrieve 生命周期。
- 仍然保持默认离线；真实路径必须同时传 `--allow-network --allow-upload --use-official-sdk`。
- 只允许上传 `/tmp/bailian_small_kb_upload_payload.md`。
- 只把临时 index id 写入 `/tmp` 报告，不写入 repo。
- cleanup 必须显式传 `--cleanup --cleanup-index-id`，不自动删除。

Implemented Phase 6c-quad files:

```text
review_writer/retrieval/bailian_official_client.py
scripts/rag/bailian_small_kb_pilot.py
tests/test_bailian_small_kb_pilot_safety.py
docs/rag/bailian_official_api_contract.md
docs/rag/bailian_small_kb_pilot_runbook.md
docs/pr/phase6c_bailian_small_kb_pilot_pr.md
```

Gate:

```bash
make bailian-small-kb-official-sdk-dry-run
make bailian-small-kb-official-sdk-real-command
```

Current result:

- official SDK lifecycle implemented behind explicit gates
- default dry-run: no network, no upload, no KB creation
- real command target prints the command only
- one authorized real pilot was attempted once and failed with `unexpected_error` / `UnretryableException`
- no file/index/job id was created, retrieval did not run, and no cleanup was required
- future successful real pilot may create a temporary Bailian index and must be followed by reviewed cleanup

Next:

- Run exactly one authorized real SDK pilot.
- If an index is created, delete it after evaluation using the reviewed cleanup path or Bailian console.

## PR 24: Bailian SDK Error Forensics And Lease-only Probe

目标：

- 不盲目重试 full pilot。
- 为 SDK exception 增加安全取证字段。
- 新增只执行 `ApplyFileUploadLease` 的 lease-only probe。
- 不上传、不 AddFile、不 CreateIndex、不 SubmitIndexJob、不 Retrieve。
- 不输出 pre-signed URL、signed headers、AccessKey、secret。

Implemented Phase 6c-quin files:

```text
scripts/rag/bailian_lease_probe.py
tests/test_bailian_lease_probe_safety.py
docs/rag/bailian_error_forensics.md
```

Updated:

```text
review_writer/retrieval/bailian_official_client.py
scripts/rag/bailian_small_kb_pilot.py
Makefile
docs/rag/bailian_small_kb_pilot_runbook.md
docs/pr/phase6c_bailian_small_kb_pilot_pr.md
```

Gate:

```bash
make bailian-lease-probe-dry-run
make bailian-lease-probe-real-command
```

Decision rule:

- If lease succeeds, a reviewed full pilot retry may be considered.
- If lease fails, fix auth/workspace/category/endpoint/request model according to `safe_error` before any upload-capable run.

Current result:

- one authorized lease-only probe was executed once
- status: `fail`
- error type: `endpoint_or_region_error`
- exception class: `UnretryableException`
- failed phase: `apply_file_upload_lease`
- no lease obtained, no upload, no knowledge base

Next:

- Fix endpoint/region alignment before any full pilot retry.

## PR 25: Bailian Endpoint / Region Alignment

目标：

- 显式化 official SDK endpoint、region、category-id。
- 默认 endpoint 使用官方示例 `bailian.cn-beijing.aliyuncs.com`。
- `--endpoint` 优先；没有 endpoint 时由 `--region` 构造。
- 继续只做 lease-only reprobe，不上传、不建库。
- 保持 `WORKSPACE_ID` 为 official SDK 管理路径变量，避免和 no-upload preflight 的 `BAILIAN_WORKSPACE_ID` 混用。

Updated Phase 6c-six files:

```text
review_writer/retrieval/bailian_official_client.py
scripts/rag/bailian_lease_probe.py
scripts/rag/bailian_small_kb_pilot.py
tests/test_bailian_lease_probe_safety.py
rag/bailian/preflight_config.example.yaml
docs/rag/bailian_error_forensics.md
docs/rag/bailian_official_api_contract.md
docs/rag/bailian_small_kb_pilot_runbook.md
docs/pr/phase6c_bailian_small_kb_pilot_pr.md
```

Gate:

```bash
make bailian-lease-probe-dry-run
make bailian-lease-probe-real-command
```

Decision rule:

- If lease succeeds, a reviewed full pilot retry may be considered.
- If lease fails again, fix permission/workspace/category/endpoint/request parameters first.

Current result:

- one authorized explicit-endpoint lease reprobe was executed once
- endpoint: `bailian.cn-beijing.aliyuncs.com`
- region: `cn-beijing`
- category_id: `default`
- status: `fail`
- error type: `endpoint_or_region_error`
- exception class: `UnretryableException`
- no lease obtained, no upload, no knowledge base

Next:

- Check endpoint reachability, workspace-region binding, account permissions, and SDK endpoint expectations before any full pilot retry.

## PR 26: Bailian Transport Diagnostics And Minimal Lease Repro

目标：

- 不重跑 full pilot。
- 将问题拆成 endpoint transport 与 official SDK minimal lease repro。
- endpoint diagnostics 不带认证、不调用业务 API。
- minimal lease repro 只执行官方第一步 `ApplyFileUploadLease`，不上传、不 AddFile、不建索引。
- SDK safe error 增加 cause/context/repr/attribute-presence 脱敏字段。

Implemented Phase 6c-sept files:

```text
scripts/rag/bailian_endpoint_diagnostics.py
scripts/rag/bailian_minimal_lease_repro.py
tests/test_bailian_endpoint_diagnostics.py
tests/test_bailian_minimal_lease_repro_safety.py
docs/rag/bailian_transport_diagnostics.md
```

Updated:

```text
review_writer/retrieval/bailian_official_client.py
scripts/rag/bailian_lease_probe.py
Makefile
docs/rag/bailian_error_forensics.md
docs/pr/phase6c_bailian_small_kb_pilot_pr.md
```

Gates:

```bash
make bailian-endpoint-diagnostics-check
make bailian-minimal-lease-repro-dry-run
```

Decision rule:

- Endpoint diagnostics fail: fix WSL/conda/proxy/DNS/TLS.
- Endpoint diagnostics pass but minimal lease fails without request id: inspect SDK endpoint/transport/proxy behavior.
- Minimal lease fails with request id: inspect workspace, permission, category, or request model.
- Minimal lease succeeds: consider one reviewed full pilot retry.

Current result:

- endpoint diagnostics: DNS/TCP/TLS pass
- HTTPS root probe: failed without status code, likely proxy or endpoint-root behavior
- official minimal lease repro: `fail`
- error type: `transport_error`
- exception class: `UnretryableException`
- request id/status code: not present
- no lease obtained, no upload, no knowledge base

Next:

- Investigate conda/SDK proxy transport and SDK endpoint expectations before modifying workspace/category/request assumptions.

### Phase 6c-oct: Bailian SDK proxy / transport matrix

目标：

- 不重跑 full pilot。
- 对 SDK transport 做三模式 matrix：`inherited_proxy`、`no_proxy`、`explicit_proxy`。
- 只执行 lease-only `ApplyFileUploadLease`，不上传、不 AddFile、不建索引、不 Retrieve。
- 通过 introspection 判断 SDK 是否支持 proxy / timeout 字段，而不是猜。

Implemented Phase 6c-oct files:

```text
scripts/rag/bailian_sdk_transport_introspection.py
scripts/rag/bailian_transport_matrix.py
tests/test_bailian_sdk_transport_introspection.py
tests/test_bailian_transport_matrix_safety.py
docs/rag/bailian_sdk_transport_matrix.md
```

Updated:

```text
review_writer/retrieval/bailian_official_client.py
scripts/rag/bailian_minimal_lease_repro.py
Makefile
docs/rag/bailian_transport_diagnostics.md
docs/rag/bailian_error_forensics.md
docs/pr/phase6c_bailian_small_kb_pilot_pr.md
```

Gates:

```bash
make bailian-sdk-transport-introspection
make bailian-transport-matrix-dry-run
```

Decision rule:

- `no_proxy` 成功：代理环境污染 SDK。
- `inherited_proxy` 成功：默认环境可用。
- `explicit_proxy` 成功：SDK 需要显式 proxy/runtime。
- 有 request id 但失败：查 RAM/workspace/category/request。
- 无 request id：继续查 conda/SDK proxy/TLS transport，或走 manual console pilot。

Current result:

- `inherited_proxy`: transport error, no request id.
- `no_proxy`: service reached, request id present, status code `400`, error code `InvalidCategoryType`.
- `explicit_proxy`: transport error, no request id.
- no lease obtained.
- no upload, no AddFile, no index, no Retrieve, no knowledge base.

Next:

- Use `no_proxy` as the service-reaching transport mode.
- Inspect `category_type`, `category_id`, and SDK request-model contract before any full pilot retry.

### Phase 6c-nov: Bailian category discovery / correct category-id lease probe

目标：

- 固定 `no_proxy`，因为它是唯一能到服务端并拿到 request id 的模式。
- 调用只读 `ListCategory`，发现当前 workspace 的 category id/type。
- 用 discovery 推荐类目做一次 lease-only reprobe。
- 不上传、不 AddFile、不建索引、不 Retrieve、不创建知识库。

Implemented Phase 6c-nov files:

```text
scripts/rag/bailian_category_introspection.py
scripts/rag/bailian_category_discovery.py
tests/test_bailian_category_introspection.py
tests/test_bailian_category_discovery_safety.py
docs/rag/bailian_category_discovery.md
```

Updated:

```text
review_writer/retrieval/bailian_official_client.py
scripts/rag/bailian_minimal_lease_repro.py
scripts/rag/bailian_transport_matrix.py
tests/test_bailian_minimal_lease_repro_safety.py
Makefile
docs/rag/bailian_sdk_transport_matrix.md
docs/rag/bailian_error_forensics.md
docs/pr/phase6c_bailian_small_kb_pilot_pr.md
```

Gates:

```bash
make bailian-category-introspection
make bailian-category-discovery-dry-run
```

Decision rule:

- Discovery 有 recommended category：用它做一次 lease reprobe。
- Discovery 没有合适 category：需要在控制台创建或选择文档搜索类目。
- Discovery 失败且有 request id：查权限/workspace。
- Discovery 失败且无 request id：回到 transport。
- Lease reprobe 成功后，才允许 full pilot retry once。

Current result:

- `ListCategory` through `no_proxy` reached service.
- request id present.
- status code `400`, error code `MissingCategoryType`.
- categories_count `0`; no recommended category.
- no lease reprobe executed.
- no upload, no AddFile, no index, no Retrieve, no knowledge base.

Next:

- Confirm valid Bailian `category_type` values for this workspace/API contract.
- Rerun `ListCategory` once with explicit `--category-type`.
- Only if a recommended category is found, run one lease-only reprobe.

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
