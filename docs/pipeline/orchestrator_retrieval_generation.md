# Orchestrator Retrieval Generation

## Purpose

Phase 7 adds a single-section, retrieval-grounded generation pilot that connects a safe EvidencePack, one generation provider, and grounded-section validation.

Default behavior is fully offline:

```bash
make retrieval-generation-check
make grounded-section-check
make phase7-pilot-dry-run
```

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
