# Competition MVP Requirements Coverage Matrix

Status vocabulary:

- `COMPLETE_AND_DEMONSTRATED`
- `IMPLEMENTED_NOT_DEMONSTRATED`
- `PARTIAL`
- `CASE_SPECIFIC`
- `MISSING`
- `NOT_NEEDED_FOR_MVP`

The status describes competition-product evidence, not whether a unit test
exists.

| Requirement/capability | Status | Repository or run evidence | Gap/interpretation |
| --- | --- | --- | --- |
| Qwen actual invocation | `COMPLETE_AND_DEMONSTRATED` | Frozen Phase 8B V2 `reports/model_generation_manifest.json`: Qwen 3.7 Max, request count 2, token usage, redacted endpoint, no recorded API key | Needs a submission-safe screenshot or organizer-accepted call credential |
| Bailian invocation | `COMPLETE_AND_DEMONSTRATED` | `docs/rag/bailian_manual_success_record.md:5`; `docs/rag/bailian_retrieval_qa.md:5` | Demonstrated as sanitized pilot, not exposed in product UI |
| Invocation credential/screenshot | `PARTIAL` | Redacted model/capability manifests exist | No competition-form screenshot or final credential artifact |
| Multi-source input | `CASE_SPECIFIC` | Case 01 main papers and SI, Phase 8 source inventory | No generic project/source manifest or upload flow |
| PDF handling | `CASE_SPECIFIC` | External Phase 8 source workspaces and source identity gates; PDFs intentionally untracked (`.gitignore:62`) | No generic product ingestion surface; this audit did not reread PDFs |
| SI handling | `COMPLETE_AND_DEMONSTRATED` | Main/SI roles in `schemas/phase8_source_first_v3_1/source_unit.schema.json:21`; Case 01 includes MAIN/SI identity audit | Schema/task builder remains case-bound |
| Table processing | `CASE_SPECIFIC` | Layer A claim locators support table/scheme/entry fields | No general table-to-CSV product output demonstrated |
| Image/figure processing | `PARTIAL` | Figure inventory/redraw workflow and `view/assets/dashboard/figures.html:43` | Phase 8 evidence images and product dashboard are not connected; no generic chart data extraction demo |
| Source inventory | `COMPLETE_AND_DEMONSTRATED` | `scripts/phase8/build_phase8_review_package.py:179`; public Phase 8A status | Strong Case 01 asset; output path/schema needs product normalization |
| Structured claims | `COMPLETE_AND_DEMONSTRATED` | Phase 8A 44 final records (`docs/phase8/phase8a_status_report.md:10`) | Claim types are chemistry-oriented and execution is case-specific |
| Evidence locator | `COMPLETE_AND_DEMONSTRATED` | Layer B schema `schemas/phase8_source_first_v3_1_1_layer_b/verifier_task.schema.json:44` | No clickable sentence-to-locator viewer in the main dashboard |
| Conflict detection | `COMPLETE_AND_DEMONSTRATED` | Seven retained source conflicts (`docs/phase8/phase8a_status_report.md:12`) | Case 01 only |
| Human feedback | `COMPLETE_AND_DEMONSTRATED` | Append-only decision writer (`scripts/review/record_phase8_decision.py:209`); 10/10 Case 01 budget | Main dashboard does not offer evidence-level Accept/Revise/Flag |
| Correction/version comparison | `COMPLETE_AND_DEMONSTRATED` | Salvage diff and issue reclassification; `review_writer/phase8/phase8b_salvage.py:447` | External artifact only, no integrated viewer |
| Grounded synthesis | `CASE_SPECIFIC` | Phase 8B salvage candidate with 20 sentences, 30 selected claims, zero blockers | Fixed paper IDs, counts, citation map, and section logic |
| Provenance manifest | `COMPLETE_AND_DEMONSTRATED` | External hash manifests and input hashes; salvage manifest binds frozen upstream artifacts | Multiple phase manifests need one top-level product manifest |
| Reproducibility | `PARTIAL` | Offline gates, external hashes, committed schemas/tests | Real source files and private decisions cannot be distributed; no clean-room replay package yet |
| Provider abstraction | `COMPLETE_AND_DEMONSTRATED` | `review_writer/providers/base.py`; 16 provider adapter tests passed in this audit | Product configuration is not linked to a project manifest |
| Test API | `PARTIAL` | Local routes under `view/serve_review_dashboard.py:63`; Phase 8 queue API at `scripts/review/serve_phase8_evidence_review.py:70` | No stable documented competition API for creating/running/reading a project |
| Interactive UI | `PARTIAL` | Eight-stage local dashboard (`view/assets/dashboard/review-ui.js:2`) | No unified input, progress, evidence/conflict, sentence provenance, feedback, and diff flow |
| Demo workflow | `CASE_SPECIFIC` | Tiny, real-lite, clean-three-paper, Phase 7, Phase 8A/B artifacts | No single 10-minute product happy path |
| Second clean-room case | `MISSING` | No non-allene case fixture/run | Required to support generalization claims |
| Direct Qwen vs RAG vs full-system baseline | `MISSING` | Existing evals score artifact health, not the requested three-arm comparison | Run only a small Case 02 experiment |
| Evaluation metrics | `PARTIAL` | `scripts/eval/run_eval_baseline.py:14`; Phase 8 validators | Existing metrics do not report unsupported numbers, citation-paper mismatch, conflict leakage, human edits, time, and cost across arms |
| Technical report materials | `PARTIAL` | Architecture/status/PR notes and new audit documents | No <=20-page competition proposal assembled |
| Demo video materials | `MISSING` | No competition demo script/storyboard/video artifact | Produce after UI and Case 02 stabilize |
| Privacy/secret handling | `COMPLETE_AND_DEMONSTRATED` | `.gitignore:40`; `config/providers.example.yaml:1`; provider manifest says `api_key_recorded=false`; provider/safety tests pass | Add explicit per-project privacy profile and screenshot redaction checklist |
| Failure recovery | `COMPLETE_AND_DEMONSTRATED` | Bounded provider error classification, Phase 8 resumability, deterministic Attempt 2 salvage | Product UI does not expose recovery state |
| Accounts/payments/multi-tenancy | `NOT_NEEDED_FOR_MVP` | No official requirement found | Do not build for the competition MVP |
| Large knowledge graph | `NOT_NEEDED_FOR_MVP` | Direction 1A does not require it | Do not substitute graph scope for the evidence integration product |

## Overall Assessment

The strongest coverage is provenance, exact evidence binding, conflict
preservation, human correction, provider safety, and failure recovery. The
weakest coverage is product entry, second-case proof, integrated interaction,
and comparative evaluation. Those four areas, not additional scientific
validators, determine MVP readiness.

