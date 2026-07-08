# QoderWork Skill Pack QA

## Current Skill Pack

| skill | trigger scenario |
| --- | --- |
| `chem-review-orchestrator` | Main entry for a topic-to-deliverables chemistry review workflow with project status, routing, checkpoints, and offline smoke behavior. |
| `chem-review-library-prep` | Prepare local PDFs or MinerU outputs into review-writer metadata and require a human metadata audit. |
| `chem-review-planning` | Convert a chemistry topic and local metadata into discovery results, literature matrix, outline options, and section blueprint. |
| `chem-review-drafting` | Draft approved sections, select source-grounded figures, coordinate redraw, and merge a first draft. |
| `chem-review-quality-release` | Run final chemistry quality checks and coordinate Markdown/DOCX/PDF-ready release outputs. |

## Install QA Commands

Dry-run only. This must not write to the global QoderWork skills directory:

```bash
python scripts/install_qoderwork_skills.py --dry-run
```

Staging install. This validates copy behavior without touching
`~/.qoderwork/skills`:

```bash
rm -rf /tmp/review_writer_qoderwork_skills_staging
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir /tmp/review_writer_qoderwork_skills_staging \
  --apply
python scripts/check_qoderwork_skills.py \
  --skills-dir /tmp/review_writer_qoderwork_skills_staging \
  --output-json /tmp/qoderwork_skill_check_staging.json \
  --output-md /tmp/qoderwork_skill_check_staging.md \
  --strict
```

Real install requires explicit human confirmation first:

```bash
python scripts/install_qoderwork_skills.py --apply
```

The installer refuses to overwrite an existing skill directory.

## Skill Discovery And Invocation

Expected QoderWork install shape:

```text
~/.qoderwork/skills/<skill-name>/SKILL.md
```

Typical invocation styles:

- Automatic trigger: describe a chemistry review workflow task that matches a skill description.
- Slash-style call: invoke the target skill by name if the QoderWork client supports slash shortcuts.
- Explicit conversation call: ask QoderWork to use `chem-review-orchestrator` or a specific sub-skill.

Use `chem-review-orchestrator` for most end-to-end work. Use sub-skills only
when the current stage is already known.

## Human Checkpoints

Do not continue automatically across these checkpoints without explicit human
approval:

```text
Library -> Discovery -> Matrix -> Blueprint -> Sections -> Figures -> Draft -> Final -> Export
```

The dashboard is a local review console. JSON and Markdown artifacts remain the
source of truth.

## Quality Gate Flow

Final release must run deterministic checks before export:

```bash
make smoke
make quality-check
python skills/review-final-audit-release/scripts/final_audit_scan.py \
  --review-root <review_root> \
  --project-id <project_id>
```

The final audit stage emits:

```text
05_final_audit/format_scan.json
05_final_audit/quality_report.json
05_final_audit/quality_report.md
```

Blocking quality errors must not be hidden. If there are no approved figures,
the workflow must record an explicit no-figure reason and require human review.

## Offline Smoke Policy

By default, skill QA and workflow smoke tests must not call:

- real LLM APIs
- DashScope
- MinerU API
- real image generation APIs
- external retrieval APIs

Provider-specific calls require explicit user approval and should degrade to
offline or local-only checks when unavailable.

## Known Limits

- Early QoderWork runtime behavior was represented by source-level QA and
  staging copy tests. Phase 5i later records one actual QoderWork CN product
  run at HEAD `7b9a8af`.
- Latest-HEAD QoderWork CN product revalidation remains optional.
- Semantic title and section-content alignment remains an LLM judge task placeholder.
- Alibaba provider adapters are documented but not implemented in this phase.
- PDF/LaTeX export remains a later skeleton target.

## Next Stage

- Add Alibaba provider adapter skeletons for LLM, retrieval, and image generation.
- Add PDF/LaTeX export skeleton and offline smoke checks.
- Design local human review, partial regeneration, and figure regeneration handoffs.
