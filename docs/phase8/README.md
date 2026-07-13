# Phase 8A Evidence Review Workflow

Phase 8A builds an auditable evidence package for the three selected papers and
the Phase 7 generated section.

Methodology wording:

```text
HUMAN_SPOT_CHECKED_AI_ADJUDICATION
```

This context-isolated three-layer AI adjudication method uses a small human spot
check. It is for engineering validation and internal demonstration, not
publication-grade scientific validation. No item may be described as
`HUMAN_VERIFIED`, `SINGLE_HUMAN_VERIFIED`, `FULLY_VERIFIED`, or
`SCIENTIFICALLY_VERIFIED`.

Allowed Phase 8A statuses are `AI_EXTRACTED`, `HUMAN_REVIEW_REQUIRED`,
`MISSING_SOURCE`, `CONFLICT`, and `UNSUPPORTED_CANDIDATE`. Phase 8A must not
produce verified bibliography, verified claims, gold evidence packs, or a final
scientific evaluation report.

Default gates are offline:

```bash
make phase8-preflight
make phase8-source-inventory-check
make phase8-extraction-check
make phase8-review-package-check
make phase8-dashboard-check
make phase8-decision-writer-check
make phase8-ai-adjudication-check
make phase8-v2-semantic-input-check
make phase8-v3-source-first-check
make phase8-v3-1-source-first-check
```

Current Phase 8A refresh:

- The first three-layer run, V2 run, and audited V3 preparation are retained as diagnostic evidence
  only. V2 completed structural A/B review, but an independent PDF audit found
  that its fixed-field task matrix was not a valid scientific adjudication
  queue. V2 cannot produce scientific AI decisions. V3 received a `NO-GO`
  because its Layer A contract allowed empty completion, broad evidence
  locators, weak semantic binding, and an unscored same-session calibration.
- The 41 V2 tasks form an adversarial task-validation set for safe rejection,
  error categorization, and wrong-value-binding avoidance. Its `NOT_FOUND`
  rate is not a scientific extraction-recall metric.
- `F3I_SI` is represented as `NO_SI_PUBLISHED_ON_OFFICIAL_PAGE`; it is not a
  manual-download blocker for Phase 8A.
- `extended_review_queue` keeps all atomic review items. `core_review_queue`
  keeps the 2-4 hour priority subset and is linked back through
  `core_to_atomic_map.json`.
- Human decision events and AI adjudication events remain in separate ignored
  logs. Effective human decisions take precedence over new AI adjudication,
  which takes precedence over the old extraction.
- Human spot checks are capped at 10 unique core items.

Local dashboard:

```bash
conda run -n review-writer-phase8 python scripts/review/serve_phase8_evidence_review.py \
  --root local/phase8_evidence \
  --host 127.0.0.1 \
  --port 8787
```

The dashboard binds to localhost only, serves no full-PDF download endpoint,
and runs as a read-only evidence viewer in `guided_chat` mode. Confirmed human
decisions are appended separately through the locked, schema-validating writer:

```bash
conda run -n review-writer-phase8 python scripts/review/record_phase8_decision.py \
  record --root local/phase8_evidence --input <confirmed-batch.json> --dry-run
```

The V3 preparation below is retained for compatibility only and must not be
started. V3.1 creates separate scientific and calibration workspaces outside
Git:

```bash
conda run -n review-writer-phase8 python \
  scripts/phase8/prepare_v3_1_source_first.py \
  --evidence-root local/phase8_evidence \
  --workspace-parent <WORKSPACE_PARENT>
```

V3.1 Layer A inventories only atomic evidence actually present in eight source
units: three F3I page shards, F47A main+SI, P403 main, and three P403 SI shards
for methods/mechanism, substrate preparation, and product characterization.
F3I references and P403 routine spectra are excluded. The coordinator-reserved
calibration page is physically absent from the scientific workspace.

Calibration runs in a second workspace and a separate fresh session using the
same core prompt, schema, validator, and finalizer. Its task contains only the
exact source page; its answer and evaluator stay coordinator-private. It is
excluded from the scientific queue and consumes no additional human budget.
Task `search_scope` and claim `evidence_locator` are separate contracts.

Layer B is created only after Layer A output passes strict package, schema,
coverage, uniqueness, task-hash, and source-integrity validation. Layer C may
later receive only material conflicts about the same claim. The isolation is
procedural, not an operating-system sandbox or statistical independence between
model weights. The current checkpoint is
`PREPARED_FOR_SOURCE_FIRST_LAYER_A_V3_1`. Neither Layer A session has started,
Layer B/C do not exist, and Phase 8B has not started.
