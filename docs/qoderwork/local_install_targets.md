# QoderWork Skill Install Targets

## Summary

QoderWork skill installation is user-environment specific. Do not assume a
particular Windows user directory, WSL home directory, or QoderWork CN path.

Use these placeholders in generic instructions:

```text
<REPO_ROOT>
<QODERWORK_SKILLS_DIR>
<QODERWORK_CN_SKILLS_DIR>
```

Kenqia's local validation paths are recorded separately in
`docs/local/KENQIA_LOCAL_VALIDATION.md`. They are not defaults for general
users.

## Candidate Discovery

Use dry-run mode first:

```bash
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir <QODERWORK_SKILLS_DIR> \
  --dry-run
```

Optional environment variables can help list local candidates without hardcoding
machine-specific paths:

```bash
export QODERWORK_SKILLS_DIR="<QODERWORK_SKILLS_DIR>"
export QODERWORK_CN_SKILLS_DIR="<QODERWORK_CN_SKILLS_DIR>"
python scripts/install_qoderwork_skills.py --list-candidates
```

## Install

Only install after explicit human confirmation:

```bash
python scripts/install_qoderwork_skills.py \
  --skills-dir qoderwork/skills \
  --target-dir <QODERWORK_SKILLS_DIR> \
  --apply
```

The installer refuses to overwrite an existing skill directory.

## Windows / WSL Notes

Windows and WSL setups should pass explicit paths. If QoderWork runs on Windows
but the repository is inside WSL, use an environment-specific command such as:

```powershell
wsl.exe --cd <REPO_ROOT_IN_WSL> bash -lc "make smoke"
```

Do not treat WSL as the only supported runtime. Native Linux, WSL, and other
local setups should all provide their own `<REPO_ROOT>` and
`<QODERWORK_SKILLS_DIR>`.

## Rollback

Rollback should remove only the five review-writer skill directories installed
by this repository. Verify `<QODERWORK_SKILLS_DIR>` before running:

```bash
rm -rf "<QODERWORK_SKILLS_DIR>/chem-review-orchestrator"
rm -rf "<QODERWORK_SKILLS_DIR>/chem-review-library-prep"
rm -rf "<QODERWORK_SKILLS_DIR>/chem-review-planning"
rm -rf "<QODERWORK_SKILLS_DIR>/chem-review-drafting"
rm -rf "<QODERWORK_SKILLS_DIR>/chem-review-quality-release"
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

- Directory discovery is local to each user.
- No real API, retrieval, MinerU, or image generation call is required for
  installation discovery.
