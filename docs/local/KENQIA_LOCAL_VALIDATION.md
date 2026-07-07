# Kenqia Local Validation

This file records one developer's local validation environment.
It is not a default path guide for general users.
Do not copy these paths into generic skills or product docs.

## Environment

- WSL repo path used for validation: `/home/kenqia/my_folder/review-writer`
- QoderWork CN skill install dir used for validation:
  `/mnt/c/Users/26960/.qoderworkcn/skills`
- Previous incorrect Windows Desktop path:
  `C:\Users\26960\Desktop\review-writer`
- Real-lite output root used during validation:
  `/tmp/review_writer_real_lite_e2e`

## QoderWork CN Validation Notes

- The five `chem-review-*` skills were installed into the QoderWork CN skill
  directory above during local validation.
- QoderWork CN successfully loaded `chem-review-orchestrator`.
- QoderWork CN could access the real WSL repo through:

```powershell
wsl.exe --cd /home/kenqia/my_folder/review-writer bash -lc "make smoke && make quality-check && make qoderwork-check && git status --short"
```

## Desktop Wrong Path Incident

The path below was used once during an incorrect smoke attempt and represented
an empty or wrong project root:

```text
C:\Users\26960\Desktop\review-writer
```

Do not use that path as a generic `review_root`.

## Real-Lite Manual Flow Result

During local validation, the real-lite output root contained 9 checkpoints:

```text
Library -> Discovery -> Matrix -> Blueprint -> Sections -> Figures -> Draft -> Final -> Export
```

The run summary recorded no network, PDF read, Qwen call, MinerU API call, or
upload.
