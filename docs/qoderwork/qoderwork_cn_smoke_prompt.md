# QoderWork Smoke Prompts

Use these prompts inside QoderWork after installing the review-writer
`chem-review-*` skills.

## 1. Read-Only Skill Load Smoke

This checks skill discovery only. It must not run repository commands.

```text
请使用 chem-review-orchestrator skill 做只读 skill 加载 smoke test。

禁止调用真实 API，禁止读取真实论文，禁止修改文件，禁止创建 smoke_test_report.md。

请只用 5 条以内回答：
1. 是否加载了 chem-review-orchestrator skill。
2. 加载的 skill 路径是什么。
3. 该 skill 需要哪些必填输入字段。
4. 它会进入哪个人工 checkpoint。
5. 哪些操作需要我明确确认。
```

## 2. Optional WSL Repo Command Smoke

Use this only when QoderWork runs on Windows and the repository lives inside
WSL. Replace `<REPO_ROOT_IN_WSL>` before running.

```text
请使用 chem-review-orchestrator skill 做 WSL repo 命令 smoke test。

必须使用真实 repo：
<REPO_ROOT_IN_WSL>

禁止使用任何未确认的 Windows Desktop 空目录作为 review_root。

禁止调用真实 API，禁止读取真实论文，禁止修改文件，禁止创建 smoke_test_report.md。

请只运行这一条命令：
wsl.exe --cd <REPO_ROOT_IN_WSL> bash -lc "make smoke && make quality-check && make qoderwork-check && git status --short"

最后请只用 5 条以内总结：
1. 是否加载了 chem-review-orchestrator skill。
2. 是否识别到真实 repo。
3. make smoke / make quality-check / make qoderwork-check 是否通过。
4. 当前会停在哪个人工 checkpoint。
5. 哪些后续操作需要我明确确认。
```

## Notes

- The source of truth repository is the user-provided `<REPO_ROOT>`.
- Offline smoke must not call LLM, DashScope, MinerU, retrieval, or image
  generation APIs.
- Kenqia-specific QoderWork CN validation notes live in
  `docs/local/KENQIA_LOCAL_VALIDATION.md`.
- Codex-simulated QoderWork manual flow QA is not the same as actual QoderWork
  CN product-run validation. Phase 5i records a real QoderWork CN product run
  at HEAD `7b9a8af`; a latest-HEAD product revalidation remains optional.
