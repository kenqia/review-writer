# Phase 7 Retrieval Generation PR Notes

## Summary

This phase adds an orchestrator-backed retrieval generation pilot for one grounded section.

Added:

- `review_writer/pipeline/retrieval_generation.py`
- `scripts/demo/run_retrieval_generation_pilot.py`
- `scripts/validators/validate_grounded_section.py`
- offline retrieval replay fixtures
- Phase 7 Make gates
- QoderWork orchestrator/drafting routing notes

## Verification

```bash
make release-readiness-check
make bailian-phase6-final-check
make provider-check
make judge-check
make clean-3paper-e2e-check
make clean-3paper-eval-check
make phase7-pilot-dry-run
```

## Current Pilot Status

Offline replay passes and stops at `Sections: ready_for_human_review`.

The real controlled pilot reached the Qwen generation request, but the request timed out. Phase 7 is therefore not complete under the strict completion criteria.

## Safety Wording

Use this wording:

```text
Default checks do not upload; controlled pilots require explicit authorization.
```

Do not claim blanket "no uploads / no KB creation" for the whole branch, because Phase 6 and controlled pilots include explicit real upload/index lifecycles.
