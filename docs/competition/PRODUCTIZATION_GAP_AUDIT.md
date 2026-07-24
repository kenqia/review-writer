# Competition Productization Gap Audit

## Executive Verdict

The project has a credible technical core and a strong deep case, but it is not
yet a competition-ready product. The immediate need is not another validator or
more allene prose. It is a generic project boundary, a second clean-room case,
and one coherent demo surface.

## Strongest Three Completed Assets

1. **Traceable evidence and provenance.** Phase 8A completed source-first
   inventory, exact-claim verification, deterministic reconciliation, immutable
   external artifacts, and hash manifests (`docs/phase8/phase8a_status_report.md:7`).
2. **Conflict/error handling rather than silent synthesis.** Seven source-
   internal conflicts were retained, locator/stage/entity errors were corrected,
   and unsupported synthesis can block prose (`docs/phase8/phase8a_status_report.md:9`).
3. **A real domestic-model path with deterministic feedback correction.** The
   frozen V2 manifest records a real Qwen 3.7 Max call through Alibaba's
   OpenAI-compatible endpoint; the salvage pass reused the frozen response,
   made no model request, and reached zero blockers.

## Top Five MVP Gaps

| Priority | Gap | Evidence | Why it blocks MVP | Minimum response |
| --- | --- | --- | --- | --- |
| P0 | No generic project input/output contract | Repository search found no integrated fields for `research_question`, `source_files`, `output_language`, `citation_style`, `human_review_policy`, or `privacy_policy` | A new user/case cannot be configured without knowing internal Phase paths | Introduce a project/case manifest and normalize outputs without changing Phase 8 scientific logic |
| P0 | Executed generation and Phase 8B code is case-bound | `review_writer/pipeline/retrieval_generation.py:12`, `review_writer/phase8/phase8b_grounded_revision_v2.py:18`, `review_writer/phase8/phase8b_salvage.py:24` | Different paper IDs/counts/section fail before scientific work starts | Move Case 01 constants into its manifest/adapter; keep frozen audit code as legacy case logic |
| P0 | No second clean-room case or comparative baseline | Demo roots, retrieval questions, and eval fixtures are all allene-specific | Generality and competition value are asserted, not demonstrated | Run one 3-5 source non-allene case and compare Direct Qwen, RAG, and full system |
| P1 | UI/API capabilities are fragmented | Generic stage dashboard at `view/serve_review_dashboard.py:39`; Phase 8 viewer at `scripts/review/serve_phase8_evidence_review.py:66` | Judges cannot follow one stable input-to-evidence-to-diff flow | Add a light demo shell that reads existing artifacts and exposes project, progress, evidence/conflict, synthesis, feedback, and diff |
| P1 | Competition evidence package is incomplete | Real call manifests and engineering reports exist, but no 20-page proposal, redacted invocation screenshot, demo script/video, or test API contract exists | Official delivery completeness is a scoring dimension | Assemble competition-specific report/demo artifacts after PRs A and B provide stable evidence |

## Generic Input Contract Audit

| Input | Current location | Run evidence | Case binding | Code change needed for Case 02 | Minimum repair |
| --- | --- | --- | --- | --- | --- |
| `project_name` | No integrated field | None | N/A | Yes | Required project manifest field |
| `research_question` | Topic text exists in demo projects, not as a runtime contract | Demo topic files only | High | Yes | Required field passed to discovery, extraction, and synthesis |
| `domain` | Metadata and skill prose use domain concepts | Partial | Chemistry/allene default | Yes | Optional controlled string; select an explicit rule pack only when needed |
| `source_files` | Paths are spread across metadata, registry, and Phase 8 source inventory | Real in Case 01 | High | Yes | Manifest list with stable source IDs and relative/external references |
| `source_roles` | Phase 8 V3 schemas support MAIN/SI (`schemas/phase8_source_first_v3_1/source_unit.schema.json:21`) | Real | IDs and page counts fixed | Yes | Lift role vocabulary into case-neutral source records |
| `output_language` | No integrated field | None | English assumed in prompts | Yes | Manifest enum/string passed to synthesis |
| `citation_style` | Numeric citations are assumed | Case 01 real | High | Yes | Manifest field plus deterministic renderer |
| `review_scope` | V3 source unit has a prose scope | Real | Phase/case-specific | Yes | Project-level and task-level scope fields |
| `provider` | `config/providers.example.yaml:7` and provider adapters | Real Qwen and offline runs | Low | No core rewrite | Reference provider profile from project manifest |
| `human_review_policy` | Phase 8 has a fixed 10-item budget | Real Case 01 | High | Yes | Policy object; Case 01 retains its frozen budget |
| `privacy_policy` | Safety is configured/documented, not a project input | Real gates, no per-case selection | Medium | Yes | Named policy profile controlling upload/network/source retention |

## Standard Output Contract Audit

| Output | Existing evidence | Status | Minimum normalization |
| --- | --- | --- | --- |
| `source_inventory/` | `local/phase8_evidence/inventories/` and public status summary | Case-specific, demonstrated | Stable case-neutral directory and schema |
| `claims/` | V3.1.1 Layer A/B and final reconciled claim JSONL | Case-specific, demonstrated | Export final claim records behind a generic claim contract |
| `evidence/` | Structured `evidence_locator` and short evidence | Case-specific, demonstrated | Artifact resolver independent of fixed source IDs |
| `conflicts/` | Seven retained structured source conflicts | Case-specific, demonstrated | Generic conflict collection/view |
| `synthesis/` | Phase 7 section and Phase 8B salvage revision | Case-specific, demonstrated | Generic section request/result and status |
| `citations/` | Salvage citation map | Case-specific, demonstrated | Build from manifest sources, not fixed paper map |
| `feedback/` | Human decision writer and salvage diff | Fragmented | Connect bounded feedback events to synthesis version |
| `run_manifest/` | Multiple hashed external manifests | Demonstrated but phase-specific | One top-level manifest linking stage manifests |

## Can a Second Case Run Without Core Code Changes?

No. Provider and retrieval interfaces are reusable, but the executed pipeline
filters new paper IDs (`review_writer/pipeline/retrieval_generation.py:157`), the
default taxonomy is allene-specific (`skills/review-topic-paper-discovery/SKILL.md:25`),
the blueprint defaults to the allenation rule pack
(`skills/review-section-blueprint/references/rule_packs.json:2`), and Phase 8B
requires exactly 44 claims and seven conflicts
(`review_writer/phase8/phase8b_grounded_revision_v2.py:136`).

## What Case 01 Should Become

- Preserve frozen Phase 8A and Phase 8B runs as audit evidence.
- Add a public case manifest that names inputs, source roles, question, output
  scope, frozen hashes, and demonstrated checkpoints without publishing source
  text or private decisions.
- Treat Case 01 IDs, counts, and allene rule packs as fixtures/adapters.
- Route a generic product entrypoint around those fixtures; do not rewrite or
  generalize the frozen V3/V3.1/V3.1.1 validators.

## Work To Stop Immediately

- Further polishing of the representative allene section before user review.
- Re-running or redesigning Phase 8A.
- Adding another validator layer.
- Expanding to the full review.
- Copying Phase 8A wholesale for Case 02.
- Building accounts, payments, multi-tenancy, a large knowledge graph, or a
  complex SaaS deployment.
- Claiming broad cross-domain generalization or a complete AI Scientist.

## Answers Required For Go/No-Go

1. **What is the product?** A chemistry-oriented review/evidence system with one
   deeply demonstrated evidence-grounding case, moving toward a reusable
   multi-source evidence integration product.
2. **Best track?** Track 2, Direction 1A, marked
   `RECOMMENDED_TRACK_PENDING_REGISTRATION_CONFIRMATION`.
3. **Strongest assets?** Provenance ledger, independent verification/conflict
   retention, and real Qwen plus deterministic feedback correction.
4. **Top gaps?** Generic contract, case hardcoding, second case/baseline,
   integrated demo UI/API, and competition deliverables.
5. **Allene case role?** `Case Study 01 - Asymmetric Allene Chemistry`.
6. **Blocking hardcodes?** Fixed paper/source IDs, fixed 44/37/7/10 counts,
   fixed citation map/section, allene taxonomy/default rule pack, and frozen run
   IDs in active entrypoints.
7. **Recommended second case?** MOF atmospheric water-harvesting performance
   integration, subject to open-source artifact preflight.
8. **Enough UI/API foundation?** Enough to reuse, not enough for a coherent judge
   demo. A light shell is needed; a full rewrite is not.
9. **Minimum baseline?** One source set and question, three arms (Direct Qwen,
   RAG, full system), with automatic provenance/error metrics and a small blinded
   human review.
10. **Three PRs?** Generic case boundary, Case 02 plus baseline, then integrated
    demo and competition assets.
11. **What stops now?** Additional Case 01 science/validators/full-review work.
12. **Only next PR?** PR A: Case 01 packaging plus a generic project/case manifest
    and removal of hardcodes that prevent Case 02.
