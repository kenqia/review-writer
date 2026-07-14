# Layer A Source-First Evidence Inventory

Read `AGENTS.override.md`, then run `python3 input/verify_input_package.py` before reviewing sources.

For each row in `input/source_units.jsonl`, inspect only its listed sources and only the area allowed by `locator_scope`:

- `EXACT_PAGE`: inspect only `pdf_page_index`.
- `PAGE_WINDOW`: inspect only the inclusive `page_window`.
- `SECTION`: inspect only the named `section`.
- `FULL_SOURCE`: the full listed source files may be searched.

Inventory only atomic, review-relevant evidence actually reported by the source. Do not manufacture one result for every category. A category with no qualifying evidence produces no claim.

Each claim must bind one fact to explicit entity roles, reaction stage, reaction entry, metric/value, and source locator. Yield, ee, er, and dr require a product and reaction entry. Never silently convert ee to er, treat substrate preparation as the target catalytic reaction, treat intermediate isolation as proof of a catalytic pathway, or emit a negative claim without explicit source text. Read `printed_page_label_observed` from the page itself; never derive it from `pdf_page_index`.

F3I is a background/review source. Its scientific summaries use `REVIEW_ARTICLE_SUMMARY`, not direct experimental-result classes; source identity/provenance remains metadata.

Use `schemas/layerA_inventory_output.schema.json`. Write exactly one JSONL result row per source unit to `output/results.jsonl`. Claim IDs must be `CL-<source_unit_id>-NNN`, unique across the file. An empty `claims` array is valid when the source unit contains no qualifying evidence. Do not emit `AI_INFERENCE` claims.

After writing results, run:

```bash
python3 input/finalize_output.py
```

Completion requires successful input verification, schema validation, exact source-unit coverage, unique IDs, matching hashes, unchanged sources/inputs, and a valid output manifest.
