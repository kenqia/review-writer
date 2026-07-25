# review-writer Project Instructions

## Scope

This repo contains the review-writer workflow source, QoderWork skill source, local dashboard code, deterministic scripts, and migration documentation.

Generated paper libraries, MinerU outputs, project outputs, real PDFs, API tokens, and local metadata are external data and should not be committed.

## Safety

- Do not read, print, copy, commit, or upload real API keys, tokens, cookies, sessions, or private auth files.
- Do not modify `~/.codex`, `~/.qoderwork`, Windows `.codex`, CC Switch, or Headroom provider config from this repo.
- Do not run remote writes, push, publish, deploy, or install global QoderWork/Codex skills without explicit confirmation.
- Use `.env.example` and `config/providers.example.yaml` for documented configuration only.

## Data Layout

Default external data root placeholder:

```text
<DATA_ROOT>/
```

Recommended local data directories under that root:

```text
chem_papers/
mineru-outputs/
review-library/
review-projects/
template-papers/
```

The repository may create same-named local directories during development, but they are ignored by Git.

## Workflow

Main Codex entry:

```text
review-writing-orchestrator
```

Main QoderWork entry source:

```text
qoderwork/skills/chem-review-orchestrator/SKILL.md
```

Human checkpoints are mandatory after library audit, discovery, matrix/outline, blueprint, section drafting, figure redraw, first draft, final audit, and DOCX/PDF export.

## Verification

Prefer deterministic local checks before any LLM/API step:

```bash
make smoke
make quality-check
```

If a check cannot run because project data has not been created yet, report that explicitly rather than calling the workflow complete.

## Owner-Review Orchestration

- Each work package has exactly one writable persistent Implementation Owner; all reviewers and the Final Verifier are fresh, read-only sessions.
- Repairs resume the recorded original Owner unless a documented replacement is approved.
- Parallel writing requires approved worktrees and a dedicated Integration Owner.
- Read `docs/agent-orchestration/AGENT_OPERATING_MODEL.md` before launching orchestration work.
