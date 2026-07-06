# QoderWork CN Smoke Prompts

Use these prompts inside QoderWork CN after installing the review-writer
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

## 2. WSL Repo Command Smoke

This checks that QoderWork CN can reach the real WSL repository and run offline
Makefile checks. It must use the WSL repository path as the source of truth.

```text
请使用 chem-review-orchestrator skill 做 WSL repo 命令 smoke test。

必须使用真实 repo：
/home/kenqia/my_folder/review-writer

禁止使用：
C:\Users\26960\Desktop\review-writer

禁止调用真实 API，禁止读取真实论文，禁止修改文件，禁止创建 smoke_test_report.md。

请只运行这一条命令：
wsl.exe --cd /home/kenqia/my_folder/review-writer bash -lc "make smoke && make quality-check && make qoderwork-check && git status --short"

最后请只用 5 条以内总结：
1. 是否加载了 chem-review-orchestrator skill。
2. 是否识别到真实 WSL repo。
3. make smoke / make quality-check / make qoderwork-check 是否通过。
4. 当前会停在哪个人工 checkpoint。
5. 哪些后续操作需要我明确确认。
```

## Notes

- The source of truth repository is `/home/kenqia/my_folder/review-writer`.
- The Windows Desktop path `C:\Users\26960\Desktop\review-writer` is an empty
  mistaken path and must not be used as `review_root`.
- Offline smoke must not call LLM, DashScope, MinerU, retrieval, or image
  generation APIs.
