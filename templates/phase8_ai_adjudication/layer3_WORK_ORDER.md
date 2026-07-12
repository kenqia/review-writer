# Work Order

Objective: Adjudicate anonymous Candidate X and Candidate Y against the original source and deterministic rule flags.

1. Read `INPUT_MANIFEST.json` and verify `INPUT_MANIFEST.sha256`.
2. Process every row in `input/candidates.jsonl` exactly once.
3. Compare the anonymous candidates without assuming either is correct.
4. Reopen the supplied source whenever candidates conflict or a rule flag is present.
5. Follow `schemas/adjudication_output.schema.json` exactly and keep evidence excerpts short.
6. Write JSON Lines to `output/results.jsonl` only.
7. Run `python3 input/finalize_output.py` to create the two output manifest files.
8. Do not modify any input, schema, instruction, or source file.

Stop after the output manifest is written. Do not perform unrelated work.
