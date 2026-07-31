# Honest Progressive Route

## Decision

Chemical Completion no longer has separate strict and exploratory gates. Every
project uses one `honest_progressive` route: incomplete work may proceed when
its uncertainty is explicit, source-bound, and visible.

The route never converts a candidate into a confirmed fact. It carries the
three-state status on every core molecule:

| State | Value | Required provenance | Downstream eligibility |
|---|---|---|---|
| `CONFIRMED` | non-null | PDF locator and researcher confirmation | precise scientific claims |
| `AI_PROVISIONAL` | non-null | PDF/structure-figure locator, confidence, and provenance | internal tables, grouping, trends, candidate discussion only |
| `BLOCKED` | `null` | gap reason; locator when available | limitation/gap disclosure only |

The researcher-safe projection uses these fields:

```text
resolved_smiles_status
resolved_smiles
confidence
provenance
gap_reason
actor_provenance_residual
```

`provenance` must not expose raw paths, hashes, JSON, MolBlocks, tokens, or
sessions. Existing append-only history is immutable. An actor mismatch is
represented by `actor_provenance_residual=true`; it is disclosed, not repaired
by rewriting history.

## Continuation rule

For the 309 core molecules:

```text
coverage_ratio = (confirmed_count + ai_provisional_count) / core_molecule_count
workflow_can_continue = coverage_ratio >= 0.80
```

The projection always includes `confirmed_count`, `ai_provisional_count`,
`blocked_count`, `core_molecule_count`, `coverage_ratio`,
`coverage_threshold`, an uncertainty statement, and a visible gap registry.
Missing data is never silently counted as zero. A project below 80% remains
usable for source/evidence preparation but is visibly `needs_more_traceable_candidates`.

## Consumer rules

- Evidence and synthesis may consume `CONFIRMED` for exact claims.
- `AI_PROVISIONAL` may be consumed only by explicitly provisional internal
  views and must retain its confidence/provenance label.
- `BLOCKED` is excluded from exact structure claims and is emitted in the
  limitation/gap registry.
- Release and benchmark reports show total, confirmed, provisional, blocked,
  per-study coverage, traceability, and uncertainty disclosure.
- Credits remain `NOT_APPLICABLE_BY_CURRENT_SCOPE` when the route does not
  measure credits; missing ledgers are not interpreted as zero.

All user-facing route labels and reports say `Honest Progressive Route`.
Technical flags such as `--strict` used by unrelated validators are not route
names and are unaffected.
