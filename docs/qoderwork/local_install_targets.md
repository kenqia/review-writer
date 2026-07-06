# QoderWork Local Install Targets

## Summary

This machine is a Windows + WSL setup using QoderWork CN. The likely QoderWork
CN skill directory is the Windows-side CN user directory exposed through WSL:

```text
/mnt/c/Users/26960/.qoderworkcn/skills
```

The Windows project root exists here, but it does not currently contain a
`skills` directory:

```text
/mnt/d/qodework/QoderWork CN
```

The WSL-side directory also does not currently exist:

```text
/home/kenqia/.qoderwork/skills
```

No real install was performed during this QA pass.

## Candidate Status

| target | exists | parent exists | observed skills | same-name conflicts |
| --- | --- | --- | ---: | --- |
| `/home/kenqia/.qoderwork/skills` | no | no | 0 | none |
| `/mnt/c/Users/26960/.qoderwork/skills` | yes | yes | 10 | none |
| `/mnt/c/Users/26960/.qoderworkcn/skills` | yes | yes | 10 | none |
| `/mnt/d/qodework/QoderWork CN/skills` | no | yes | 0 | none |

Additional related Windows-side directories were observed:

```text
/mnt/c/Users/26960/.qoderwork
/mnt/c/Users/26960/.qoderworkcn
/mnt/c/Users/26960/AppData/Roaming/QoderWork
/mnt/c/Users/26960/AppData/Roaming/QoderWork CN
```

If using QoderWork CN specifically, verify whether it reads
`.qoderworkcn/skills` before installing.

## Recommended Target

Use the Windows-side QoderWork CN user target first:

```text
/mnt/c/Users/26960/.qoderworkcn/skills
```

Reason:

- The active client is QoderWork CN.
- The Windows CN target already exists.
- It contains QoderWork CN built-in skills such as `qoderwork-guidance`.
- The WSL target does not exist.
- The D drive QoderWork CN project root exists, but `/mnt/d/qodework/QoderWork CN/skills` does not.
- Desktop QoderWork on this machine is more likely to read the Windows user
  directory than the WSL home directory.

## Dry-Run Commands

WSL target dry-run:

```bash
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir "$HOME/.qoderwork/skills" \
  --dry-run
```

Windows target dry-run:

```bash
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir /mnt/c/Users/26960/.qoderwork/skills \
  --dry-run
```

Windows CN target dry-run:

```bash
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir /mnt/c/Users/26960/.qoderworkcn/skills \
  --dry-run
```

Candidate listing:

```bash
python scripts/install_qoderwork_skills.py --list-candidates
```

Dry-run does not create directories or copy files.

## Real Install Commands

Do not run either command without explicit human confirmation.

WSL target:

```bash
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir "$HOME/.qoderwork/skills" \
  --apply
```

Windows target:

```bash
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir /mnt/c/Users/26960/.qoderwork/skills \
  --apply
```

Windows CN target:

```bash
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir /mnt/c/Users/26960/.qoderworkcn/skills \
  --apply
```

The installer refuses to overwrite an existing skill directory.

## Rollback Commands

Rollback should remove only the five review-writer skill directories installed
by this repository. Verify the paths before running:

```bash
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-orchestrator
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-library-prep
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-planning
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-drafting
rm -rf /mnt/c/Users/26960/.qoderwork/skills/chem-review-quality-release
```

QoderWork CN rollback:

```bash
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-orchestrator
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-library-prep
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-planning
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-drafting
rm -rf /mnt/c/Users/26960/.qoderworkcn/skills/chem-review-quality-release
```

WSL rollback, if the WSL target is used:

```bash
rm -rf "$HOME/.qoderwork/skills/chem-review-orchestrator"
rm -rf "$HOME/.qoderwork/skills/chem-review-library-prep"
rm -rf "$HOME/.qoderwork/skills/chem-review-planning"
rm -rf "$HOME/.qoderwork/skills/chem-review-drafting"
rm -rf "$HOME/.qoderwork/skills/chem-review-quality-release"
```

## Manual QoderWork Smoke Prompt

Copy this into QoderWork after installation:

```text
请使用 chem-review-orchestrator skill 做只读 smoke test。不要调用真实 API，不要读取真实论文，不要修改文件。请只用 5 条以内说明：你是否加载了该 skill、你需要哪些输入字段、你会进入哪个人工 checkpoint、你会生成哪些离线报告、哪些操作需要我确认。
```

Expected behavior:

- QoderWork identifies `chem-review-orchestrator`.
- It reports missing inputs such as `project_id`, `review_root`, `topic`,
  `paper_library`, and `output_format`.
- It routes to the first human checkpoint rather than performing work.
- It promises no real API calls.
- It asks for confirmation before any install, mutation, export, or provider
  call.

## Known Limits

- This QA pass discovers local directory candidates; it does not prove runtime
  discovery inside QoderWork until the manual smoke prompt is run.
- QoderWork CN appears to have its own `.qoderworkcn/skills` directory.
- The D drive project root is not treated as the install target unless a future
  QoderWork CN runtime check proves it reads `D:\qodework\QoderWork CN\skills`.
- No real API, retrieval, MinerU, or image generation call is required for
  installation discovery.

## Next Stage

After controlled install and manual smoke pass, add Alibaba provider adapter
skeletons with offline fallback and no committed credentials.
