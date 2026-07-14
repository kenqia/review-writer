# Minimum Baseline Evaluation Plan

## Objective

Measure the product value of evidence verification and conflict control on one
small Case 02 question without recreating Phase 8A or building a benchmark
platform.

## Fixed Experimental Unit

- One research question.
- The same 3-5 source artifacts and the same extracted-text boundary.
- One short comparison table and one 2-4 paragraph synthesis target.
- One fixed Qwen model/region and bounded generation settings where applicable.
- No web search during generation unless it is a declared, identical input to
  all arms.

## Arms

### Baseline A: Direct Qwen

Provide the bounded source text and research question directly to Qwen. Ask for
the target table and synthesis with citations. Do not provide a claim ledger or
verification results.

### Baseline B: Retrieval/RAG plus Qwen

Use the existing local or Bailian retrieval path to select chunks, then ask Qwen
for the same output. Preserve retrieved chunk IDs and scores.

### Full System

Use source inventory, atomic claims, evidence locators, independent verification,
conflict/missing-field handling, bounded human feedback, and grounded synthesis.

## Metrics

| Metric | Automatic/manual | Definition |
| --- | --- | --- |
| Unsupported numeric claims | Automatic candidate detection + manual confirmation | Scientific numbers in output with no supporting source/claim binding |
| Citation-paper mismatch | Automatic where mapping exists + manual confirmation | Cited paper does not support the sentence's core fact |
| Source-conflict leakage | Automatic | A retained conflict is rendered as one settled fact |
| Sentence locator coverage | Automatic | Proportion of factual sentences with at least one valid evidence locator |
| Core-fact contradiction | Manual | Sentence contradicts its cited source or verified claim |
| Human-modified sentences | Automatic count from accepted diff | Number/proportion of factual sentences changed after review |
| Human overall rating | Manual, blinded arm labels | Small rubric for factual usefulness, traceability, and editing burden |
| Calls | Automatic | Model and retrieval request counts |
| Tokens | Automatic where provider returns usage | Prompt, completion, and total tokens |
| Time | Automatic | Wall-clock time per arm, excluding deliberate human pause reported separately |
| Cost | Automatic calculation from recorded usage and official price snapshot | Report assumptions and date; do not fabricate absent usage |

## Review Protocol

- Randomize arm labels for the human reviewer.
- Use the same bounded source set and output target.
- Review every scientific number and every sentence citation in this small
  experiment; this is feasible because the output is short.
- Report counts and examples, not a publication-grade accuracy estimate.
- Record disagreements and unjudgeable items explicitly.

## Existing Data Reuse

Case 01 can backfill **Full System engineering evidence** for unsupported-number
blocking, conflict leakage prevention, sentence locator mapping, feedback diff,
request count, and tokens. The Phase 8B V2 model manifest records 22,584 prompt
tokens, 9,148 completion tokens, and 31,732 total tokens for the successful
second attempt.

Case 01 cannot provide a fair three-arm comparison because Direct Qwen and RAG
outputs were not generated under the same final frozen source/question/output
contract. Do not retroactively label old artifacts as those baselines.

Existing `scripts/eval/run_eval_baseline.py:14` and
`scripts/eval/run_clean_3paper_eval.py:12` can supply artifact/safety utilities,
but their scores measure workflow health and Case 01 traceability, not the
competition comparison. Reuse small helpers only; do not add a new general
benchmark framework.

## Acceptance Evidence

The Case 02 comparison is complete when it has:

- three frozen output packages bound to the same input manifest;
- one machine-readable metrics table and one short human-review sheet;
- redacted request/token/time metadata;
- a concise finding that states what the full system improved and what remains
  unresolved;
- no claim of statistical generalization from the single case.

