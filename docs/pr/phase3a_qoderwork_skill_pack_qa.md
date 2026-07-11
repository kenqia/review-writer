# Phase 3a QoderWork Skill Pack QA PR Notes

## PR Title

`feat: add qoderwork skill pack QA`

## Summary

This PR adds offline QA for the QoderWork skill pack. It validates skill
frontmatter, trigger descriptions, safety wording, human checkpoints, quality
gate requirements, deterministic script references, and installer behavior.

No real API calls are introduced. The install path remains dry-run by default.

## Branch Relationship

- `qoderwork-migration-baseline` contains the Phase 1 migration baseline:
  QoderWork skill source, migration docs, safety checks, local config examples,
  and externalized generated data.
- `feat/chem-review-quality-gates` is linear on top of the baseline and adds
  Phase 2 quality gates plus Phase 3a skill pack QA.

Recommended PR order:

1. PR1: `qoderwork-migration-baseline` -> `main`.
2. PR2: `feat/chem-review-quality-gates` -> `qoderwork-migration-baseline`
   while PR1 is open, or retarget PR2 to `main` after PR1 merges.

## Skill Pack

| skill | QA result |
| --- | --- |
| `chem-review-orchestrator` | pass |
| `chem-review-library-prep` | pass |
| `chem-review-planning` | pass |
| `chem-review-drafting` | pass |
| `chem-review-quality-release` | pass |

## Added QA Tooling

- `scripts/check_qoderwork_skills.py`
  - parses SKILL frontmatter
  - checks name and description
  - detects broad trigger descriptions
  - detects secret-like values without printing values
  - detects disallowed operation wording
  - detects machine-specific absolute paths
  - verifies human checkpoint, quality gate, offline smoke, and script references
  - writes JSON and Markdown reports
  - returns non-zero in strict mode when errors exist
- `make qoderwork-check`
  - runs the skill checker in strict mode
  - runs installer dry-run

## Installer QA

`scripts/install_qoderwork_skills.py` now supports:

```bash
--skills-dir <path>
--target-dir <path>
--target <path>
--dry-run
--apply
```

Default behavior remains dry-run. Copying happens only with `--apply`.
Existing target skill directories are not overwritten.

Staging QA path:

```text
/tmp/review_writer_qoderwork_skills_staging
```

Observed staging result:

- 5 skill directories copied.
- each copied skill has `SKILL.md`.
- checker passed against the staging directory.

## Global Skill Directory Check

Only a read-only check was performed. No files were copied to
`~/.qoderwork/skills`.

Observed state:

- `~/.qoderwork/skills` did not exist.
- no same-name skill conflicts were found.

## Validation Commands

```bash
make smoke
make quality-check
make qoderwork-check
python tests/test_quality_validators.py
python scripts/check_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --output-json /tmp/qoderwork_skill_check.json \
  --output-md /tmp/qoderwork_skill_check.md \
  --strict
python scripts/install_qoderwork_skills.py --dry-run
```

Expected result: all commands pass offline.

## Not Included

- no real LLM API calls
- no DashScope calls
- no MinerU API calls
- no real image generation calls
- no global QoderWork skill installation
- no merge, rebase, branch deletion, or push in this phase
- no Alibaba provider adapter implementation

## Risks

- The checker is intentionally text-based; it validates safety and packaging
  signals, not QoderWork runtime internals.
- Trigger breadth is heuristic and may need tuning after real QoderWork usage.
- Skill invocation UX depends on the installed QoderWork client behavior.

## Next Stage

- Add Alibaba provider adapter skeletons without real credentials.
- Add provider config validation with offline fallback.
- Add PDF/LaTeX export skeleton and smoke checks.
- Add human review and local partial-regeneration design.
