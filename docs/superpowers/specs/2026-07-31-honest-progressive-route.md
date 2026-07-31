# Honest Progressive Route

## Decision

Chemical Completion uses one route for every new project: `Honest Progressive
Route` (internal enum `honest_progressive`). Incomplete work may proceed when
its uncertainty is explicit, source-bound, and visible. The
historical v2/Round 2 execution record is retained in the design, plan, and QA
documents, but it is not a fresh v3 gate.

## Fresh v3 Honest Progressive Contract

<!-- FRESH_V3_CONTRACT_START -->

This is the normative contract for every fresh v3 execution. The route never
converts a candidate into a confirmed fact and never uses zero as a substitute
for an unknown or unavailable state.

### Three-state scientific value

Every authoritative molecule row uses exactly one state:

| State | Value | Required evidence | Allowed use |
|---|---|---|---|
| `CONFIRMED` | non-null | PDF locator and researcher confirmation | precise scientific claims |
| `AI_PROVISIONAL` | non-null | PDF locator, confidence, and provenance | explicitly provisional internal views only |
| `BLOCKED` | `null` | non-empty `gap_reason`; locator when available | limitation/gap disclosure only |

`CONFIRMED` is never inferred from an AI candidate. `AI_PROVISIONAL` must keep
its PDF locator, confidence, and provenance. `BLOCKED` must keep
`value=null` plus `gap_reason`. The researcher-safe projection may expose
status, safe locator, confidence, provenance, and gap reason, but never raw
paths, hashes, JSON, MolBlocks, tokens, sessions, or internal IDs. Append-only
history is immutable; actor mismatch is disclosed as provenance residual.

### Fresh v3 initial state

When the fresh project has only verified PDFs and fresh Generic current, with no
authoritative Chemical cohort yet:

- `availability/status` is `unknown/unavailable`, never `ready/current`;
- `core_denominator`, `confirmed_count`, `ai_provisional_count`,
  `blocked_count`, `coverage_ratio`, `coverage_sufficient`, and `gap_registry`
  remain unknown/null; none is compressed to `0` and no empty `gap_registry`
  is fabricated;
- the only next action is `待 Chemical Paper 导入`; after the first approved ZIP
  has completed safe preflight and awaits confirmation, the only next action is
  `确认第一份 Chemical Paper 导入`;
- credits are displayed only as `NOT_APPLICABLE_BY_CURRENT_SCOPE`.

No new next action is allowed to compete with those labels. `gap_registry` is
created only after authoritative molecule rows exist.

### Formal Chemical import and v3 counting

Only after all three approved Chemical inputs have completed formal
preflight/confirm/import and are `3/3 current` may the server validate pages
`6/11/11`, molecule counts `125/109/75` (project total `309`), and
`reaction_data_status=unavailable_not_provided`. At that point, and only when
authoritative molecule rows exist:

```text
project_denominator = 309
coverage_ratio = (confirmed_count + ai_provisional_count) / 309
coverage_threshold = 0.8
coverage_sufficient = server_calculated(coverage_ratio >= coverage_threshold)
```

The server calculates all counts, denominator, ratio, threshold, and
`coverage_sufficient`; client-supplied counts are untrusted. Missing reaction
data remains `unavailable_not_provided`, never zero.

For the approved-inputs fresh-v3 audit snapshot, the authoritative projection
is `CONFIRMED=0`, `AI_PROVISIONAL=210`, `BLOCKED=99`, so covered rows are
`210/309 = 0.6796116505`. The threshold target is
`ceil(309 * 0.80) = 248`; therefore this snapshot needs **38 additional
traceable candidates** before `coverage_sufficient` can become true. The
per-study slices are ANIE `78/125`, ACS Catalysis `80/109`, and JACS `52/75`;
the project gap registry contains exactly `99` BLOCKED rows. These values are
server-derived audit evidence, not a permission to fabricate or backfill
values; every later change must be append-only and recompute the same formula.

Approved ZIPs enter only through the formal preflight → confirm → importer
path. Never hand-unzip them, use a v2 Generic ZIP, or reuse old Generic
outputs. ZIP/PDF binding and path/hash evidence are Coordinator-only and never
enter Dashboard or Researcher projections.

A current Generic Parse gate may be `approved_with_pdf_locator`: this keeps
automatic Generic extraction fail-closed while still permitting the current
PDF-bound Chemical lane and reconciliation to proceed. It must never be
treated as automatic extraction approval.

### Progressive continuation and role sequence

Honest Progressive permits incomplete work but never permits opaque work. Below
80%, source/evidence preparation may continue with an explicit
`needs_more_traceable_candidates` state; no scientific approval may be
fabricated or silently upgraded.

The Researcher makes visible PDF-bound decisions and supplies confirmation for
`CONFIRMED`; the Coordinator audits binding, path/hash, formal-import, safe-
projection, and gap evidence read-only; the Integration Owner owns Task 10
fresh bootstrap, formal preflight/confirm/import, safe projection, runtime
readiness, and protocol restarts. Only after formal import, safe projection,
and runtime readiness are complete may Task 11 create a new Playwright
Researcher. Content Agents remain candidate-only and study-local.

### Researcher-safe fields

```text
resolved_smiles_status
resolved_smiles
confidence
provenance
gap_reason
actor_provenance_residual
```

<!-- FRESH_V3_CONTRACT_END -->

## Consumer rules

- Evidence and synthesis may consume `CONFIRMED` for exact claims.
- `AI_PROVISIONAL` may be consumed only by explicitly provisional internal
  views and must retain its confidence/provenance label.
- `BLOCKED` is excluded from exact structure claims and is emitted in the
  limitation/gap registry.
- After formal v3 import, release and benchmark reports show denominator,
  confirmed, provisional, blocked, per-study coverage, traceability, and
  uncertainty disclosure. Before that import they preserve unknown/unavailable
  values rather than rendering zeros.
- Credits remain `NOT_APPLICABLE_BY_CURRENT_SCOPE` when the route does not
  measure credits; missing ledgers are not interpreted as zero.

All user-facing route labels and reports say `Honest Progressive Route`.
Unrelated validator parameters retain their own technical meaning and are not
route names.
