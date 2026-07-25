# Product Leader Current Handoff

Status: `CURRENT_APPROVED_PRODUCT_DIRECTION`

Last verified: 2026-07-19 Asia/Shanghai

## Product North Star

Build a chemistry-first, case-neutral, evidence-governed review workbench. One
user supplies a research question and papers/SI, reviews the work repeatedly at
material decisions, and ultimately hands an expert one clean DOCX whose
important scientific claims remain traceable to approved evidence.

The canonical product definition is
[PRODUCT_NORTH_STAR.md](../product/PRODUCT_NORTH_STAR.md). The canonical
implementation order is [PRODUCT_ROADMAP.md](../product/PRODUCT_ROADMAP.md).

## Verified repository context

- Local worktree branch at this handoff: `snapshot/pre-provider-qualification-20260716`.
- Baseline HEAD at this handoff: `6e6d53bc782c1fb879e3c203670da9d95cd3ad0d`.
- No current PR number or remote branch state is asserted by this handoff.
- Existing eight-stage orchestration remains the execution skeleton.
- Fifteen logical review checkpoints are governed by the unified
  [CheckpointContract](../product/CHECKPOINT_CONTRACT.md); they do not imply
  fifteen mandatory clicks or multiple reviewers.

## Accepted product decisions

- Product boundary: chemistry-first, case-neutral, bounded-corpus, and
  offline-first; not cross-domain, fully autonomous, or fully offline by claim.
- Operator model: one user, repeated human checkpoints. A self-review is never
  described as independent expert review.
- Final user-facing artifact: one clean DOCX. Audit and evidence products remain
  internal side artifacts.
- Authority: the Approved Claim Registry is the fact authority; Approved Claim
  RAG is a derived retrieval index. Evidence Discovery RAG cannot write facts
  directly into the clean manuscript.
- Scientific disagreement: preserve it as `ConflictRecord`; supported disputes
  may appear only as attributed, non-definitive unresolved controversies.
- Mutations: user edits are immutable revision events bound to base artifact
  hashes, with optimistic concurrency, three-way diff, and explicit downstream
  invalidation.
- Releases: release records are immutable. A new DOCX hash creates a new
  release candidate and cannot mutate or downgrade an earlier expert release.
- UI: reuse the Python plus HTML/CSS/JS localhost dashboard, support `zh-CN` and
  `en`, and expose only the current or affected checkpoint task. Exact visual
  style and checkpoint timing remain subject to later UX review.

## Current scientific case state

- Case 01 v4 remains frozen and must not be modified.
- Its independent AI and page-visual pre-review remains advisory. It does not
  create scientific acceptance or an `EXPERT_REVIEWED_RELEASE`.
- The user-supplied full-text critique is an interim delegated review input for
  v5 planning, not a substitute for the later external chemistry-expert review.
- Case 01 v5 is approved as a structural rewrite and golden calibration:
  a narrow two-study comparative perspective, 3,500-4,000 English words,
  seven sections, three original redraws, one compact three-column comparison
  table, and bracketed numeric citations.
- v5 may reread the existing three MAIN/SI source sets to repair evidence for
  the approved scope. It must use the correct P403 hashes:
  - MAIN: `8fbc8f252952b8cca4f8f25084ee0e9067144b66366f96bee1aa09952f6da7e1`
  - SI: `9c0549eb99dfe84649de5a75306a257118560d99148e9a0e957ced7f4ef0ec2e`
- The wrong quarantined JACS parse/hash beginning `9720ece6` remains forbidden
  evidence and must never be promoted into v5.

## Current milestone order

1. **M0 - Product and Checkpoint Contract:** validate the minimum editable
   manifest, immutable snapshots/closures, case-neutral entry, synthetic
   non-allene path, and read-only frozen Case 01 adapter.
2. **M1 - Case 01 v5 Golden Calibration:** exercise the generic contract, the
   minimum bilingual checkpoint UI, and one Windows-native QoderWork CN flow
   using `qwen3.7-max` under the approved provider boundary.
3. **M2 - New 20-40 Paper Chemistry Review:** prove the large-review path with
   a new topic and no new topic-specific production code.
4. **M3 - Product Hardening:** make proven behavior simple to install, recover,
   repeat, and evaluate.

## Immediate stop rules

Do not:

- modify frozen Case 01 v4 artifacts;
- add new Case 01-only validators or rerun Phase 8A;
- start the new 20-40-paper review before the M1 vertical slice is stable;
- add providers, a universal ontology, accounts, deployment, or a frontend
  framework rewrite;
- claim publication readiness, independent expert review, cross-domain
  generality, or AI Scientist capability;
- push, open/merge a PR, publish, or deploy without explicit authorization.

## Next implementation decision

Resume at M0: turn the accepted CheckpointContract and North Star into the
smallest case-neutral project/artifact contract slice, with a synthetic
non-allene fixture and a read-only Case 01 adapter. Do not start scientific v5
generation until that slice has fresh offline acceptance evidence.

After M0 human acceptance, stop horizontal infrastructure work and prepare the
separately approved M1 vertical run. Its first runtime gate is hash-bound
evidence -> human-approved claims -> one real model API section draft ->
citation/evidence validation -> human review. Provider, transmitted content,
request budget, M1 scope, and Owner require explicit approval before execution.
If the gate passes, continue the complete v5 DOCX inside the same M1. Model text
remains a draft and never self-approves scientific facts.
