# Phase 5f Portability Hardening PR

## PR Title

`fix: parameterize local paths in qoderwork docs`

## Summary

This PR removes machine-specific defaults from generic QoderWork docs, skills,
scripts, and demo assets. Kenqia-specific validation paths are isolated in
`docs/local/KENQIA_LOCAL_VALIDATION.md`, while generic docs now use placeholders
such as `<REPO_ROOT>`, `<OUTPUT_ROOT>`, and `<QODERWORK_SKILLS_DIR>`.

## Added Files

- `docs/local/KENQIA_LOCAL_VALIDATION.md`
- `docs/portability/portable_skill_guidelines.md`
- `docs/pr/phase5f_portability_hardening_pr.md`
- `scripts/check_portability.py`
- `tests/test_portability.py`

## Updated Areas

- QoderWork skill docs now require explicit path resolution before commands.
- QoderWork install docs use parameterized install targets.
- Demo and eval docs use `<OUTPUT_ROOT>` and repo-relative paths.
- Real-lite input package pointers use portable placeholders.
- Installer candidate discovery uses optional environment variables instead of hardcoded user paths.
- `make real-lite-preflight` uses `$(REPO_ROOT)` and `$(SEARCH_ROOT)`.

## Safety Boundary

- No PDF body read.
- No MinerU API.
- No Qwen call.
- No uploads.
- No Bailian knowledge base creation.
- No image API.
- No secrets read or printed.

## Validation

```bash
make portability-check
python tests/test_portability.py
```

Full local QA:

```bash
make smoke
make quality-check
make qoderwork-check
make provider-check
make qwen-hello-dry-run
make judge-check
make tiny-e2e-check
make real-lite-preflight
make real-lite-e2e-check
make dashboard-real-lite-check
make eval-baseline-check
make portability-check
```

## Risks

- Historical PR notes still contain local validation paths, but they are marked
  as local validation records and are allowed by the portability checker.
- `/tmp` remains a convenient default for generated temporary reports and demo
  output; generic docs use `<OUTPUT_ROOT>`.

## Next Stage

- Phase 5g: PR review / merge readiness.
- Phase 6a: Bailian RAG preflight.
