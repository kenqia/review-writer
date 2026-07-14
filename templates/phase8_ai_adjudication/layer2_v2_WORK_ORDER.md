# V2 Dual-Mode Independent Review Work Order

1. Verify `INPUT_MANIFEST.sha256` before reading tasks.
2. Process all 41 rows in `input/tasks.jsonl` exactly once.
3. For `CANDIDATE_VERIFICATION`, independently open the source before judging the supplied claim.
4. For `BLIND_DUAL_EXTRACTION`, independently find one atomic fact without a supplied claim.
5. For non-exact locator qualities, search independently and do not assume a label or value.
6. Follow `schemas/layer2_v2_output.schema.json` and keep evidence excerpts short.
7. Write only `output/results.jsonl`, then run `python3 input/finalize_output.py`.
8. Stop after the output manifest is created.
