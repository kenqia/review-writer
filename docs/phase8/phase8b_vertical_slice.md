# Phase 8B Grounded Revision Vertical Slice

Phase 8B is active on a branch created from the squash-merged Phase 8A result.
The first bounded, offline vertical slice reached:

```text
PHASE8B_GROUNDED_REVISION_VERTICAL_SLICE_COMPLETE
```

This is one representative-section integration exercise, not a whole-review
revision or publication-grade scientific validation.

## Result

- Phase 7 sentences reconstructed and assessed: `10`
- Phase 8A final claims accounted: `44/44`
- Non-conflict claims available: `37`
- Claims used in this vertical slice: `12`
- Available claims not selected for this slice: `25`
- Source-internal conflicts retained outside prose: `7`
- New human decisions: `0`
- Human budget remaining: `0`
- Network used: `false`

The external run contains the before section, grounded revision, unified diff,
sentence assessments, revised-sentence records, the 44-record
claim-to-sentence map, remaining-attention reports, and a SHA-256 manifest.
Scientific text and per-claim records remain outside Git.

## Provenance

```text
run ID:
phase8b_grounded_vertical_slice_20260714T125822Z

generator commit:
b660a7aa3f1f264e8c6295b0443f8904e02e3e30

Phase 8A final claims SHA-256:
c2aae9212fe798f94e1aca3637d6c7ee24e0f6980c89c9c1e6fc870045c80352

Phase 8A closure manifest SHA-256:
cef91cc2b48fc40f20275e6db1d258d5adae3a295016d52893c2230d81d3a3cd

preserved Phase 7 claims SHA-256:
86fbe3c1328b1a836cb410cbcd120520209c3e1d5f728e385064aff98c4de894

vertical-slice hash manifest SHA-256:
00b53fd08a900c59e05f1ad14968edcbecb69448f33e79427d6e951f27b57d9b
```

The ignored external run is stored below the local `AI_REVIEW_WORKSPACES`
root under the run ID above. No external absolute path is published here.

## Boundary

The vertical slice uses `HUMAN_SPOT_CHECKED_AI_ADJUDICATION` outputs. All seven
retained source conflicts remain structured attention items and are not
asserted as single facts. The workflow created no additional human decision,
did not reopen Phase 8A, and did not process the rest of the review.
