# Three-PR Competition MVP Roadmap

Only the next PR is authorized by this roadmap. Later PRs depend on the prior
acceptance evidence and should not start early.

## PR A - Case 01 Product Boundary and Generic Project Entry

Size: `MEDIUM`

User-visible outcome:

> A user can describe a bounded scientific evidence-integration project in one
> case-neutral manifest, validate it offline, and see Case Study 01 represented
> through that same public contract without changing or rerunning frozen Phase
> 8 artifacts.

Must do:

- archive/present the current salvage run as Case Study 01 evidence;
- define the generic project manifest fields audited in
  `PRODUCTIZATION_GAP_AUDIT.md`;
- define normalized product output locations for inventory, claims, evidence,
  conflicts, synthesis, citations, feedback, and run manifest;
- add a Case 01 public manifest/adapter that refers to external artifacts by
  hashes and placeholders, not private paths;
- remove only hardcodes that prevent a second case from entering discovery,
  retrieval-generation, citation rendering, and product accounting;
- keep legacy Phase 8 V2/V3/V3.1/V3.1.1 validators and frozen salvage logic on a
  Case 01-only path;
- add offline contract/portability tests and one case-neutral CLI help path.

Explicitly do not:

- revise the allene synthesis candidate;
- rerun Phase 8A or Qwen;
- generalize the allene taxonomy into a universal ontology;
- add another validator layer;
- build the UI shell, Case 02, or baseline experiment.

Dependencies:

- current clean branch state and frozen Case 01 hashes;
- agreement on the project manifest and normalized output directory names.

Acceptance criteria:

- a synthetic non-allene manifest passes validation without editing code;
- Case 01 can be resolved through its adapter with frozen hashes unchanged;
- active generic entrypoints contain no required `F3I`, `F47A`, `P403`, 44/37/7,
  fixed run ID, or allenation default;
- Case 01-specific schemas/tests still pass;
- no PDF, raw model response, private decision, token, or external absolute path
  is tracked.

Risks:

- accidentally rewriting historical Phase 8 contracts instead of isolating
  them;
- designing an overly broad ontology rather than a small product envelope;
- mixing product schema with source-specific scientific semantics.

Demo evidence:

- `project validate` on Case 01 and one synthetic Case 02-shaped manifest;
- normalized Case 01 artifact index and hash provenance;
- hardcoding inventory diff showing blockers moved out of the generic path.

Likely directories:

```text
review_writer/project/
schemas/project/
scripts/product/
demo_projects/case_01_asymmetric_allene/
tests/
docs/competition/
```

Network or real Qwen: **No**.

Human participation: product-contract review only; no new scientific decision.

## PR B - Case 02 and Three-Arm Baseline

Size: `LARGE`, `HIGH_UNCERTAINTY`

User-visible outcome:

> A second clean-room source set runs through the generic contract, producing a
> traceable comparison table and short synthesis plus a fair Direct Qwen/RAG/
> full-system comparison.

Must do:

- select Case 02 only after open-source/access preflight;
- stage 3-5 sources externally and record source roles/identity;
- run the smallest evidence inventory/verification flow needed by the generic
  contract, without cloning Phase 8A architecture;
- generate the same bounded output under Direct Qwen, RAG, and full-system arms;
- record unsupported numbers, citation mismatch, conflict leakage, locator
  coverage, human edits, rating, calls, tokens, time, and cost;
- produce frozen, redacted demo artifacts and a short findings report.

Explicitly do not:

- process a full review;
- create a large benchmark framework;
- build a domain ontology or knowledge graph;
- claim statistical generalization from two cases;
- publish licensed source text or private review notes.

Dependencies:

- PR A generic manifest/output contract;
- accessible, lawfully usable Case 02 sources;
- explicit approval for bounded network/Qwen/Bailian calls.

Acceptance criteria:

- Case 02 completes without editing generic production code;
- all three arms bind to the same input manifest and target output;
- automatic metrics are reproducible and human metrics retain raw decisions
  privately;
- no unsupported scientific number or source conflict is silently accepted by
  the full-system candidate;
- call/token/time/cost metadata is redacted and complete where available.

Risks:

- source or SI access failure;
- incompatible metrics requiring tighter scope rather than normalization;
- model/API variability;
- insufficient human time for a bounded gold review.

Demo evidence:

- Case 02 source inventory and comparison CSV;
- one locator drill-down and one conflict/missing-field example;
- three-arm metric table and short blinded human assessment;
- redacted Qwen/Bailian invocation manifest.

Likely directories:

```text
demo_projects/case_02_*/
scripts/product/
evals/competition/
tests/
docs/competition/cases/
```

Network or real Qwen: **Yes, bounded and explicitly approved**.

Human participation: source selection, small gold/metric review, and final
candidate acceptance; no large Phase 8-style audit.

## PR C - Integrated Judge Demo and Submission Assets

Size: `MEDIUM`

User-visible outcome:

> A judge can follow one stable local workflow from project question and sources
> to progress, evidence/conflicts, grounded synthesis, feedback diff, API output,
> and reproducibility evidence.

Must do:

- reuse the existing dashboard server and stage/project components;
- add project setup, run status, evidence/conflict, sentence provenance, feedback,
  and diff views;
- document a small read-only test API plus the bounded feedback action used in
  the demo;
- add Case 01/Case 02 selection and three-arm comparison display;
- prepare the <=20-page technical proposal source, redacted invocation evidence,
  10-minute demo script/video assets, and reproducibility instructions;
- make the prepared/replay path independent of live model latency.

Explicitly do not:

- add login, payment, multi-tenancy, production deployment, or a large frontend
  framework migration;
- add new scientific claims or rerun either case unnecessarily;
- make live cloud upload/model success a prerequisite for the presentation.

Dependencies:

- accepted PR A contract and PR B artifacts/metrics;
- final registration/submission portal requirements.

Acceptance criteria:

- a fresh local setup can open both cases and the API without secrets;
- the 10-minute happy path is rehearsed and completes from prepared artifacts;
- every displayed factual sentence can resolve to claims and locators;
- feedback produces a visible diff without overwriting frozen input artifacts;
- the report is <=20 pages and all credentials/screenshots are redacted;
- offline smoke, safety, portability, and demo replay pass.

Risks:

- UI scope creep;
- accidental exposure of source paths or cloud identifiers;
- report/demo drift from actual behavior.

Demo evidence:

- stable local URL and documented test API;
- screen recording following the happy path;
- report PDF, architecture diagram, metrics, and redacted call proof;
- fresh-machine or clean-environment replay record.

Likely directories:

```text
view/
review_writer/project/
scripts/product/
docs/competition/submission/
tests/
```

Network or real Qwen: not required for replay; optional one-shot proof only with
explicit approval.

Human participation: UX rehearsal, report review, screenshot redaction, and
final submission approval.

## Next Action

The only recommended next implementation action is **PR A**. Do not begin Case
02 acquisition, Qwen runs, or UI work until the generic boundary is accepted.

