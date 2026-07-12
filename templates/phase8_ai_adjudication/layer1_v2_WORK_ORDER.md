# V2 Blind Source Extraction Work Order

1. Verify `INPUT_MANIFEST.sha256` before reading tasks.
2. Process all 41 rows in `input/tasks.jsonl` exactly once.
3. Open the specified source and independently locate the atomic evidence target.
4. For `SECTION_WINDOW`, `PAGE_WINDOW`, or `SOURCE_ONLY`, search independently and do not assume a label or value.
5. Follow `schemas/layer1_v2_output.schema.json` and keep evidence excerpts short.
6. Write only `output/results.jsonl`, then run `python3 input/finalize_output.py`.
7. Stop after the output manifest is created.
