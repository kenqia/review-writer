# Deliverable-First Core Contract

Status: ACTIVE_AND_HASH_BOUND

Adopted: 2026-08-03

Scope: every local review-writer session, work package, handoff, review, and
artifact decision until a newer explicit user instruction supersedes it.

## 0. 用户价值第一

本项目的一切技术选择都必须先回答用户问题：用户少做了什么、看懂了什么、
获得了什么更可靠的结果，以及遇到失败时能否知道如何恢复。报告只从用户角度
叙述；分支、代理、commit、测试和内部架构只能作为验证证据，不能替代用户结果。
默认读者是懂基础软件工程但不深入的学生，不把内部复杂度转嫁给用户。没有直接
改善用户结果、信任或可恢复性的工作，必须停车、合并为更小的实现，或删除。

## 1. The two outcomes that authorize work

This project exists to produce the strongest defensible chemistry review that
the bounded corpus can support. Its first outcome is a manuscript that
approaches a gold-standard review: it answers the declared Review Questions,
compares studies fairly, grades mechanistic evidence, exposes limits and
conflicts, and never turns unsupported text into a fact.

Its second outcome is trustworthy traceability. A researcher must be able to
move from a manuscript conclusion to its claim, the relevant decision, the
supporting evidence, and the exact hash-bound PDF location without relying on
model memory, a dashboard assertion, or a stale derived file.

Everything else is subordinate. Work that cannot improve one of these outcomes
is not neutral overhead; it is prohibited.

Gold standard does not mean publication acceptance, a fabricated expert review,
or 100% certainty. It means the best auditable, bounded, and candid synthesis
the available evidence justifies.

## 2. Authority and required session read

For active Deliverable-First work, resolve authority in this order:

1. the latest explicit user instruction;
2. repository AGENTS.md;
3. this Core Contract;
4. immutable Approved Spec constraints that protect scientific correctness,
   source integrity, safety, and the declared deliverable;
5. older continuation documents, execution authority records, finding
   inventories, handoffs, branches, and chat summaries as reference evidence
   only.

No lower item may revive work, become a sole next action, relax a gate, or
change a priority merely because it was once recorded as the next action.

Before a session writes, reviews, dispatches, or adopts inherited work, it must:

1. verify the hash-bound core manifest;
2. read AGENTS.md and this file;
3. read the immutable Approved Spec sections affected by the task;
4. inspect current Git state; and
5. record the task's admission decision below.

The manifest binds this contract, AGENTS.md, the immutable Approved Spec, and
the priority pointer. A hash mismatch is a stop for the affected authority
pack, never a reason to silently use a convenient old copy.

## 3. Task admission: measurable contribution or no task

Every bounded task must declare both fields before it starts:

    BASELINE=
    TARGET=
    AFFECTED_DELIVERABLE=
    GOLD_DELTA=
    TRACE_DELTA=
    DIRECT_TARGET=
    MEASUREMENT_OR_ARTIFACT=
    STOP_LINE=

GOLD_DELTA is present only when the task has a measurable path to one or more
of the following:

- a more complete or more accurate answer to a declared Review Question;
- a better grounded cross-paper comparison, including explicit comparability
  boundaries;
- stronger mechanism-evidence grading, conflict treatment, or limitation
  disclosure;
- fewer unsupported or overstated manuscript claims;
- a demonstrably improved result against the approved review-quality rubric.

TRACE_DELTA is present only when the task measurably improves the reachable
chain from claim to decision to evidence to hash-bound PDF locator, including
identity, version, provenance, auditability, or reproducibility.

A delta may be DIRECT, or ENABLING only when it names the direct bounded task it
unblocks and expires when that direct task is stopped. Otherwise it is NONE. If
both fields are NONE, do not start. Do not count tests, agent volume, generic
abstractions, dashboard activity, token use, or process ceremony as a delta by
themselves.

At completion, the task must show the stated measurement or artifact. If it
cannot, its result is a documented non-improvement rather than a reason to
broaden scope.

BASELINE and TARGET must make the proposed change falsifiable, and
AFFECTED_DELIVERABLE must name the Paper Evidence Card, matrix, claim, audit,
manuscript, export, or manifest it changes. A task without all three is not
admitted merely because its intent sounds useful.

## 4. The irreducible truth chain

The minimum sources of truth are exactly:

1. Source Manifest;
2. Paper Evidence Cards;
3. Claim and Decision Ledger, including the Claim-Evidence Registry and the
   Researcher Decision Ledger;
4. five Review-Question Synthesis Matrices;
5. one authoritative manuscript;
6. Gap Registry; and
7. Artifact Manifest.

They form the only permitted path to a material conclusion:

    Source Manifest and PDF hash
      -> Paper Evidence Card
      -> Claim and Decision Ledger
      -> Review-Question Synthesis Matrix
      -> authoritative manuscript
      -> Gap Registry and Artifact Manifest
      -> DOCX and PDF

Every edge must preserve stable identifiers and freshness. A material claim is
writing-eligible only if an audit can mechanically traverse all of these fields:

    Claim ID
      -> decision and state
         (real researcher decision, AI_PROVISIONAL, or BLOCKED)
      -> Evidence ID
         (MAIN or SI; page plus section/table/figure locator;
          excerpt hash and locator hash; evidence type and limitations)
      -> source PDF SHA-256 and document role

A missing edge makes the material claim BLOCKED. The workflow must then
downgrade it to a limitation or exclude it from factual prose, record the gap,
and continue every independent task. A dashboard value, raw parse, retrieval
result, or candidate citation cannot stand in for an edge in this chain.

Traceability is bidirectional. From a source/PDF version, the audit must list
every dependent Evidence Card, decision, claim, matrix cell, manuscript
location, and export artifact. From a material claim, the audit must walk back
to the exact source/version and locator. A source, parse, or source-version
change makes every dependency stale until it is re-audited; stale support is
not writing-eligible.

The five Review-Question Synthesis Matrices are mandatory and current only when
each answer/cell carries one of SUPPORTED, COUNTER_EVIDENCE, NON_COMPARABLE,
NOT_REPORTED, NOT_APPLICABLE, or BLOCKED. Each matrix retains its denominator,
counter-evidence, outliers, heterogeneity/comparability conditions, mechanism
evidence level, and applicability boundary. It must not collapse absence,
conflict, or non-comparability into a positive aggregate conclusion.

Each of the five matrices must disposition every study in the frozen Source
Manifest exactly once for that Review Question. NOT_APPLICABLE requires a
recorded reason. The examined set is the complete frozen study-ID set, and every
reported denominator is mechanically derived from those complete dispositions,
never entered as an unsupported manual count. When the examined set contains
no counter-evidence, record NONE_FOUND_IN_BOUNDED_CORPUS together with the exact
examined_set; never write an unbounded claim that no counter-evidence exists.

Every material claim also records one executable epistemic level and uses only
the corresponding language:

1. EXPERIMENTAL_OBSERVATION: a directly reported result under named conditions.
   Allowed language is limited to reports, observes, or measured under those
   conditions.
2. AUTHOR_INTERPRETATION_OR_PROPOSED_MECHANISM: the source authors' explanation
   without sufficient direct support. Attribute it explicitly with propose,
   suggest, or interpret; never restate it as an established mechanism.
3. EXPERIMENTALLY_SUPPORTED_MECHANISM: named experiments support a mechanism
   with recorded alternatives and limitations. Use supports or is consistent
   with under the tested conditions, not proved or universally causal.
4. CROSS_STUDY_SYNTHESIS_OR_UNRESOLVED: a synthesis over the explicitly
   comparable examined set. Use converges across the examined set only when
   support and counter-evidence are dispositioned; otherwise state mixed,
   heterogeneous, non-comparable, or unresolved.

The words proved, causal, general, superior, and consensus are prohibited unless
the claim has a comparable multi-study set, complete counter-evidence
disposition, and a current real-researcher decision authorizing that exact
language. Without all three, the claim must use the qualified/provisional
language above or remain BLOCKED.

Claim strength must never exceed evidence strength. The claim/source audit
reports evidence-strength mismatches, and the required mismatch count is zero.

The Artifact Manifest must bind all input PDFs, the authoritative manuscript,
and the derived DOCX and PDF to their hashes and stable artifact identities. The
DOCX and PDF must derive from the same authoritative manuscript.

## Gold calibration gate and maturity labels

These labels are strict and must not be used interchangeably:

- GENERATION_CAPABLE: text can be generated; it establishes neither traceability
  nor scientific readiness.
- TRACEABLE_DRAFT: every material claim is linked through the truth chain and
  uncertainty is disclosed; it is not yet a gold-calibrated or
  researcher-authorized release.
- GOLD_CALIBRATION_PASS: an independent reviewer has verified all of the
  following for the authoritative artifact:

      total >= 90
      evidence_fidelity >= 18/20
      synthesis_and_critique >= 18/20
      source_set_coverage >= 13/15
      citation_and_traceability = 10/10
      every other required dimension >= 80%
      hard_fails = []

- RESEARCHER_AUTHORIZED_RELEASE: a real qualified researcher explicitly
  authorized the exact, hash-bound artifact after it reached the required
  traceability and calibration state. It is not created by AI, a simulated
  actor, an automated gate, or a self-reviewed draft.

For a GOLD_CALIBRATION_PASS, the independent reviewer records the rubric
rationale, representative supported examples, misses, hard-fail result, and
the reviewed artifact hash. Gold Gap Registry remediation is limited to two
focused rounds; after that, preserve the unmet label and stop rather than
rewriting indefinitely.

## 5. Scientific state and honest limits

The only molecular and material-claim states are CONFIRMED, AI_PROVISIONAL, and
BLOCKED.

CONFIRMED requires uniquely supporting original MAIN/SI evidence and an
explicitly recorded decision by a real qualified researcher. AI or Sol may
produce a provenance-bearing recommendation, AI_PROVISIONAL candidate, or
needs_researcher_decision record; it must never create a real researcher
decision, CONFIRMED state, external-expert review, or a statement that a human
accepted the result. This is a stricter safeguard, not a relaxation of the
Approved Spec.

AI_PROVISIONAL must remain visibly unconfirmed and retain its actor, timestamp,
locator, provenance, confidence, and freshness. BLOCKED has value=null and
retains the precise gap reason. A simulated actor remains explicitly simulated.

Never guess a SMILES string or other structure. Never use an R-group, wildcard,
label, syntactic validity, common knowledge, or plausible analogy to turn an
unknown structure into a precise fact. Never overwrite a valid confirmation
without recorded authority.

Precise manuscript claims whose structure dependencies are not CONFIRMED must
be downgraded, excluded, or remain blocked.

## 6. Unattended execution without dishonest bypasses

The user sleeping is not a reason to create artificial waiting loops, repeated
approval prompts, or a false manual blocker. Continue all independent work.

When a real qualified researcher decision is genuinely unavailable, preserve
the affected material claim as BLOCKED or a stated limitation, record the
affected object and unique recovery action, and complete every independent
evidence, synthesis, drafting, audit, or export step that remains safe. Do not
manufacture confirmation merely to keep a pipeline moving.

At a terminal blocker, report the factual state, completed independent work,
remaining gap, and one recovery action. Do not present a blocked result as
submission-ready.

## 7. Deliberate execution shape

Work proceeds only along the shortest evidence-to-deliverable path:

1. establish the bounded, hash-bound corpus and source identity;
2. produce and audit one Paper Evidence Card per study, with a disposition for
   every study;
3. preserve real researcher decisions and conservative AI/gap records;
4. synthesize independently by declared Review Question from current evidence;
5. let exactly one manuscript writer create the authoritative draft;
6. run claim/source, coverage, uncertainty, benchmark, export, and artifact
   audits against that one draft.

Model routing is fixed unless a newer explicit user instruction changes it:

- 5.6 sol max: simulated/recommendation work, independent scientific review,
  gold-standard or rubric review, scientific conflicts, and other high-risk
  scientific judgment;
- 5.6 luna max: per-paper evidence processing, structured extraction,
  synthesis execution, manuscript-support work, merge/polish, and ordinary QA.

The total live concurrency is at most min(4, available Codex concurrency). The
Coordinator stays light and owns only current-state integration. Parallel paths
must have disjoint artifact ownership. There is exactly one authoritative
manuscript writer; a reviewer is fresh and read-only and cannot approve its own
work or write its repair.

An immutable task receives at most two attempts. A reviewer works only within
its assigned stop line and cannot add a new threat model to keep the work alive.
On attempt two, record the exact blocker or park the work; do not form a
recursive Reviewer/Repair tree.

## 8. Frozen work and parked history

The following are frozen unless a proposed, bounded change passes a direct
GOLD_DELTA or TRACE_DELTA test and is the smallest way to remove a current
deliverable blocker:

- scheduler platformization or a general orchestration framework;
- recursive Reviewer/Repair trees and historical-branch repair campaigns;
- Dashboard/UI work with no direct manuscript or traceability value;
- generic schema, DAG, provider, plugin, event, or workflow-engine expansion;
- open-ended security audits;
- infrastructure built mainly for future development convenience;
- inherited P0/P1/P2 findings whose only support is the old next-phase
  continuation path.

All inherited items are PARKED_REFERENCE_ONLY. An old P1 may be reconsidered
only when a current material-claim audit proves that it repairs a missing truth
chain edge. It then needs current evidence, an explicit delta, a fixed stop
line, and no widening of its threat model.

## 9. Acceptance language and handoff discipline

No result may claim gold standard, ready, expert reviewed, or submission
readiness merely from automation. The handoff must distinguish:

- what the corpus and audits directly establish;
- what the current evidence supports in the manuscript;
- what is AI_PROVISIONAL or BLOCKED;
- which decisions are simulated versus real researcher decisions; and
- which exact files, hashes, locators, and artifacts make the conclusion
  reproducible.

Each handoff names the current commit and parent, clean/dirty state, manifest
result, admission fields for the next task, completed measurable deltas,
blockers, and the sole next shortest-path action. It never reactivates legacy
work merely because it is available.

## 10. Non-waiver

This contract narrows work toward the final review; it does not authorize
remote writes, push, deployment, publication, corpus substitution, sensitive
data exposure, destructive Git commands, or any downgrade of immutable
scientific and safety constraints.
