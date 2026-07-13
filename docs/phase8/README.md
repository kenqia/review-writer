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
```

Current Phase 8A refresh:

- The first three-layer run and V2 run are retained as diagnostic evidence
  only. V2 completed structural A/B review, but an independent PDF audit found
  that its fixed-field task matrix was not a valid scientific adjudication
  queue. V2 cannot produce scientific AI decisions.
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

The offline V3 preparation command validates and freezes V2, then creates one
source-first Layer A workspace outside Git:

```bash
conda run -n review-writer-phase8 python \
  scripts/phase8/prepare_v3_source_first.py \
  --evidence-root local/phase8_evidence \
  --workspace-parent <WORKSPACE_PARENT>
```

V3 Layer A inventories only atomic evidence actually present in three source
units: F3I, F47A main+SI, and P403 main+SI. It does not generate claims from a
fixed field matrix. One opaque exact-page unit executes the existing human gold
under the same schema and prompt; its answer remains coordinator-private and is
excluded from the scientific queue.

Layer B is created only after Layer A output passes strict package, schema,
coverage, uniqueness, task-hash, and source-integrity validation. Layer C may
later receive only material conflicts about the same claim. The isolation is
procedural, not an operating-system sandbox or statistical independence between
model weights. Phase 8B has not started.
