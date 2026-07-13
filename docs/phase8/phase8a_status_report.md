# Phase 8A Human Review Package Status

- status: `HUMAN_REVIEW_REQUIRED`
- method label: `HUMAN_SPOT_CHECKED_AI_ADJUDICATION`
- methodology: Context-isolated three-layer AI adjudication with a small human spot check. Engineering validation only; not publication-grade scientific validation.
- human spot-check limit: `10` unique core items
- source documents: `6`
- SI identity status: `{'F3I': 'NO_SI_PUBLISHED_ON_OFFICIAL_PAGE', 'F47A': 'SI_VALIDATED', 'P403': 'SI_VALIDATED'}`
- F3I official SI status: `NO_SI_PUBLISHED_ON_OFFICIAL_PAGE`
- bibliography status counts: `{'BIBLIOGRAPHY_CANDIDATE_CONFIRMED': 2, 'BIBLIOGRAPHY_UNCONFIRMED': 1}`
- update query summary: `{'NO_UPDATE_FOUND_IN_CHECKED_SOURCES': 3}`
- SI incremental extraction items: `30`
- numeric candidates: `35`
- mechanism candidates: `3`
- figure candidates: `3`
- Phase 7 claims: `10`
- core queue size: `53`
- extended queue size: `115`
- core atomic mapping count: `53`
- Qwen calls: `0`
- MinerU calls: `0`
- network calls: `3`
- VERIFIED status present: `False`
- local package path: `local/phase8_evidence`
- dashboard command: `make phase8-dashboard-check && conda run -n review-writer-phase8 python scripts/review/serve_phase8_evidence_review.py --root local/phase8_evidence --host 127.0.0.1 --port 8787`

V3 audit verdict: `NO-GO`; frozen diagnostic evidence only.
V3.1 acceptance verdict: `NO-GO`; frozen and not executable.
V3.1.1 scientific source units: `8`.
V3.1.1 calibration source units: `1`, separate one-item spot-check workspace/session.
Scientific Layer A started: `False`.
Calibration Layer A started: `False`.
Layer B/C created: `False`.

Current checkpoint: PREPARED_FOR_SOURCE_FIRST_LAYER_A_V3_1_1.
Phase 8B has not started.
