# Work Order

Objective: Extract facts directly from the supplied source documents without judging any prior claim.

1. Read `INPUT_MANIFEST.json` and verify `INPUT_MANIFEST.sha256`.
2. Process every row in `input/tasks.jsonl` exactly once.
3. Follow `schemas/layer1_output.schema.json` exactly. Keep evidence excerpts short.
4. Write JSON Lines to `output/results.jsonl` only.
5. Run `python3 input/finalize_output.py` to create the two output manifest files.
6. Do not modify any input, schema, instruction, or source file.

Stop after the output manifest is written. Do not perform unrelated work.
