# Provider qualification report

Status: `QUALIFIED_EXTERNAL_LEADER_GRADE_4` for the no-Schema Owner → same Owner resume → fresh read-only Reviewer workflow.

The route contract is qualified for natural-language transport: exact `codex-cli 0.144.5`, bundled Terra metadata verified, `gpt-5.6-terra`, explicit `custom` provider, `medium` reasoning, 600-second timeout, explicit sandbox, JSON events, and last-message capture. Workflow grade and contract mode are independent: workflow grade is `Grade 4 / Production External Leader`; contract mode is `natural_language_with_leader_extraction / qualified`.

Q0 route snapshot is recorded. Historical 0.142.4 evidence is Q1 plain exec 3/3, Q2 JSON events 2/2, Q4 resume 2/2, and Q5 one passing run per sandbox. The fresh 0.144.5 no-Schema metadata smoke is 1/1. Q3 Output Schema is unsupported (0/2 at 0.142.4 and 0/2 at 0.144.5) and is never used in production. Q6 passed 1/1 on 0.144.5: exactly three turns, all complete lifecycle fields, exact phase-1 write and contextual phase-2 replacement, same Owner resume, fresh Reviewer, Reviewer no-write inventory, and three non-empty natural-language last messages. Q7 native subagents remain disabled/unqualified.

The prior unknown model metadata condition was fixed by 0.144.5. An auxiliary 401 appeared in each Q6 turn but remained non-blocking because every main turn completed. Raw prompts, Worker prose, stderr, events, and opaque runtime references are intentionally excluded from this tracked report.

Grade 4 does not authorize parallel Writers, native subagents, fallback models, route drift, or automatic semantic acceptance. Human checkpoints and fresh review remain mandatory.

Upgrade condition: exact CLI version plus bundled Terra metadata must preflight. Rollback: return to known-good 0.144.5 outside this repository; do not introduce fallback or schema downgrade behavior. Legacy schemas remain historical, non-enforcing offline compatibility files.
