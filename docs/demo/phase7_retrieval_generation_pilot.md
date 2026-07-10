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

## Safety

- PDF uploaded: no
- raw image uploaded: no
- full paper text uploaded: no
- default checks upload: no
- resource ids committed: no
- model output marked final scientific review: no
