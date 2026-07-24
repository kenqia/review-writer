# Product Positioning

## Current Product

The repository is currently best described as a **chemistry-oriented review
workflow with a demonstrated, case-specific scientific evidence verification
pipeline**. Among the five audit choices, it sits between:

```text
2. chemistry-domain review agent
3. general multi-source scientific evidence integration system
```

It is not yet a general system under choice 3 because the executed Phase 7/8
path binds paper IDs, source units, claim counts, section structure, and
reconciliation assumptions to the allene case. It is not a complete AI Scientist
under choice 4 because it does not demonstrate hypothesis generation,
experimental planning/execution, or feedback from experiments. It is more than
a validator collection under choice 5 because a real Qwen/Bailian path, an
evidence ledger, independent claim verification, grounded synthesis, a human
review surface, and deterministic correction have all run.

## Competition Product Definition

The intended product is:

> A Qwen- and Alibaba Cloud Bailian-based, traceable scientific evidence
> integration and Grounded Synthesis assistant. Given a research question and a
> bounded set of papers, supplements, or scientific records, it builds a source
> inventory and evidence ledger, locates and independently verifies claims,
> preserves conflicts and missing evidence, incorporates bounded human feedback,
> and produces a cited synthesis with an auditable before/after diff.

This is a productization target, not a claim that every element is currently
available through one generic user-facing entrypoint.

## Capability Tiers

| Tier | Capability | Evidence | Assessment |
| --- | --- | --- | --- |
| Demonstrated | Qwen generation through Alibaba OpenAI-compatible endpoint | `reports/model_generation_manifest.json` in the frozen Phase 8B V2 external run records Qwen 3.7 Max, two bounded requests, token usage, redacted endpoint, and no API key | Real but case-specific |
| Demonstrated | Bailian create/index/retrieve/cleanup | `docs/rag/bailian_manual_success_record.md:5` and `docs/rag/bailian_retrieval_qa.md:5` | Real sanitized pilot, not product UI |
| Demonstrated | Source-first claim inventory, exact-claim verification, conflict retention | `docs/phase8/phase8a_status_report.md:7` | Strongest technical asset; allene case only |
| Demonstrated | Deterministic grounded-synthesis salvage and provenance hashes | `review_writer/phase8/phase8b_salvage.py:225`; external salvage report has zero blockers | Strong case evidence, not a generic service |
| Implemented | Provider abstractions and offline safety | `review_writer/providers/base.py`; `config/providers.example.yaml:7` | Reusable core |
| Implemented | Local multi-stage review dashboard and HTTP endpoints | `view/serve_review_dashboard.py:39` | Useful shell, not connected to Phase 8 evidence outputs |
| Documented/partial | End-to-end review orchestration | `skills/review-writing-orchestrator/SKILL.md:12` | Workflow exists, but its discovery and blueprint defaults remain allene-specific |
| Missing | One generic project manifest and command/API that accepts a new case without code edits | No repository-wide matches for `project_name`, `research_question`, `source_files`, `output_language`, `citation_style`, `human_review_policy`, or `privacy_policy` | Primary productization gap |
| Missing | Second clean-room execution and three-way baseline comparison | Only allene demo roots and fixtures exist | Generalization not demonstrated |

## Case Study 01

All allene-specific assets should be presented as:

```text
Case Study 01 - Asymmetric Allene Chemistry
```

The case demonstrates depth: main-paper/SI identity handling, 44 extracted
claims, independent verification, seven retained source-internal conflicts,
four bounded spot checks, and a grounded synthesis candidate. Its IDs, fixed
counts, classification rules, and frozen hashes remain case fixtures or audit
records. They must not define the product's default schema.

## Honest Boundary

The repository demonstrates an evidence-grounded scientific review loop in one
chemistry case. It does not yet demonstrate domain-independent scientific data
integration, autonomous scientific discovery, publication-grade validation, or
an experimental research loop.
