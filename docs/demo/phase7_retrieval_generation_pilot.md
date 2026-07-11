# Phase 7 Retrieval Generation Pilot

## Offline Replay

Latest offline dry-run:

- retrieval mode: `offline_fixture`
- generation provider: `offline`
- status: pass
- checkpoint: `Sections: ready_for_human_review`
- claim-evidence coverage: `1.0`
- unsupported claim count: `0`
- prompt leakage count: `0`

Output root:

```text
/tmp/review_writer_phase7_offline
```

## Real Controlled Pilot

One real controlled attempt was made after offline gates passed:

```text
clean 3-paper compact payload
-> temporary Bailian retrieval
-> EvidencePack
-> one Qwen generation request
-> grounded validation
-> cleanup
```

Result:

- real retrieval: reached Qwen generation stage
- Qwen generation: failed with read timeout
- validation: not run for real output
- checkpoint: blocked before `Sections: ready_for_human_review`
- cleanup: attempted before generation; follow-up file sweep found `0` clean payload file candidates

No second Qwen request was made.

## Real Generation Closure Update

Latest local preflight:

- `make phase7-real-preflight`: pass
- network calls: `0`
- provider dependency in active base environment: `openai` importable
- env report: SET/MISSING only
- dedicated endpoint metadata: redacted; reports keep only region and boolean use

Qwen-only smoke:

- first Qwen-only request: failed before section validation with a first-byte style timeout boundary
- one evidence-backed retry: produced a section from the offline sanitized EvidencePack
- revalidated grounding after validator heading/truncated-marker fix: pass
- claim-evidence coverage: `1.0`
- unsupported claims: `0`
- unsupported citations: `0`
- prompt leakage: `0`
- checkpoint: `Sections: ready_for_human_review`

Full Bailian + Qwen E2E:

- status: incomplete at local dependency/API-contract boundary before resource creation
- active base environment: Qwen `openai` dependency available, Bailian SDK contract incomplete
- `review-writer-bailian` environment: Bailian SDK available, `openai` missing
- Bailian temporary index lifecycles created: `0`
- Bailian file uploads: `0`
- final Qwen generation for full E2E: not sent

Install real Qwen dependency only in the project/conda environment used for the
full pilot:

```bash
python -m pip install -r requirements-qwen.txt
```

## Safety

- PDF uploaded: no
- raw image uploaded: no
- full paper text uploaded: no
- default checks upload: no
- resource ids committed: no
- model output marked final scientific review: no
