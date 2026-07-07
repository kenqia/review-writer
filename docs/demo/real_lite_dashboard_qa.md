# Real-Lite Dashboard QA

## Goal

Phase 5c verifies that the local dashboard can display the real-lite E2E output
package generated under:

```text
<OUTPUT_ROOT>
```

The QA target is dashboard payload coverage and local file-access safety. It does not attempt a full scientific review.

## Displayed Artifacts

The dashboard now supports a direct E2E output root in addition to the older `review-projects/<project_id>` layout. For the real-lite output root it exposes:

- Library/project summary through `/api/projects`
- Discovery candidates
- Literature matrix and outline
- Section plan
- Section draft summary
- Figure manifest summary
- Final draft
- Final audit report
- Quality report JSON and Markdown
- Checkpoint log

## Checkpoint Log

The endpoint below returns the real-lite checkpoint log:

```text
/api/checkpoints
```

The Final payload also includes `checkpoint_log`, so the Final page can show all 9 checkpoint states alongside quality gate status.

## File Access Safety

The dashboard file endpoint remains constrained to the configured `review_root`.

Validated cases:

- `/file?path=/etc/passwd` returns `403`
- `/file?path=../../../../etc/passwd` returns `403`
- a file inside `<OUTPUT_ROOT>` is readable

## Run

```bash
make dashboard-real-lite-check
```

This test starts the dashboard on `127.0.0.1`, verifies payloads, checks file sandboxing, and then shuts the server down.

## Safety Boundary

- No network beyond loopback localhost.
- No PDF read.
- No MinerU API.
- No Qwen call.
- No upload.
- No Bailian knowledge base.
- No image generation.

## Current Limits

- This is real-lite, not a full review project.
- The final draft is a workflow skeleton, not final review quality.
- The figure is a pointer/placeholder.
- The test checks payloads and endpoint behavior; visual browser screenshot QA can be a later pass if the layout changes materially.

## Next Stages

- Phase 5d: eval baseline.
- Phase 5e: QoderWork CN manual real-lite flow.
- Phase 6: Bailian RAG preflight.
