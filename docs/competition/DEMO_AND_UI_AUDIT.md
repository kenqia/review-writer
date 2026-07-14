# Demo, UI, and API Audit

## Verdict

There is enough UI/API foundation to reuse, but not enough integration for a
judge-ready product. Reuse the existing local server, stage navigation, project
selection, document rendering, and filesystem payload builders. Add a light
competition demo shell or focused routes; do not build a new SaaS frontend.

## Existing Surfaces

### Review dashboard

`view/serve_review_dashboard.py` provides:

- eight stage pages (`/library` through `/final`) at lines 39-60;
- project, paper, discovery, checkpoint, project-stage, metadata, Markdown, and
  bounded file-read endpoints at lines 63-101;
- metadata/discovery/draft writes at lines 105-120;
- DOCX export at lines 122-164;
- project-root path controls at lines 344-378;
- localhost execution with configurable root/port at lines 813-817.

The frontend can select a project, inspect metadata and source files, edit a
draft (`view/assets/dashboard/draft.html:255`), view final reports, and export
DOCX (`view/assets/dashboard/final.html:44`). Dashboard payload tests for both
clean-three-paper and real-lite fixtures passed during this audit.

### Phase 8 evidence viewer

`scripts/review/serve_phase8_evidence_review.py` provides a separate localhost
viewer with `/api/queue` and restricted file reads (lines 66-79). It is
intentionally read-only: POST/PUT return 405 (lines 81-85), and users submit
decisions through guided chat. It displays candidate, locator, and short
evidence but is tied to `local/phase8_evidence` (lines 35-37).

### Decision writer

`scripts/review/record_phase8_decision.py` implements validation, append/fsync,
re-read verification, recovery, backups, and progress/resume reports. It is a
strong audit component, but its event contract and fixed human budget belong to
Case 01 rather than a general feedback API.

## Judge Workflow Coverage

| User action | Current ability | Evidence | Product gap |
| --- | --- | --- | --- |
| Enter research question | Missing | No generic runtime `research_question` field | Add project-create form/API using a project manifest |
| Upload/select sources | Partial | Existing library and file paths; no upload route | For MVP, allow selecting local staged files and optionally bounded upload to an external case directory |
| See processing progress | Partial | Eight-stage strip and `/api/checkpoints` | Phase 8/Case 02 stages are not represented in the same progress model |
| Inspect claim/evidence/conflict | Partial | Phase 8 read-only queue; figure/source pages | No final-claim/conflict viewer in main dashboard |
| Click synthesis sentence to source | Missing | Sentence-claim JSONL exists only in external salvage artifact | Add sentence-to-claim-to-locator drill-down |
| Submit Accept/Revise/Flag | Partial | Metadata/draft PUT and external decision writer | No bounded evidence/sentence feedback endpoint/UI |
| See before/after version | Partial | Salvage diff and draft/final pages | No side-by-side diff view |
| Call test API | Partial | Local HTTP routes exist | No stable case create/run/status/result contract |

## Existing But Unconnected

- Multi-stage project navigation and Phase 8 evidence review.
- Draft editing and append-only scientific decision recording.
- Source/figure display and claim evidence locators.
- Checkpoint summaries and external run manifests.
- Final document view and Phase 8B before/after diff.

The productization task is data-contract integration, not visual reinvention.

## Minimum Demo Additions

1. Project page: research question, domain, source selection, language, citation
   style, provider, human/privacy policy.
2. Run page: deterministic stage status and failure/recovery state.
3. Evidence page: source inventory, claims, locators, missing fields, and
   retained conflicts.
4. Synthesis page: sentence-level provenance, Accept/Revise/Flag, and before/
   after diff.
5. Read-only test API for project manifest, status, evidence summary, synthesis,
   and provenance manifest; a bounded feedback endpoint only if needed for the
   live demo.

## Stable Ten-Minute Happy Path

1. Open a pre-staged Case 02 project and show its research question/sources.
2. Start or replay a deterministic prepared run; show stage progress rather than
   waiting for live PDF parsing.
3. Open one extracted numeric claim and jump to its source locator.
4. Show one missing/incompatible field and one retained source conflict.
5. Compare Direct Qwen/RAG/full-system outputs on the same question.
6. Open grounded synthesis, click a sentence to reveal its supporting claims.
7. Submit one non-scientific demo feedback action or replay a pre-recorded safe
   feedback event; show the diff and manifest.
8. Show the redacted Qwen/Bailian invocation evidence and reproducibility hash.

Do not depend on a long live model call, a new knowledge-base upload, or private
source access during the presentation.

