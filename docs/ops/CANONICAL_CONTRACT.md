# Canonical Contract

本文件定义这条 canonical code line 的边界，不定义新的综述验收。

## Identity and provenance

- Base: `31d9dab16edc105b4f03aa7e8d3bf3745ed326fa`.
- Base parent: `44e485a2fe3b6161b8b3965d7be5412ad0f005ee`.
- Integrated worktree: `/home/kenqia/my_folder/review-writer/.worktrees/e2r-canonicalization`.
- The final integrated commit identity is reported from `git rev-parse HEAD` after the local commit; this document deliberately does not self-embed a commit hash.
- All four governing specification/plan/QA documents remain the exact content from the single base revision above.

## Reviewed SI patch

Source-only reference: `codex/e2r-chemical-integration@0aa517cc802a7af714bb39363755b46c137f0b16`.

Only these two files were transplanted manually:

1. `review_writer/project/dual_parse_bootstrap.py`
2. `tests/test_dual_parse_bootstrap.py`

For a `core` study without an SI input, bootstrap now writes:

- `si_policy = REQUIRED`;
- `study_status = PARTIAL`;
- `blocking_reasons = ["SI_REQUIRED_FOR_DECLARED_CLAIMS"]`;
- `blocked_claim_ids = []`;
- `limitations = []`.

Non-core rows retain the existing `NOT_REQUIRED` / `READY` behavior. The corresponding test asserts the core-study contract. No unrelated generic-binding change from `0aa517c` was copied.

## Retained honest-progressive contract

The base revision remains the source for the following behavior:

- Honest Progressive permits incomplete work while making uncertainty visible.
- The only authoritative scientific states are `CONFIRMED`, `AI_PROVISIONAL`, and `BLOCKED`.
- The project denominator is 309, with coverage calculated as `(CONFIRMED + AI_PROVISIONAL) / 309`.
- Generic MinerU and Chemical Paper are separate bound input lanes.
- Safe projection is downstream of formal input binding and must fail closed on missing or mismatched provenance.
- Candidate-only and gap-registry artifacts remain non-authoritative.
- A `CONFIRMED` scientific decision is researcher-owned; an AI candidate cannot silently become confirmed.
- Current-scope credits remain `NOT_APPLICABLE_BY_CURRENT_SCOPE`.

## Four distinct evidence layers

| Layer | Meaning | Can it authorize a scientific claim? |
|---|---|---|
| raw Chemical candidate | MinerU/Chemical extraction or candidate result with provenance and unresolved gaps | No |
| authoritative Honest Progressive projection | Server/calculator-produced rows, each explicitly `CONFIRMED`, `AI_PROVISIONAL`, or `BLOCKED`, with required locators/provenance/gap reason | Only according to the state contract; `CONFIRMED` still needs researcher decision |
| Researcher decision | Human/researcher-owned, PDF-bound scientific acceptance or rejection | Yes for the decision's declared scope |
| downstream Evidence | Evidence/Synthesis/Manuscript/release input created only after valid upstream gates | No retroactive authority; it inherits upstream provenance |

The reported snapshot `210 raw candidate / 99 unresolved` belongs to the first layer. It is not a formal three-state count and cannot be interpreted as `210 AI_PROVISIONAL`, `0 CONFIRMED`, or any release coverage result. The current fresh project has no formal three-state projection artifact.

## Forbidden transitions

- raw Chemical candidate → `CONFIRMED`: forbidden without researcher decision and PDF locator;
- missing/uncertain value → guessed SMILES/digest: forbidden;
- `BLOCKED` → covered count: forbidden;
- candidate staging → downstream Evidence: forbidden without formal lifecycle receipt;
- runtime visibility → project authority: forbidden without a project-scoped receipt.
