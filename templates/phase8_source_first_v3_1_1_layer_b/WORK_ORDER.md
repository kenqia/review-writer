# V3.1.1 Layer B Exact Claim Verification

Run `python3 input/verify_input_package.py` before opening a source. Process `input/verifier_tasks.jsonl` in manifest order, one task at a time. Each task contains exactly one Layer A claim and one task-specific source PDF slice. The task's `allowed_original_page_indices` and `source_binding` map the claim's structured `evidence_locator` to the packaged PDF pages.

Independently verify value, unit, entities, product, reaction entry, reaction stage, fact type, locator, and epistemic class against that task's source artifact. Do not use the old V3 `locator_scope` model and do not search beyond the packaged pages. Do not compare claims with each other or infer a verdict from Layer A wording.

For a `source_conflict` claim, verify whether the conflict and its alternatives were faithfully recorded. Use `SOURCE_CONFLICT` with `FAITHFULLY_RECORDED` when appropriate. Do not select or declare one alternative as the winner; the output schema intentionally has no selected-alternative field.

Write exactly one row per task to `output/results.jsonl` using `schemas/verifier_output.schema.json`. Use only these verdicts:

```text
SUPPORTED
EDIT_REQUIRED
CONTRADICTED
INSUFFICIENT_EVIDENCE
LOCATOR_ERROR
ENTITY_BINDING_ERROR
REACTION_STAGE_ERROR
FACT_TYPE_ERROR
SOURCE_CONFLICT
```

Keep `short_independent_evidence` concise and source-bound. `EDIT_REQUIRED` must include `corrected_fields`; `SUPPORTED` and faithfully recorded `SOURCE_CONFLICT` must not. After writing all rows, run:

```bash
python3 input/finalize_output.py
```

Finalization verifies the immutable package, task/claim/upstream hashes, exact task coverage, structured locator containment, conflict semantics, schema, and closed output set.
