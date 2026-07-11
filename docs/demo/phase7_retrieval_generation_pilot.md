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

The final controlled Phase 7 pilot completed after offline gates and real
preflight passed:

```text
clean 3-paper compact payload
-> temporary Bailian retrieval
-> EvidencePack
-> one Qwen generation request
-> grounded validation
-> cleanup
```

Result:

- unified environment: `review-writer-bailian`
- installed Qwen dependency: `openai==1.93.0`
- `python -m pip check`: pass
- `make phase7-real-preflight`: pass, `network_calls=0`
- Qwen-only streaming smoke: pass
- Full Bailian + Qwen E2E: pass
- model: `qwen3.7-plus`
- thinking: disabled
- external search: disabled
- transport modes: Bailian `no_proxy`; Qwen `openai_sdk_default`
- dedicated endpoint: used and redacted in reports
- retrieval evidence count: `3`
- EvidencePack hash prefix: `02ded82c3494`
- stream started: `true`
- Qwen-only stream: `server_chunks_received=122`, `content_chunks_received=119`, `finish_reason=stop`
- full E2E stream: `server_chunks_received=106`, `content_chunks_received=103`, `finish_reason=stop`
- claim-evidence coverage: `1.0`
- unsupported claims: `0`
- unsupported citations: `0`
- prompt leakage: `0`
- malformed marker count: `0`
- checkpoint: `Sections: ready_for_human_review`
- temporary file cleanup: pass
- temporary index cleanup: pass
- final budget ledger: Qwen-only attempts `1`, full E2E attempts `1`, Qwen total requests `2`, Bailian lifecycles `1`, uploads `1`
- trusted as final scientific text: no

Safe report paths:

```text
/tmp/review_writer_phase7_real_qwen_only_1.json
/tmp/review_writer_phase7_real_qwen_only_1.md
/tmp/review_writer_phase7_real_full_e2e_1.json
/tmp/review_writer_phase7_real_full_e2e_1.md
```

## Safety

- PDF uploaded: no
- raw image uploaded: no
- full paper text uploaded: no
- default checks upload: no
- resource ids committed: no
- model output marked final scientific review: no
- Phase 7 automatically proceeds to human scientific evidence review: no
