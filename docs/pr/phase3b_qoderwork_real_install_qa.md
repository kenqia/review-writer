# Phase 3b QoderWork Real Install Target QA

## PR Title

`feat: add qoderwork real install target QA`

## Summary

This PR documents and validates QoderWork CN skill install targets for a
Windows + WSL machine. It adds installer candidate discovery, improves dry-run
output, and records a controlled install plan without performing a real install.

No global QoderWork directory was modified.

## Repository State

- Branch: `feat/chem-review-quality-gates`
- Remote branch: `origin/feat/chem-review-quality-gates`
- Latest baseline in branch includes:
  - `a4ef2f8 feat: add qoderwork skill pack QA`
  - `f85253f docs: add phase 2 quality gates PR notes`
  - `ae1e549 fix: constrain dashboard file access`
  - `3bf7a5c fix: address final dashboard browser qa issues`
  - `edcc3f0 feat: integrate quality gate into final audit`
  - `0ff5972 feat: add chemistry review quality gates`
  - `be94d33 chore: establish QoderWork migration baseline`

## Candidate Discovery

| target | status | skill count | conflicts |
| --- | --- | ---: | --- |
| `/home/kenqia/.qoderwork/skills` | not found | 0 | none |
| `/mnt/c/Users/26960/.qoderwork/skills` | exists | 10 | none |
| `/mnt/c/Users/26960/.qoderworkcn/skills` | exists | 10 | none |
| `/mnt/d/qodework/QoderWork CN/skills` | not found | 0 | none |

The Windows-side QoderWork CN user target is more likely to be read by the
active client because it already contains built-in QoderWork CN skills. The
WSL-side target does not exist. The D drive QoderWork CN project root exists at
`/mnt/d/qodework/QoderWork CN`, but it does not currently contain a `skills`
directory.

Related Windows-side directories were also observed, including `.qoderwork`,
`.qoderworkcn`, and AppData QoderWork directories.

## Installer Changes

`scripts/install_qoderwork_skills.py` now supports:

```bash
--list-candidates
--skills-dir <path>
--target-dir <path>
--target <path>
--dry-run
--apply
```

Behavior:

- default remains dry-run
- `--apply` is required to copy files
- dry-run prints source, target, target existence, parent existence, and per-skill destination status
- existing target skill directories are not overwritten
- `--list-candidates` prints likely WSL, Windows, Windows CN, and D drive project-derived targets without writing files

## Dry-Run Results

WSL target:

- target exists: false
- target parent exists: false
- no files copied

Windows target:

- target exists: true
- target parent exists: true
- all five review-writer skill destinations do not yet exist
- no files copied

Windows CN target:

- target exists: true
- target parent exists: true
- all five review-writer skill destinations do not yet exist
- no files copied

D drive project-derived target:

- target exists: false
- target parent exists: true
- not recommended unless QoderWork CN runtime discovery proves it reads this path

Candidate listing:

```text
wsl: /home/kenqia/.qoderwork/skills (exists=False, parent_exists=False, skill_count=0)
windows: /mnt/c/Users/26960/.qoderwork/skills (exists=True, parent_exists=True, skill_count=10)
windows-cn: /mnt/c/Users/26960/.qoderworkcn/skills (exists=True, parent_exists=True, skill_count=10)
windows-cn-project: /mnt/d/qodework/QoderWork CN/skills (exists=False, parent_exists=True, skill_count=0)
```

## Recommended Install Target

Use the Windows-side QoderWork CN target:

```bash
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir /mnt/c/Users/26960/.qoderworkcn/skills \
  --apply
```

Do not run this command until the user explicitly confirms `apply install`.

## Rollback Plan

Remove only review-writer skill directories:

```bash
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-orchestrator
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-library-prep
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-planning
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-drafting
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-quality-release
```

For QoderWork CN, use:

```bash
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-orchestrator
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-library-prep
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-planning
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-drafting
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-quality-release
```

## Manual Smoke Prompt

```text
请使用 chem-review-orchestrator skill 做只读 smoke test。不要调用真实 API，不要读取真实论文，不要修改文件。请只用 5 条以内说明：你是否加载了该 skill、你需要哪些输入字段、你会进入哪个人工 checkpoint、你会生成哪些离线报告、哪些操作需要我确认。
```

## Validation Commands

```bash
make smoke
make quality-check
make qoderwork-check
python scripts/install_qoderwork_skills.py --list-candidates
python scripts/install_qoderwork_skills.py --skills-dir qoderwork/skills --target-dir "$HOME/.qoderwork/skills" --dry-run
python scripts/install_qoderwork_skills.py --skills-dir qoderwork/skills --target-dir /mnt/c/Users/26960/.qoderwork/skills --dry-run
python scripts/install_qoderwork_skills.py --skills-dir qoderwork/skills --target-dir /mnt/c/Users/26960/.qoderworkcn/skills --dry-run
git status --short
```

Expected result: all commands pass, no global install occurs, and git status is
clean after committing.

## Not Included

- no real `--apply` install
- no overwrite of existing skills
- no QoderWork config changes
- no Codex auth/config changes
- no real LLM, DashScope, MinerU, retrieval, or image generation calls
- no push, merge, or branch deletion

## Next Stage

After explicit user confirmation, run the Windows CN real install command, open
QoderWork CN, and run the manual smoke prompt. If discovery succeeds, proceed to
Alibaba adapter skeletons with offline fallback.
