# Tiny Allene Review Demo

This demo is a fully offline, synthetic end-to-end workflow skeleton for review-writer.

It uses three mock allene-ligand paper records, tiny mock MinerU markdown snippets, and one placeholder SVG figure. It does not read real PDFs, call MinerU, call Qwen, upload files, create a Bailian knowledge base, or generate images.

Run:

```bash
python scripts/demo/run_tiny_e2e.py \
  --demo-root demo_projects/tiny_allene_review \
  --output-root /tmp/review_writer_tiny_e2e \
  --strict
```
