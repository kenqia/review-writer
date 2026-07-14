# Layer B Exact Claim Verification

Verify each concrete claim independently against its original source using exactly the claim's `locator_scope`.

- For `EXACT_PAGE`, facts found elsewhere require `LOCATOR_ERROR`; they may be recorded only as `recovery_candidate`.
- For `PAGE_WINDOW`, do not search outside the window.
- For `SECTION`, do not search outside the section.
- Only `FULL_SOURCE` permits full-document search.

Check value, unit, entity roles, product, reaction entry, reaction stage, fact type, locator, and epistemic class. Use only the verdicts and fields defined by `layerB_verifier_output.schema.json`. Do not compare against other claims or sessions.
