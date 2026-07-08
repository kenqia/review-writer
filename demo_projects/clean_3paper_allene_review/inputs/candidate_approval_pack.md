# Clean 3-Paper Candidate Approval Pack

This approval pack turns the Phase 5j-A recommendation into a lightweight
decision page. It does not verify any scientific claim. It does not read PDF
bodies, call APIs, upload files, or create a knowledge base.

## Recommended Top 3

### 1. `F3I`

- Filename: `chem_papers/3i-Angew Chem Int Ed - 2012 - Yu - Allenes in Catalytic Asymmetric Synthesis and Natural Product Syntheses.pdf`
- Inferred title: Angew Chem Int Ed 2012 Yu Allenes in Catalytic Asymmetric Synthesis and Natural Product Syntheses
- Inferred year: 2012
- Inferred journal: Angew. Chem. Int. Ed.
- Role: `review_background`
- Evidence source: filename; candidate recommendation heuristics
- Confidence: medium
- Why selected: best background anchor for orienting allene synthesis, catalytic asymmetric synthesis, and natural product synthesis context.
- Risks: PDF body has not been read; metadata is inferred from filename only; claims, DOI, authors, figures, and citation details still require verification.
- `needs_pdf_read_verification: true`
- `human_verified: false`

### 2. `F47A`

- Filename: `chem_papers/47a-palladium-catalyzed-asymmetric-synthesis-of-axially-chiral-allenes-a-synergistic-effect-of-dibenzalacetone-on-high.pdf`
- Inferred title: Palladium catalyzed asymmetric synthesis of axially chiral allenes a synergistic effect of dibenzalacetone on high
- Inferred year: unknown
- Inferred journal: unknown
- Role: `representative_method`
- Evidence source: filename; candidate recommendation heuristics
- Confidence: medium
- Why selected: representative asymmetric/chiral allene method candidate with clear palladium catalysis and axial chirality signals.
- Risks: PDF body has not been read; year and journal are unknown from filename; metadata is inferred from filename only; claims, DOI, authors, figures, and citation details still require verification.
- `needs_pdf_read_verification: true`
- `human_verified: false`

### 3. `P403`

- Filename: `chem_papers/pd-catalyzed-asymmetric-allenylation-of-secondary-phosphine-oxides-with-enyne-type-propargylic-carbamates-for-the.pdf`
- Inferred title: Pd-Catalyzed Asymmetric Allenylation of Secondary Phosphine Oxides with Enyne-Type Propargylic Carbamates for the Construction of Chiral Allenyl Phosphine Oxides
- Inferred year: 2025
- Inferred journal: ACS Catal. 2025
- Role: `recent_progress`
- Evidence source: filename; real-lite metadata; selected_papers.candidates.json
- Confidence: medium
- Why selected: recent-progress candidate covering a 2025 palladium asymmetric allenylation example with committed real-lite metadata.
- Risks: PDF body has not been read; real-lite metadata may contain extraction artifacts; claims, DOI, authors, figures, and citation details still require verification.
- `needs_pdf_read_verification: true`
- `human_verified: false`

## Trio Coverage

- Background/review: `F3I`
- Representative method: `F47A`
- Recent progress: `P403`

This trio is balanced because it combines one overview-style background paper,
one focused asymmetric/chiral allene method, and one 2025 recent-progress
method candidate while keeping the next verification step to only three PDFs.

## Alternatives

### `P401`

- Can replace: `P403`
- Why it might be better: recent 2025 nickel-catalyzed reductive coupling candidate with real-lite metadata; useful if the user wants Ni rather than Pd as the recent-progress slot.
- Why not Top 3 now: `P403` better matches asymmetric/chiral allene synthesis and complements `F47A`.
- Risks: real-lite metadata still needs human cleanup; PDF body has not been read; claims and figures are unverified.

### `F4G`

- Can replace: `F3I`
- Why it might be better: likely broader catalytic allene synthesis review/background candidate focused on recent advances and critical assessment.
- Why not Top 3 now: `F3I` more directly signals catalytic asymmetric synthesis and natural product synthesis.
- Risks: metadata inferred from filename only; year and journal are unknown; PDF body has not been read.

### `F4A`

- Can replace: `F3I` or `F47A`
- Why it might be better: classic enantioselective synthesis of and with allenes candidate.
- Why not Top 3 now: it overlaps with the background role while `F47A` gives a more method-specific Pd/axial-chirality slot.
- Risks: metadata inferred from filename only; PDF body has not been read; claims and figures are unverified.

### `F14`

- Can replace: `F47A`
- Why it might be better: copper-catalyzed enantioselective axially chiral allene candidate.
- Why not Top 3 now: `F47A` was preferred as a palladium representative method.
- Risks: metadata inferred from filename only; year and journal are unknown; PDF body has not been read.

### `F24A`

- Can replace: `F47A`
- Why it might be better: gold-catalyzed highly enantioselective axially chiral allene candidate.
- Why not Top 3 now: `F47A` was preferred as a more central palladium asymmetric allene method candidate.
- Risks: metadata inferred from filename only; year and journal are unknown; PDF body has not been read.

### `C2024-angew-chem-int-ed-2024-wen-remote-enantios`

- Can replace: `P403`
- Why it might be better: 2024 Angewandte remote enantioselective copper ethynylallenylidene candidate.
- Why not Top 3 now: it is filename-only, while `P403` has committed real-lite metadata and a clearer selected-paper path.
- Risks: metadata inferred from filename only; PDF body has not been read; claims, DOI, authors, and figures are unverified.

## User Decision

Choose one:

```text
Option A: accept Top 3
Option B: replace candidate ___ with alternative ___
Option C: regenerate candidates with changed topic focus
```

## Next-Stage Authorization

If you accept the Top 3, the next phase can request this exact authorization:

```text
allow read-only verify top 3 PDFs
```

Authorization scope:

- read only these 3 PDFs
- do not read full `chem_papers`
- do not upload files
- do not call external APIs
- do not create a knowledge base
- extract title/authors/year/DOI/abstract/key claims/figure notes only
- output a verified metadata draft that still requires human review
