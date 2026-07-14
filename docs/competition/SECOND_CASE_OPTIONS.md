# Second Clean-Room Case Options

No source has been downloaded or scientifically verified as part of this audit.
Each option requires a source-availability and license preflight before it is
selected.

## Recommendation

### 1. MOF Atmospheric Water-Harvesting Performance

Research question:

> Across 3-5 open-access primary studies and their supplements, how do reported
> water uptake or working capacity, relative humidity, temperature, and cycling
> conditions compare, and which values cannot be aligned without qualification?

Source types:

- 3-5 open-access primary papers;
- SI containing adsorption isotherms, tables, or cycling protocols;
- optional structured table exported from an open repository if provenance is
  explicit.

Why it tests generality:

- It is chemistry/materials science but not reaction-synthesis/allene work.
- It needs source roles, numeric extraction, condition binding, unit alignment,
  missing-field handling, table/figure locators, and conflict-safe synthesis.
- A merged comparison table maps directly to Track 2 Direction 1A.
- It can use a compact vocabulary without designing a domain ontology.

Human work:

- Confirm source identity and open-access availability.
- Define one page/table-level gold sheet for a small sample.
- Review ambiguous distinctions such as total uptake versus working capacity
  and equilibrium versus dynamic/cycling measurements.

Hardcodes it will expose:

- allene taxonomy and allenation rule pack;
- fixed paper IDs/citation order;
- reaction-stage-focused claim fields;
- 44/37/7 count requirements;
- P403-specific RAG preflight warnings.

Risks:

- Values are only comparable when humidity, temperature, activation, and cycle
  definitions are preserved.
- Some results may be figure-only and need bounded visual verification.
- Open-access SI availability must be checked before commitment.

Recommendation order: **1**. This is the clearest Direction 1A data-integration
demo and the best stress test for unit/condition alignment.

## Alternative 2. Photocatalytic Hydrogen Peroxide Production

Research question:

> How do 3-5 open-access photocatalytic H2O2 studies report production rate,
> selectivity, light source, sacrificial donor, catalyst mass, and stability, and
> which headline values are not directly comparable?

Source types: primary papers, SI optimization tables, and catalyst/irradiation
condition tables.

Why it tests generality: it remains chemistry, includes numeric outcomes and
conditions, and has frequent unit/normalization risks without needing a large
ontology.

Human work: source selection, metric normalization policy, and review of one
small table of rate/selectivity claims.

Expected hardcodes: all allene discovery/blueprint defaults, reaction-specific
entity mappings, fixed Case 01 citation map, and fixed counts.

Risks: reported rates can use incompatible denominators and irradiation areas;
"selectivity" definitions can differ. This is valuable but raises the manual
normalization burden.

Recommendation order: **2**.

## Alternative 3. Perovskite Solar-Cell Stability Reporting

Research question:

> For 3-5 open-access reports of one bounded perovskite device family, which
> initial efficiencies and T80/T90 stability results are supported by explicit
> test conditions, and where do protocol differences prevent comparison?

Source types: main articles, SI device tables, and stability plots/captions.

Why it tests generality: it emphasizes missing protocol fields, figure evidence,
unit/time alignment, and explicit non-comparability.

Human work: tightly constrain the device family, define minimum stability
conditions, and inspect a small set of plots.

Expected hardcodes: the same allene/citation/count assumptions plus chemistry
reaction-stage claim types that do not fit device measurements.

Risks: protocol heterogeneity can overwhelm a small MVP, and plot extraction can
become a separate computer-vision project.

Recommendation order: **3**.

## Selection Gate

Before PR B begins, the chosen case must pass all of the following:

- 3-5 lawful, accessible scientific sources are available locally;
- at least two source roles or modalities are present;
- one bounded research question can be answered in a short section and table;
- at least one missing/incompatible/conflicting field is plausible but not
  artificially planted;
- the run can finish without changing generic production code after PR A;
- private or licensed full text remains external and uncommitted.

