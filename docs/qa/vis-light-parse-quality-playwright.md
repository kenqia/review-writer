# Visible-light Parse Quality Playwright Protocol

## Role And Boundary

Act as a chemistry researcher reviewing three visible-light olefin difunctionalization papers in a local evidence workbench. Judge whether the interface supports careful human decisions; do not judge the scientific correctness of the papers on behalf of the project owner.

This is a fresh, read-only Artifact Reviewer session. The reviewer receives only the dashboard URL, this protocol, and the researcher persona. It must not read the repository, inspect project files, inspect browser cookies or storage, modify project files directly, or fix implementation defects.

## Allowed Browser Operations

Use Playwright through either an isolated MCP browser session or an explicitly approved Inline Execution session for:

- navigation, tabs, accessibility snapshots, and find;
- click, fill/type, key press, and resize;
- screenshots, console messages, network request lists, and bounded waits;
- closing the browser page when the review is complete.

For Inline Execution, shell access is only a transport for launching the existing Playwright runtime. Temporary scripts and screenshots must stay under a task-specific `/tmp` directory. Do not install or upgrade browsers or packages, read repository or project files, or reuse another reviewer's browser session.

Do not use `browser_run_code_unsafe`, `browser_evaluate`, browser storage inspection, file upload, or direct network request body inspection. Never reveal internal identifiers returned by the page.

## Test Sequence

1. Navigate to the supplied `/review` URL at `1440x1000`.
2. From visible UI only, state the current project stage and recommended next action.
3. Confirm that the parse quality workspace shows three studies and object-level checks.
4. For the first study, open or switch between the original PDF and parsed-text preview. Report whether both are reachable and whether the comparison controls are understandable.
5. Choose one visible object that requires a decision. Select the least permissive action that still allows manual evidence work, enter the note `黑盒验收：已回看原始 PDF，后续仅人工定位。`, and save that one object.
6. Confirm the saved state from visible UI, refresh the page, and confirm the same decision and note remain visible.
7. Pause and report `READY_FOR_SERVER_RESTART`; do not restart the server yourself.
8. After the Implementation Owner confirms restart, refresh and confirm the same decision and note remain visible.
9. Inspect `1440x1000`, `1024x900`, and `390x844`. At each viewport check text fit, horizontal overflow, overlapping controls, stable status badges and save buttons, preview behavior, and study/object navigation.
10. Use keyboard focus navigation on the decision controls, note field, save action, preview modes, and new-tab link. Report missing focus indicators or inaccessible labels.
11. Review Playwright console messages at warning level and network request list. Do not inspect request or response bodies.
12. Close the page and return the report. Do not edit code or project files.

## Evidence And Report Format

Capture screenshots for the initial desktop view, the saved decision after refresh, the tablet view, and the mobile view. Use relative screenshot filenames prefixed with `vis-light-parse-quality-`.

Report each finding as one row with these fields:

| Field | Required content |
| --- | --- |
| ID | Stable `PQ-###` identifier |
| viewport | Width x height |
| action | Exact visible operation performed |
| expected | Expected researcher-visible behavior |
| observed | What the browser visibly showed |
| severity | `P0`, `P1`, `P2`, `P3`, or `PASS` |
| category | `workflow`, `persistence`, `visual`, `accessibility`, `console`, `network`, or `language` |
| screenshot | Screenshot filename or `none` |
| blocks release | `yes` or `no` |

End with exactly one overall result: `PASS`, `BLOCKED`, or `ENVIRONMENT_UNDETERMINED`.

## Pass Rule

Pass requires:

- zero P0 or P1 findings;
- zero console errors or warnings;
- no horizontal scrolling or incoherent overlap at any required viewport;
- the saved decision and note survive refresh and server restart;
- ordinary visible UI never exposes local paths or the words `hash`, `schema`, `JSON`, `Agent`, or `Prompt`;
- the reviewer can distinguish automatic candidate extraction, manual PDF location, and required reparse without implementation knowledge.

P2 findings that could change or obscure a scientific decision block release. Other P2/P3 findings remain actionable but do not automatically block this slice.
