# Phase 8A Evidence Review Workflow

Phase 8A builds a human-review-ready evidence package for the three selected
papers and the Phase 7 generated section.

Methodology wording:

```text
AI-assisted pre-extraction followed by single-human verification.
It is not independent dual-human data extraction.
```

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
```

Current Phase 8A refresh:

- `F47A_SI` and `P403_SI` are local, ignored PDF sources with identity
  validation records in the local inventory.
- `F3I_SI` is represented as `NO_SI_PUBLISHED_ON_OFFICIAL_PAGE`; it is not a
  manual-download blocker for Phase 8A.
- `extended_review_queue` keeps all atomic review items. `core_review_queue`
  keeps the 2-4 hour priority subset and is linked back through
  `core_to_atomic_map.json`.

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
