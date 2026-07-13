# Source-First Layer A Evidence Inventory

Run `python3 input/verify_input_package.py` before opening any source. Read each row in `input/source_units.jsonl` and inspect only the listed `source_artifacts` and original page indices. The packaged PDF pages are a closed source subset; their workspace page order is mapped to original indices in `input/source_bindings.json`.

For every source unit, answer its `review_question` within `included_claim_classes`, `excluded_material`, and `required_sections_or_page_ranges`. Each retained claim must be one atomic fact with one entity, one reaction stage, one value or fact, and one evidence target. Task `search_scope` defines where to search. Claim `evidence_locator` records where the evidence was actually found and must be exact or a tight page window.

Distinguish substrate synthesis from target catalysis, substrate from product, isolated yield from assay yield or conversion, and ee from er or dr. Do not silently convert stereochemical metrics. Intermediate isolation is not proof of a catalytic pathway. Separate author-proposed mechanism from experimental mechanistic observation. Preserve source-internal conflicts with both alternatives and both locators. A visual modality requires a table, scheme, or figure locator. Review-source summaries must use `REVIEW_ARTICLE_SUMMARY`.

Write exactly one row per source unit to `output/results.jsonl` using `schemas/layerA_inventory_output.schema.json`. Every row records `coverage_summary`, `pages_examined`, `sections_examined`, and `status_reason`. `COMPLETED` requires complete unit coverage and at least one valid claim. Use `PARTIAL` honestly for incomplete coverage. `SOURCE_UNREADABLE`, `OUT_OF_SCOPE`, and `NO_QUALIFYING_EVIDENCE` require a reason and no claims. Do not manufacture claims to satisfy completion.

After writing results, run:

```bash
python3 input/finalize_output.py
```

Finalization verifies the immutable input package, closed output set, complete source-unit coverage, schema, task hashes, source roles, page bounds, observed printed labels, search/evidence containment, metric/value/unit binding, normalization, epistemic class, and conflict structure.
