# review-writer

`review-writer` is an offline-first literature-review workbench for chemistry
researchers. A user supplies a research question and a bounded set of main
papers and supporting information; the workflow preserves traceable evidence
and scientific disagreement, pauses for repeated user review, and produces a
revisable DOCX whose material claims can be traced back to source locators.

The final expert-facing deliverable is one clean DOCX. Evidence inventories,
claim registries, retrieval bundles, conflicts, revision histories, validation
reports, and hash manifests are internal product artifacts.

## Current status

The repository has a credible technical kernel and one deep chemistry case. It
is transitioning from a research-workflow codebase into a reusable product. It
is not yet a generic product, an AI Scientist, a fully autonomous writer, or a
publication-ready manuscript generator.

Case 01 remains a reference implementation, regression fixture, and audit
record. The next product work is to stabilize the case-neutral project,
artifact, and checkpoint contracts; run Case 01 v5 as a golden calibration;
then run a new 20-40-paper chemistry review without adding topic-specific
production code.

See the current authority documents:

- [Product North Star](docs/product/PRODUCT_NORTH_STAR.md)
- [Unified Checkpoint Contract](docs/product/CHECKPOINT_CONTRACT.md)
- [Product Roadmap](docs/product/PRODUCT_ROADMAP.md)
- [Architecture decision](docs/decisions/ADR-001-chemistry-first-evidence-governed-workbench.md)
- [Current product handoff](docs/handoff/PRODUCT_LEADER_CURRENT.md)

## Target user experience

The intended Windows-native QoderWork CN flow is:

1. clone or download the repository and open it as the current workspace;
2. put MAIN and SI files in a local project input directory;
3. provide a topic and the paper directory to one `chem-review-orchestrator`
   entry;
4. review only the current or affected task in a bilingual localhost dashboard;
5. approve, revise, request evidence, or exclude material, then resume;
6. receive one clean DOCX after scientific, consistency, and visual checks.

This single-prompt product entry is the accepted target and is **not yet a
complete supported command in the current repository**. Do not treat the
internal phase scripts as the future user interface.

## Execution and evidence boundary

- Offline preparation, hashing, deterministic validation, local checkpoint
  state, and export checks are the default.
- Qwen, Bailian, search providers, and other network execution are optional and
  require explicit project policy and user authorization.
- Default CI does not call providers, upload papers, or read credentials.
- Model-suggested sources remain candidates until source identity, required
  full text, and locators pass evidence governance.
- Final writing reads approved claims by default; missing support creates a
  blocking evidence issue instead of being filled from model memory or free
  retrieval.
- A self-reviewed draft is not an independently expert-reviewed release.

`Offline-first` does not mean `fully offline` when a selected model or search
provider requires a network connection.

## Local data safety

Generated paper libraries, source PDFs/SI, MinerU outputs, project outputs,
private review notes, and credentials are external data and must not be
committed. Keep real secrets out of the repository; document provider setup
only with `.env.example` and `config/providers.example.yaml`.

## Developer verification

Run deterministic local checks before any model or API step:

```bash
make smoke
make quality-check
```

More specialized historical Phase 6-8 and provider dry-run targets remain in
the [Makefile](Makefile) for regression and audit work. They are implementation
details, not the primary product quick start.
