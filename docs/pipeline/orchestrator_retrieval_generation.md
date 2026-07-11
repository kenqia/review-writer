# Orchestrator Retrieval Generation

## Purpose

Phase 7 adds a single-section, retrieval-grounded generation pilot that connects a safe EvidencePack, one generation provider, and grounded-section validation.

Default behavior is fully offline:

```bash
make retrieval-generation-check
make grounded-section-check
make phase7-pilot-dry-run
```

Real-generation preflight is local and must run before any Qwen or Bailian call:

```bash
make phase7-real-preflight
```

The preflight performs no network calls. It checks provider importability, safe
environment presence, request serialization, offline EvidencePack construction,
mock streaming parsing, timeout configuration, cleanup handler registration,
output writability, and prompt/token bounds. Reports must write only SET/MISSING
and redacted endpoint metadata.

Default modes:

```text
retrieval_mode=offline_fixture
generation_provider=offline
```

## Data Contract

`EvidencePack` may contain only:

- `paper_id`
- `chunk_id`
- `sanitized_text`
- `score`
- `title`
- `known_warnings`
- `needs_human_review`

It must not contain signed URLs, local paths, workspace ids, document ids, pipeline ids, or raw metadata.

## Checkpoint

The orchestrator-backed path stops at:

```text
Sections: ready_for_human_review
```

It must not proceed automatically to Figures, Draft, Final, or Export.

## Generation Contract

The provider may cite only:

```text
[F3I] [F47A] [P403]
```

It must not invent authors, DOI, yields, ee values, catalyst loading, mechanisms, or substrate scope. Missing evidence must be marked with `[NEEDS_EVIDENCE: ...]`.

Generated text remains an engineering pilot artifact, not a final scientific review section.

## Provider Boundary

`review_writer.pipeline.retrieval_generation` only orchestrates the safe
EvidencePack, prompt, provider invocation, grounded validator, and Sections
checkpoint. Real Qwen transport lives in `OpenAICompatibleProvider`, including
OpenAI-compatible endpoint construction, streaming, timeout metadata, and safe
failure reports.

Do not add urllib/http transport, Authorization headers, endpoint string
assembly, retry logic, or streaming protocol handling to the pipeline.

Real Qwen generation requires the `openai` package in the same project/conda
environment that runs the pilot. Use the project-scoped reproducible dependency
file:

```bash
python -m pip install -r requirements-qwen.txt
```

Do not install it globally just to satisfy a pilot run.
