# Portable Skill Guidelines

## Goal

Generic review-writer skills and product docs must work for users beyond one
developer's machine. Do not hardcode personal home directories, Windows account
names, WSL repo paths, QoderWork CN install paths, or temporary output roots as
defaults.

## Parameterize These Values

Use placeholders:

```text
<REPO_ROOT>
<REVIEW_ROOT>
<PAPER_LIBRARY>
<OUTPUT_ROOT>
<PROVIDER_CONFIG>
<QODERWORK_SKILLS_DIR>
<QODERWORK_CN_SKILLS_DIR>
```

Agents should resolve these from user input before running commands. If a
required path is missing, ask the user or use a repo-relative demo project.

## Local Validation Belongs Elsewhere

Machine-specific validation notes belong in:

```text
docs/local/KENQIA_LOCAL_VALIDATION.md
```

That file records one developer environment and is not a default path guide.
Historical PR notes may retain local paths only when they are clearly marked as
local validation records.

## Windows / WSL Examples

Windows and WSL are optional deployment shapes, not the only supported runtime.
Use examples like this:

```powershell
wsl.exe --cd <REPO_ROOT_IN_WSL> bash -lc "make smoke"
```

Do not write a real username or personal Desktop path into generic docs.

## Default Path Strategy

- Repo source paths should be repo-relative.
- External data should use `<DATA_ROOT>` or explicit CLI arguments.
- Temporary output can use `<OUTPUT_ROOT>` with `/tmp/...` only as an example.
- QoderWork install docs should use `<QODERWORK_SKILLS_DIR>`.
- Real API keys must stay in temporary environment variables or untracked local files.

## Verification

Run:

```bash
make portability-check
```

This fails if generic docs/scripts contain personal path patterns outside the
approved local-validation allowlist.

## Next Stages

- Phase 5g: PR review / merge readiness.
- Phase 6a: Bailian RAG preflight.
