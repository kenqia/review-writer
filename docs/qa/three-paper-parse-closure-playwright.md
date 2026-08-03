# Three-paper Parse Closure Playwright Protocol

## Scope

Act as a simulated researcher in the visible Dashboard for the named three-paper project. Your saved decisions are scientific approvals for this simulation and must remain attributed to `simulated_researcher_agent`. Do not claim to be the project owner.

## Main-agent Preflight

Before dispatching the browser agent, the main agent must verify `command -v pdftoppm`, render page 1 from one Source Truth-bound PDF through `render_pdf_page()`, and confirm the Dashboard page-preview endpoint returns `image/png`. If any check fails, stop with `PDF_PREVIEW_UNAVAILABLE`; the browser agent must not replace visual PDF comparison with downloads, internal files, or direct API calls.

## Allowed Evidence

Use only the PDF and parsed-text previews exposed by the Dashboard. Compare every reviewable object individually. Do not read repository files or internal JSON, use shell commands, call Dashboard APIs directly, or inspect browser storage, cookies, sessions, or network payloads.

## Decision Rule

For every unresolved object, inspect the reported issue, the relevant parsed text, and the corresponding visible PDF location before choosing one action:

- **Confirm candidate extraction** only when the visible PDF supports the candidate parse closely enough for downstream evidence work.
- **Use original PDF locator only** when the PDF is usable but the parsed representation is unreliable or incomplete.
- **Require reparse** when neither the displayed parse nor the visible PDF location is sufficient for reliable downstream work.

Write a concrete object-specific reason. Do not bulk-select one action or reuse generic notes across objects.

## Completion Checks

1. Resolve every object that offers researcher controls across all three studies.
2. Refresh the page and confirm the decisions remain visible.
3. Confirm the summary reports 3 studies, 21 objects, 0 needing review, and that the workflow can continue.
4. Report the action and reason for each decided object, plus any UI or scientific-review problem encountered.
5. Report `READY_FOR_SERVER_RESTART`; after the main agent restarts only its own Dashboard process, refresh again and verify persistence.

## 2026-07-29 Execution Record

The independent Playwright researcher closed all 11 reviewable objects through the visible Dashboard. The action distribution was 3 confirmed candidate extractions, 8 original-PDF-only decisions, and 0 reparse requests. Before restart, a hard refresh moved the project past Parse Quality; after the main agent restarted only the Dashboard on port 52801, another hard refresh showed the parse stages complete, all three studies available to downstream work, and DOCX export still disabled because the downstream evidence-to-release workflow was incomplete.

Observed UI issues to carry into the Dashboard integration task:

- Switching studies correctly warned about one unsaved decision; saving that object separately resolved the warning.
- The top-level overview and Parse card briefly disagreed on the remaining count (`8` versus `4`) until a later refresh.
- Page navigation requires Enter/change commit, and the preview can show the previous page for about one second while rendering.
- Automatic stage advancement hides the final 21-object/0-pending summary, so post-restart persistence is visible only through completed-stage and downstream-enabled states.
- After Parse closure, the visible workspace advances to the legacy manuscript label even though the authoritative workflow projection reports `active_stage=evidence` and `paper_evidence_ready=false`; Task 7 must replace this legacy stage mapping when the Evidence and Synthesis workspaces are connected.
