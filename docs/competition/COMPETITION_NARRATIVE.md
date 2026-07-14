# Competition Narrative

## 30-Second Product Definition

Researchers often need to combine facts from papers, supporting information,
tables, and figures, but a fluent model can silently mix reaction stages, bind a
number to the wrong condition, or erase a source conflict. Review Writer turns a
bounded scientific question and source set into a traceable evidence ledger,
uses an independent verification pass and deterministic rules to preserve
errors/conflicts, then asks Qwen to write only from accepted evidence. Every
sentence can be traced back to a claim and locator, and human feedback produces
an auditable version diff.

## One-Sentence Innovation

> The system treats grounded scientific synthesis as a versioned evidence-
> integration problem, not a one-shot generation problem.

## Three Core Values

1. **Traceability:** source inventory, atomic claims, locators, citations, and
   hashes remain connected from input to prose.
2. **Conflict-aware reliability:** entity/stage/locator errors and source-
   internal conflicts are surfaced instead of silently normalized into a smooth
   answer.
3. **Correctable workflow:** bounded Qwen generation, deterministic blockers,
   human feedback, and before/after diffs make failure visible and recoverable.

## Demonstrated Story: Case Study 01

Present the allene work as one deep case rather than the product's default
contract:

```text
Case Study 01 - Asymmetric Allene Chemistry
```

The useful story is:

1. Multiple papers and SI were inventoried and source identities checked.
2. Source-first Layer A produced 44 atomic claims across eight source units.
3. Independent Layer B verified all 44 and identified locator, reaction-stage,
   entity-binding, insufficient-evidence, and source-conflict outcomes.
4. Deterministic reconciliation retained seven internal source conflicts rather
   than choosing a convenient winner.
5. A DBA-related 76% condition binding was not permitted to survive as an
   unsupported scientific fact; bounded human feedback corrected the claim.
6. Qwen generated a representative synthesis candidate, but unsupported
   synthesis triggered a blocker rather than being accepted because it sounded
   plausible.
7. The salvage process separated 115 mixed validator findings into one real
   blocker, 102 deterministic representation fixes, and 12 warnings, then
   produced a traceable candidate with zero remaining blockers and one warning.
8. The final package includes sentence-to-claim mapping, citations, a diff, and
   a hash manifest.

This is an engineering case study with a small human spot check. It is not
publication-grade scientific validation.

## Competition Demo Story

1. A user chooses a Case 02 question and 3-5 staged scientific sources.
2. The UI shows source roles and an immutable run manifest.
3. The system builds a comparison table and evidence ledger.
4. The judge opens one numeric claim at its page/table locator.
5. The system highlights one missing or incompatible field and one retained
   conflict/non-comparability condition.
6. A three-arm panel compares Direct Qwen, RAG, and the full system.
7. The grounded synthesis view links each factual sentence to claims/sources.
8. One bounded feedback action produces a visible diff and updated manifest.
9. A redacted call manifest/screenshot proves Qwen/Bailian usage without exposing
   credentials.

## Honest Capability Boundary

The system supports bounded scientific evidence integration and grounded review
synthesis. It does not autonomously execute experiments, prove hypotheses,
guarantee publication-grade accuracy, or demonstrate broad cross-domain
generalization. The competition MVP should claim two demonstrated cases, not a
universal scientific agent.

## Statements Not To Use

- "fully human verified" or "scientifically verified";
- "publication-ready without expert review";
- "autonomous end-to-end scientific discovery";
- "works across all scientific domains";
- "eliminates hallucinations";
- "builds a complete research closed loop" when no experiment or simulation
  feedback is involved;
- "all 115 errors were model hallucinations";
- "tests passed, therefore scientific accuracy is guaranteed".

## Keep Out Of The Main Story

- the full V2/V3/V3.1/V3.1.1 validator history;
- every regression test and internal checkpoint;
- local paths and long hash lists;
- private calibration values or decision records;
- low-level debugging details from one failed response.

Those details remain available in an appendix or reproducibility package when a
judge asks how the engineering evidence was produced.

