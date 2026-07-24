# Competition Official Requirements Baseline

Audit date: 2026-07-15 (Asia/Shanghai)

## Source Policy

Only the competition's Alibaba Cloud University page and Alibaba Cloud official
documentation are treated as authoritative for competition requirements.
Third-party summaries are not used.

| Source | Official URL | Evidence used |
| --- | --- | --- |
| 2026 Challenge Cup Alibaba Cloud problem page | <https://university.aliyun.com/action/tzbjbgs2026> | problem statement, tracks, submission format, scoring, model/platform requirements, optional demo deliverables |
| First Qwen API call | <https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen> | Bailian activation, API-key setup, environment-variable handling, Qwen API invocation |
| Qwen text generation API reference | <https://help.aliyun.com/zh/model-studio/qwen-api-reference/> | official model API and supported interface families |

## Confirmed Requirements

The official competition page states that:

- The foundation model must use the Qwen model family.
- The development platform must invoke the model through Alibaba Cloud Bailian,
  or through a competition-recommended Alibaba Cloud tool such as QoderWork,
  Qoder, or Miaowu.
- The team must provide invocation credentials or screenshots. The repository
  should continue to store only redacted evidence; the submission can contain a
  separately prepared screenshot that reveals no secret.
- The technical proposal is a PDF of no more than 20 pages.
- The proposal must include the research problem and solution, architecture,
  representative test cases, source code, workflow, context-engineering design,
  data or material sources, result display, and the feedback/iteration process.
- An interactive frontend, a callable test API, and a demo video within 10
  minutes are recommended. The page also lists an interactive frontend and the
  video as optional submission materials.
- Scoring is 40% scientific value, 30% technical depth, and 30% application
  potential. Accuracy, result validation, feedback iteration, interaction,
  delivery completeness, and reproducibility are explicit scoring dimensions.

## Track Fit

The closest fit is:

```text
RECOMMENDED_TRACK_PENDING_REGISTRATION_CONFIRMATION
Track 2 -> Direction 1A: scientific data search, parsing, and integration
```

Direction 1A asks for a system that starts from a research objective or data
need, searches/parses/integrates heterogeneous scientific sources, aligns
fields, preserves provenance, and emits structured output suitable for later
analysis. It explicitly mentions papers, open databases, tables, supplements,
and image/chart data. Detecting and correcting missing data, duplicates, unit
inconsistency, or chart parsing errors, including correction after human advice,
is identified as a possible bonus.

The current product thesis matches this direction better than Track 1 because
the demonstrated closed loop ends in verified evidence integration and grounded
synthesis, not experiment execution or experimentally informed planning.

## Official API Implications

Alibaba Cloud's official Qwen quick-start documentation confirms that Bailian
can be called through an API key and recommends keeping the key in an environment
variable instead of source code. The repository's redacted provider manifests
and environment-presence-only checks are therefore appropriate evidence, but a
competition submission still needs a separately captured, redacted invocation
screenshot or organizer-accepted credential artifact.

## Known Unknowns

- The repository does not contain proof that the team has selected Direction 1A
  in the registration system.
- The official page showed the work-submission entry as not yet online at audit
  time; final portal-specific fields and evidence formats remain unknown.
- The official page does not say that a public production deployment, user
  accounts, billing, or multi-tenancy is required.
- Whether a redacted call manifest alone satisfies "invocation credentials or
  screenshot" must be confirmed against the final submission portal.
