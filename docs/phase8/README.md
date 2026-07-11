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
```

Local dashboard:

```bash
conda run -n review-writer-phase8 python scripts/review/serve_phase8_evidence_review.py \
  --root local/phase8_evidence \
  --host 127.0.0.1 \
  --port 8787
```

The dashboard binds to localhost only, serves no full-PDF download endpoint, and
appends reviewer decisions to the ignored local workspace.
