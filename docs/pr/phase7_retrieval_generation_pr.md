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
make phase7-pilot-dry-run
make phase7-real-preflight
make offline-ci-workflow-check
make quality-check
make smoke
```

## Current Pilot Status

Offline replay passes and stops at `Sections: ready_for_human_review`.

Final controlled real pilot status:

- Qwen-only streaming smoke: pass
- Full Bailian + Qwen E2E: pass
- model: `qwen3.7-plus`
- thinking: disabled
- external search: disabled
- finish_reason: stop
- retrieval evidence count: `3`
- EvidencePack hash prefix: `02ded82c3494`
- claim-evidence coverage: `1.0`
- unsupported claims: `0`
- unsupported citations: `0`
- prompt leakage: `0`
- malformed marker count: `0`
- Sections checkpoint: `ready_for_human_review`
- temporary index/file cleanup: pass
- Phase 7 real pilot: complete

Generated sections remain human-review artifacts, not final scientific text.

## Safety Wording

Use this wording:

```text
Default checks do not call Qwen/Bailian, upload files, or create knowledge bases.
Controlled real pilots require explicit authorization, use sanitized payloads,
write reports under /tmp, and perform best-effort cleanup.
```

Do not claim blanket "no uploads / no KB creation" for the whole branch, because Phase 6 and controlled pilots include explicit real upload/index lifecycles.
