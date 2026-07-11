# Clean 3-Paper Vertical Slice E2E

## Conclusion

Phase 5k turns the clean 3-paper draft package into a full offline vertical slice. It is stricter than real-lite because it uses the approved Top 3, bibliographic draft, claim draft, and figure-note draft instead of pointer-only real-lite assets.

The output is still not a final scientific review:

- `clean_draft`
- `needs_human_review`
- `not_final_scientific_review`
- `trusted_for_scientific_quality=false`

## Input Source

The runner only uses committed Phase 5j outputs:

```text
demo_projects/clean_3paper_allene_review/inputs/selected_papers.verified_draft.json
demo_projects/clean_3paper_allene_review/inputs/bibliography_verification_summary.json
demo_projects/clean_3paper_allene_review/expected/expected_claims.draft.json
demo_projects/clean_3paper_allene_review/expected/expected_figures.draft.json
```

It also writes a clean input package:

```text
demo_projects/clean_3paper_allene_review/inputs/selected_papers.clean_draft.json
demo_projects/clean_3paper_allene_review/inputs/clean_registry.jsonl
demo_projects/clean_3paper_allene_review/inputs/claims/
```

## Output

```text
/tmp/review_writer_clean_3paper_e2e/
  project_status_before.json
  checkpoint_log.json
  00_discovery/discovery_candidates.json
  01_matrix_outline/literature_matrix.json
  01_matrix_outline/outline.md
  section_blueprint.json
  02_section_drafting/section_1.md
  03_figure_redraw/figure_manifest.json
  04_first_draft/final_draft.md
  05_final_audit/final_audit_report.json
  05_final_audit/quality_report.json
  05_final_audit/clean_3paper_review_pack.md
  eval/clean_3paper_eval_report.json
  eval/clean_3paper_eval_report.md
  export/final_draft.md
  run_summary.json
```

## Commands

```bash
make clean-3paper-e2e-check
make clean-3paper-eval-check
make dashboard-clean-3paper-check
```

## Quality Gate

The final quality gate runs offline. It may return `warn` because P403 still has missing metadata and F47A/P403 preserve source-conflict warnings. Critical errors fail the run.

## Dashboard QA

The dashboard check verifies:

- Final payload includes `clean_3paper_review_pack`.
- Final payload includes `quality_report`.
- Figures payload includes `figure_manifest`.
- Checkpoints payload includes 9 checkpoints.
- `/file?path=/etc/passwd` returns 403.
- Review-root files remain accessible.

## Safety Boundary

- No full `chem_papers` scan.
- No long PDF body read.
- No Qwen, MinerU, Bailian, image API, upload, or knowledge-base creation.
- No `human_verified=true`.

## Next

- Phase 5l: user-facing review pack and manual acceptance.
- Phase 6a: Bailian RAG no-upload preflight.
