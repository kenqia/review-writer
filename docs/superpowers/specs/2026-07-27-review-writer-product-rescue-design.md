# Review Writer Product Rescue Design

Date: 2026-07-27
Status: Approved for implementation

## Goal

Repair the existing QoderWork CN plus localhost workflow for real review scale. Every change must improve scientific traceability, reduce researcher operations, or support reuse and scale. WSL branch feat/qoderwork-native-review-workbench is the sole development baseline; Windows receives one clean acceptance copy only after WSL verification.

## Product invariants

1. QoderWork calls maintained repository commands and semantic agents. It must not author one-off orchestration scripts, reviewer verdicts, risk decisions, citation repairs, or lineage repairs.
2. Brief, source upload and supplementation, Scientific Risk Packet, and final review are hard checkpoints. Backend commands cannot advance past unresolved checkpoints.
3. Researchers use ordinary scientific language and the localhost workbench; they never edit prompts, JSON, Git state, hashes, or paths.
4. One authoritative manuscript and lineage drive the workbench, figures, gates, and DOCX.

## Repair package 1: Checkpoint integrity

review_state.json remains canonical. Building a Risk Packet sets an awaiting-human state and invalidates earlier decisions. Applying decisions requires a complete current packet submitted through the dashboard. Writer packet, drafting, and release reject unresolved risk. All human checkpoints use the maintained wait-state command with bounded timeout and one safe resume instruction.

## Repair package 2: Reusable corpus intake

Before discovery or MinerU, audit a researcher library for reusable PDF, SI, MinerU output, text layers, and atom catalogs. Bind reuse by DOI where available and PDF SHA-256 otherwise; parser contracts must match. Never inherit claims, candidates, reviewer verdicts, risk decisions, manuscripts, or releases.

Discovery remains available but is not mandatory. The Sources UI accepts DOI/title additions and one ZIP containing MAIN, SI, or compatible MinerU material. Every study requires MAIN. SI is REQUIRED when scope, conditions, scale-up, negative results, controls, or mechanism evidence needed by the brief depends on it; otherwise SI is RECOMMENDED or NOT_REQUIRED. Missing required SI blocks only dependent claims.

Archive matching order is exact manifest alias, normalized DOI in filename, PDF metadata or first-page DOI, unique normalized title, then visible unresolved mapping. Ambiguous files are never guessed.

## Repair package 3: Canonical batch runner

A maintained bounded command performs deterministic preparation, assembly, R0 validation, validation of fresh Reviewer output, and registration. It persists after each study and reports ready, blocked, or waiting-for-provider. Deterministic stages consume no model credits; semantic extraction and Reviewer remain model roles and their outputs are immutable.

The Expert Kit rereads its contract and canonical project snapshot at every stage. Subagent completion is accepted only after expected machine-readable outputs validate. Chat context is never authority.

## Repair package 4: Authoritative draft and figures

Risk must be resolved before Writer Packet or drafting. Writer consumes approved claims only. Citations, lineage, images, and DOCX use maintained deterministic commands. Figure planning precedes drafting and permits only attributed licensed source figures, original evidence-derived figures, or clearly labelled figure-brief placeholders. Unknown-license figures and placeholders block final release.

## User flow

QoderWork topic -> Brief -> reusable-library report and discovery candidates -> optional paper additions -> MAIN/SI Sources and ZIP -> automatic processing and credit forecast -> mandatory Risk Packet -> manuscript studio and figures -> scientific edit review -> DOCX.

At every waiting point the same QoderWork task runs wait-state. Timeout safely stops and shows: 项目已安全保存；完成界面操作后发送“继续当前综述项目”.

## Acceptance

- Stale, incomplete, or generated Risk decisions cannot unlock writing.
- Matching source and parse assets are reused; changed PDFs are reparsed.
- Mixed-name ZIP members map deterministically or enter a visible unresolved queue.
- MAIN/SI coverage is visible per study and required SI is enforced only where evidence depends on it.
- The Expert Kit forbids ad hoc scripts and fabricated semantic outputs.
- The batch command pauses for missing semantic or Reviewer outputs.
- Sources supports supplementation, reuse status, ZIP upload, and unresolved mapping.
- Progress exposes study counts and measured credits without Agent or Prompt terminology.
- Draft, lineage, figures, and DOCX share one manuscript revision.
- Licensed or original figures are allowed; placeholders block final release.

## Non-goals

No cloud corpus service, account system, new workflow engine, second dashboard, automatic provider retry, fallback model, browser-driven paper download, remote push, PR, or deployment.
