# Scaled Review Writer Vertical Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复用现有 QoderWork 插件、确定性证据工具、动态工作台和 DOCX 导出，以 Katritzky 盐脱氨官能团化为 Case 02，完成 20–30 篇真实研究的可追溯、可编辑规模化综述 benchmark。

**Architecture:** 本地确定性程序负责 discovery provenance、合法获取、PDF page text、locator、状态归并和导出；QoderWork CN/Qwen 只负责候选筛选、语义抽取、对抗审查、跨研究综合和写作。模型只选择本地生成的 evidence atom IDs，Writer 只读取 `APPROVED` claims。一个 authoritative manuscript 同时驱动动态工作台和 DOCX，科研用户正常只确认 Review Brief、集中 risk packet 和最终成品。

**Tech Stack:** Python 3 standard library、`jsonschema`、Poppler `pdftotext`/`pdftoppm`、QoderWork CN Expert Kit Markdown agents、Qwen3.7-Max、原生 HTML/CSS/JavaScript dashboard、现有 `md2docx.py` 导出器、OpenAlex/Crossref 公共 API。

---

## Scope guard

每个任务开始前必须回答：它是否直接提高综述科学质量、减少用户操作，或支持真实规模？若三项均否，跳过该任务。

本计划明确不做：新 Provider framework、Hook/receipt/法证平台、账户、多租户、云数据库、通用 RAG 平台、Case 02 专用生产代码、旧 M2 slash-agent 修补、装饰性 UI 重写。

真实 PDF、SI、parse、Qoder 输出和 Case 02 项目状态均位于 Git ignored 的 `review-projects/` 或 Windows-native benchmark workspace；只提交通用代码、合成 fixtures 和脱敏 benchmark report。

## File map

| Responsibility | Files |
| --- | --- |
| Public source acquisition | `review_writer/acquisition/public_corpus.py`, `review_writer/acquisition/supplement_identity.py`, `scripts/acquisition/acquire_public_corpus.py` |
| Scholarly discovery | `review_writer/discovery/scholarly.py`, `scripts/discovery/discover_scholarly_corpus.py` |
| Deterministic grounding | `scripts/evidence/build_pdf_text_layers.py`, `scripts/evidence/evidence_atom_core.py`, `scripts/evidence/build_page_atom_catalog.py`, existing atom assembler/validator schemas and scripts |
| Product projection | `review_writer/project/vertical_review.py`, `scripts/run_vertical_review.py` |
| QoderWork product entry | `qoderwork/plugins/research-review-writer/skills/research-review-writer/SKILL.md` and its six existing agents |
| Dynamic researcher UI | `view/serve_review_dashboard.py`, `view/assets/dashboard/review.html`, `view/assets/dashboard/draft.html` |
| Single-source release | `review_writer/delivery/project_release.py`, existing DOCX converter, dashboard export endpoint |
| Regression and scale gates | focused tests under `tests/`, one synthetic fixture under `tests/fixtures/scaled_vertical_review/`, `Makefile` |
| User and benchmark docs | `README.md`, `docs/qoderwork/research_review_writer_quickstart.md`, `docs/benchmarks/CASE02_SCALED_VERTICAL_BENCHMARK.md` |

### Task 1: Promote the proven public-corpus acquisition kernel

**Why:** Directly supports legal real-scale source acquisition and a single consolidated missing-source queue. Reuse the already tested M2 kernel without its M2-specific Make targets.

**Files:**
- Create: `review_writer/acquisition/__init__.py`
- Create: `review_writer/acquisition/public_corpus.py`
- Create: `review_writer/acquisition/supplement_identity.py`
- Create: `scripts/acquisition/acquire_public_corpus.py`
- Create: `tests/test_public_corpus_acquisition.py`
- Create: `tests/test_supplement_identity.py`
- Modify: `Makefile`

- [ ] **Step 1: Restore only the proven acquisition tests**

Use `apply_patch` to add the exact test contents from these known commits; do not cherry-pick their M2-specific Makefile changes:

```bash
git show 81b9179:tests/test_public_corpus_acquisition.py
git show 2071556:tests/test_supplement_identity.py
```

- [ ] **Step 2: Run the tests and confirm the missing package failure**

Run:

```bash
python3 tests/test_public_corpus_acquisition.py
python3 tests/test_supplement_identity.py
```

Expected: both fail because `review_writer.acquisition` is not yet present on this branch.

- [ ] **Step 3: Restore the case-neutral production files only**

Use `apply_patch` with the exact contents shown by:

```bash
git show 81b9179:review_writer/acquisition/__init__.py
git show 81b9179:review_writer/acquisition/public_corpus.py
git show 81b9179:scripts/acquisition/acquire_public_corpus.py
git show 2071556:review_writer/acquisition/supplement_identity.py
```

Do not restore `acquire-m2`, `verify-import-m2`, M2 paths, M2 agent files, or M2 documentation.

- [ ] **Step 4: Add one generic Make gate**

Modify `Makefile`:

```make
.PHONY: public-corpus-acquisition-check

public-corpus-acquisition-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_public_corpus_acquisition.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_supplement_identity.py
```

- [ ] **Step 5: Run the focused acquisition gate**

Run: `make public-corpus-acquisition-check`

Expected: all acquisition and supplement-identity tests pass without external network calls.

- [ ] **Step 6: Commit**

```bash
git add Makefile review_writer/acquisition scripts/acquisition tests/test_public_corpus_acquisition.py tests/test_supplement_identity.py
git commit -m "feat(acquisition): promote generic public corpus tooling"
```

### Task 2: Add reproducible OpenAlex/Crossref discovery with provenance

**Why:** Directly supports the 20–30-paper benchmark. This replaces the allene-specific eight-tag discovery path for the new product entry.

**Files:**
- Create: `review_writer/discovery/__init__.py`
- Create: `review_writer/discovery/scholarly.py`
- Create: `scripts/discovery/discover_scholarly_corpus.py`
- Create: `tests/test_scholarly_discovery.py`
- Modify: `Makefile`

- [ ] **Step 1: Write the failing discovery tests**

Create `tests/test_scholarly_discovery.py` with an injected fake transport and these assertions:

```python
from review_writer.discovery.scholarly import build_candidate_pool


def test_deduplicates_doi_and_retains_all_provenance():
    plan = {
        "schema_version": "scholarly-search-plan.v1",
        "from_year": 2017,
        "to_year": 2025,
        "queries": ["Katritzky salt photoredox", "deaminative pyridinium functionalization"],
        "seed_dois": ["10.1000/seed"],
    }
    transport = FakeTransport.with_duplicate_doi("10.1000/example")
    pool = build_candidate_pool(plan, transport=transport)
    rows = [row for row in pool["candidates"] if row["doi"] == "10.1000/example"]
    assert len(rows) == 1
    assert {item["query"] for item in rows[0]["provenance"]} == set(plan["queries"])
    assert pool["counts"]["unique_candidates"] == len(pool["candidates"])


def test_rejects_unbounded_years_and_empty_queries():
    bad = {"schema_version": "scholarly-search-plan.v1", "from_year": 2025,
           "to_year": 2017, "queries": [], "seed_dois": []}
    with pytest.raises(ValueError, match="search plan"):
        build_candidate_pool(bad, transport=FakeTransport())


def test_network_is_opt_in_at_cli_boundary(tmp_path):
    result = subprocess.run(
        [sys.executable, "scripts/discovery/discover_scholarly_corpus.py",
         "--plan", str(write_plan(tmp_path)), "--output", str(tmp_path / "pool.json")],
        text=True, capture_output=True,
    )
    assert result.returncode == 2
    assert "--allow-network" in result.stderr
```

The test file must define `FakeTransport`, `write_plan`, and imports explicitly; fixture responses must include two search queries, one seed work, backward references, and one forward citation.

- [ ] **Step 2: Run the tests and verify RED**

Run: `python3 -m pytest tests/test_scholarly_discovery.py -q`

Expected: FAIL with `ModuleNotFoundError: review_writer.discovery`.

- [ ] **Step 3: Implement the bounded discovery client**

Create `review_writer/discovery/scholarly.py` with this public interface and the algorithm immediately below it:

```python
def validate_search_plan(plan: dict) -> dict:
    if plan.get("schema_version") != "scholarly-search-plan.v1":
        raise ValueError("invalid scholarly search plan")
    queries = plan.get("queries")
    start, end = plan.get("from_year"), plan.get("to_year")
    if not isinstance(queries, list) or not queries or not all(isinstance(q, str) and q.strip() for q in queries):
        raise ValueError("search plan requires nonempty queries")
    if not isinstance(start, int) or not isinstance(end, int) or start > end:
        raise ValueError("search plan year range is invalid")
    return {**plan, "queries": list(dict.fromkeys(q.strip() for q in queries))}
```

Additional public call signatures are `UrllibScholarlyTransport.get_json(url, timeout_seconds) -> dict` and `build_candidate_pool(plan, transport, timeout_seconds=20.0) -> dict`. `build_candidate_pool` searches both OpenAlex and Crossref for every query, resolves each seed DOI in OpenAlex, performs one backward and one forward citation pass, normalizes every result into the fields below, then deduplicates in DOI → OpenAlex ID → normalized title order.

Implementation rules:

- fixed hosts `https://api.openalex.org` and `https://api.crossref.org` only;
- maximum 200 results per query and one bounded backward/forward chain pass per seed;
- normalize DOI by removing `https://doi.org/` and case-folding;
- candidate fields: `candidate_id`, `title`, `authors`, `year`, `journal`, `doi`, `openalex_id`, `landing_page_url`, `oa_locations`, `abstract`, `provenance`;
- no search hit becomes an included SourceRecord;
- errors become `warnings[]`; they do not silently erase results from other sources;
- sort candidates deterministically by year, DOI/title, and candidate ID.

Create `review_writer/discovery/__init__.py` exporting `build_candidate_pool`.

- [ ] **Step 4: Add the thin network-authorized CLI**

Create `scripts/discovery/discover_scholarly_corpus.py`:

```python
parser.add_argument("--plan", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--allow-network", action="store_true")
parser.add_argument("--timeout-seconds", type=float, default=20.0)
if not args.allow_network:
    parser.error("public scholarly discovery requires --allow-network")
pool = build_candidate_pool(load_json(args.plan), transport=UrllibOpenAlexTransport(),
                            timeout_seconds=args.timeout_seconds)
atomic_write_json(args.output, pool)
```

The output path must remain inside the selected project directory when called by the product runner; do not add API key or cookie options.

- [ ] **Step 5: Add and run the focused Make gate**

```make
.PHONY: scholarly-discovery-check
scholarly-discovery-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest tests/test_scholarly_discovery.py -q
```

Run: `make scholarly-discovery-check`

Expected: PASS using only fake transport data.

- [ ] **Step 6: Commit**

```bash
git add Makefile review_writer/discovery scripts/discovery tests/test_scholarly_discovery.py
git commit -m "feat(discovery): add reproducible scholarly candidate search"
```

### Task 3: Promote locator-first evidence atoms and automate page catalogs

**Why:** Directly fixes the observed Qwen grounding failures. Qwen will select atom IDs; it will never author source ID, page, quote, hash, locator, or coverage fields.

**Files:**
- Create from proven commits: `schemas/evidence/*.json`, `scripts/evidence/*.py`, focused evidence tests and fixtures listed below
- Create: `scripts/evidence/build_page_atom_catalog.py`
- Create: `tests/test_page_atom_catalog.py`
- Modify: `Makefile`

- [ ] **Step 1: Restore the proven grounding tests before production code**

Use `apply_patch` to restore these exact test/fixture paths from commits `c96dad1` and `6f27911`:

```text
tests/test_evidence_grounding_v2.py
tests/test_evidence_atom_vertical_slice.py
tests/fixtures/evidence_grounding_v2/**
tests/fixtures/evidence_atom_vertical_slice/**
```

Do not restore `.qoder/`, `.lingma/`, the obsolete `chem-review-evidence-extraction` plugin, M2 runbooks, or M2 Make targets.

- [ ] **Step 2: Run the restored tests and verify RED**

Run:

```bash
python3 tests/test_evidence_grounding_v2.py
python3 tests/test_evidence_atom_vertical_slice.py
```

Expected: FAIL because the evidence scripts and schemas are absent.

- [ ] **Step 3: Restore only the reusable grounding kernel**

Use `apply_patch` with exact contents from the named commits:

```text
c96dad1:scripts/evidence/build_pdf_text_layers.py
c96dad1:scripts/evidence/validate_evidence_candidate.py
c96dad1:schemas/evidence/evidence_candidate.v2.schema.json
6f27911:scripts/evidence/evidence_atom_core.py
6f27911:scripts/evidence/build_evidence_atoms.py
6f27911:scripts/evidence/assemble_evidence_candidate_from_atoms.py
6f27911:scripts/evidence/render_evidence_page_crop.py
6f27911:schemas/evidence/evidence_atom_catalog.v1.schema.json
6f27911:schemas/evidence/evidence_atom_semantic_decision.v1.schema.json
6f27911:templates/evidence/evidence_atom_semantic_decision.v1.template.json
```

Keep `pdftotext-default-reading-order` for exact quotes and `pdftotext-layout-visual-locator-only` for figures/tables.

- [ ] **Step 4: Write the failing automatic catalog test**

Create `tests/test_page_atom_catalog.py`:

```python
def test_builds_stable_page_local_atoms_from_reading_layers(tmp_path):
    source = tmp_path / "MAIN.reading.txt"
    source.write_text("First exact paragraph.\n\nSecond paragraph with 82% yield.\fSI page text.\f", encoding="utf-8")
    job_path = write_bound_job(tmp_path, source, page_count=2)
    first = build_page_atom_catalog(job_path, tmp_path)
    second = build_page_atom_catalog(job_path, tmp_path)
    assert first == second
    assert [atom["page"] for atom in first["atoms"]] == [1, 1, 2]
    assert first["atoms"][1]["raw_source_span"] == "Second paragraph with 82% yield."
    assert all(atom["source_id"] == "MAIN" for atom in first["atoms"])


def test_rejects_unbound_or_cross_page_text(tmp_path):
    with pytest.raises(PageCatalogError):
        build_page_atom_catalog(write_hash_mismatched_job(tmp_path), tmp_path)
```

The test file must define `write_bound_job` and `write_hash_mismatched_job` with complete reading/layout paths, hashes, page counts, job ID, study ID, and source records matching the restored atom contract.

- [ ] **Step 5: Run the automatic catalog test and verify RED**

Run: `python3 -m pytest tests/test_page_atom_catalog.py -q`

Expected: FAIL because `scripts.evidence.build_page_atom_catalog` is absent.

- [ ] **Step 6: Implement deterministic paragraph atoms**

Create `scripts/evidence/build_page_atom_catalog.py` using `verify_job_source_layers`, `canonicalize_text`, and `canonical_json_sha256` from `evidence_atom_core.py`:

```python
PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")


def page_spans(page_text: str) -> list[str]:
    return [span.strip("\n") for span in PARAGRAPH_BREAK.split(page_text) if span.strip()]


def build_page_atom_catalog(job_path: Path, packet_root: Path) -> dict:
    job_bytes = job_path.read_bytes()
    job = json.loads(job_bytes.decode("utf-8"))
    sources = verify_job_source_layers(job, packet_root)
    atoms = []
    for source_id, (_source, pages) in sorted(sources.items()):
        for page_number, page_text in enumerate(pages, start=1):
            for span_number, raw_span in enumerate(page_spans(page_text), start=1):
                atom = {
                    "atom_id": f"{source_id}:p{page_number}:t{span_number}",
                    "source_id": source_id,
                    "page": page_number,
                    "evidence_mode": "TEXT_QUOTE",
                    "raw_source_span": raw_span,
                    "canonical_span": canonicalize_text(raw_span),
                    "asset_path": None,
                    "asset_sha256": None,
                    "depiction_locator": None,
                    "crop_manifest_path": None,
                    "crop_manifest_sha256": None,
                    "source_binary_sha256": None,
                    "renderer_contract": None,
                    "renderer_sha256": None,
                    "r3_floor_categories": [],
                }
                atom["atom_sha256"] = canonical_json_sha256(atom)
                atoms.append(atom)
    catalog = {
        "schema_version": "evidence-atom-catalog.v1",
        "job_id": job["job_id"],
        "study_id": job["study"]["study_id"],
        "job_sha256": sha256_bytes(job_bytes),
        "atoms": atoms,
    }
    catalog["catalog_sha256"] = canonical_json_sha256(catalog)
    return catalog
```

The CLI must take `--job`, `--packet-root`, `--schema`, and `--output`, validate the generated catalog with `Draft202012Validator`, and atomically write one JSON file. For each hash-bound declaration in `job.visual_crops`, it also reuses the proven crop-manifest verifier to append one `FIGURE_TABLE_IMAGE` atom with `FIGURE_TABLE_CHEMISTRY` as an R3 floor. Qwen may select that existing visual atom but cannot create its source/page/asset fields. Do not implement embeddings, chunk databases, or fuzzy locator invention.

- [ ] **Step 7: Run all grounding tests**

```bash
python3 tests/test_evidence_grounding_v2.py
python3 tests/test_evidence_atom_vertical_slice.py
python3 -m pytest tests/test_page_atom_catalog.py -q
```

Expected: PASS.

- [ ] **Step 8: Add one generic gate and commit**

```make
.PHONY: evidence-grounding-check
evidence-grounding-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_evidence_grounding_v2.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_evidence_atom_vertical_slice.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest tests/test_page_atom_catalog.py -q
```

```bash
git add Makefile schemas/evidence templates/evidence scripts/evidence tests/test_evidence_grounding_v2.py tests/test_evidence_atom_vertical_slice.py tests/test_page_atom_catalog.py tests/fixtures/evidence_grounding_v2 tests/fixtures/evidence_atom_vertical_slice
git commit -m "feat(evidence): promote locator-first atom grounding"
```

### Task 4: Build the minimal review projection and writer whitelist

**Why:** Directly enforces the approved Source → Evidence → Claim → Manuscript flow and keeps failures from blocking unrelated studies.

**Files:**
- Create: `review_writer/project/vertical_review.py`
- Create: `scripts/run_vertical_review.py`
- Create: `tests/test_vertical_review_projection.py`
- Modify: `Makefile`

- [ ] **Step 1: Write failing projection tests**

Create `tests/test_vertical_review_projection.py` covering these exact cases:

```python
def test_low_risk_claim_requires_r0_and_fresh_reviewer_support(tmp_path):
    job = initialize_review(tmp_path, "synthetic-review", brief_fixture())
    register_study(job, candidate_fixture(risk="R1"), r0_fixture("R0_PASS"), reviewer_fixture("SUPPORT"))
    projection = rebuild_projection(job)
    assert projection[0]["decision"] == "APPROVED"


def test_high_risk_and_ambiguous_claims_fail_closed(tmp_path):
    job = initialize_review(tmp_path, "synthetic-review", brief_fixture())
    register_study(job, candidate_fixture(risk="R3"), r0_fixture("R0_PASS"), reviewer_fixture("SUPPORT"))
    register_study(job, candidate_fixture(claim_id="c2", risk="R1"), r0_fixture("R0_PASS"), reviewer_fixture("AMBIGUOUS"))
    decisions = {row["claim_id"]: row["decision"] for row in rebuild_projection(job)}
    assert decisions == {"c1": "HUMAN_REQUIRED", "c2": "BLOCKED"}


def test_writer_packet_contains_only_approved_claims(tmp_path):
    job = populated_job_with_approved_blocked_and_human_claims(tmp_path)
    packet = build_writer_packet(job)
    assert {row["decision"] for row in packet["claims"]} == {"APPROVED"}
    assert packet["known_exclusions"]
    assert packet["human_required_count"] == 1


def test_one_bad_study_does_not_erase_registered_studies(tmp_path):
    job = populated_job(tmp_path, passing_studies=2)
    with pytest.raises(VerticalReviewError):
        register_study(job, candidate_fixture(study_id="bad"), r0_fixture("R0_FAIL_GROUNDING_CONTRACT"), reviewer_fixture("SUPPORT"))
    assert len(load_evidence_cards(job)) == 2
    assert load_exception_queue(job)[0]["study_id"] == "bad"
```

The test file must define `brief_fixture`, `candidate_fixture`, `r0_fixture`, `reviewer_fixture`, `populated_job_with_approved_blocked_and_human_claims`, and `populated_job` as local synthetic helpers. Each helper writes only temporary data and returns the exact object type consumed by the public functions.

- [ ] **Step 2: Run the tests and verify RED**

Run: `python3 -m pytest tests/test_vertical_review_projection.py -q`

Expected: FAIL because `review_writer.project.vertical_review` is absent.

- [ ] **Step 3: Implement the authoritative project paths and atomic writes**

Create `review_writer/project/vertical_review.py` with only these persisted product objects:

```text
00_brief/review_state.json
00_discovery/candidate_pool.json
00_discovery/screening_decisions.json
00_discovery/acquisition_manifest.json
01_evidence/evidence_cards.jsonl
01_evidence/exception_queue.json
02_claims/claim_projection.jsonl
02_claims/writer_packet.json
03_review/risk_packet.json
03_review/risk_decisions.json
04_first_draft/first_draft.md
04_first_draft/manuscript_lineage.json
05_final_audit/quality_report.json
05_final_audit/release_report.md
05_final_audit/final_draft.docx
```

Implement these public functions exactly; each returns the declared type and raises `VerticalReviewError` on invalid state:

```text
initialize_review(review_root: Path, project_id: str, brief: dict) -> Path
register_study(project: Path, candidate: dict, r0_report: dict, reviewer: dict) -> dict
rebuild_projection(project: Path) -> list[dict]
build_risk_packet(project: Path, low_risk_sample_rate: float = 0.10) -> dict
apply_risk_decisions(project: Path, decisions: dict) -> list[dict]
build_writer_packet(project: Path) -> dict
benchmark_metrics(project: Path) -> dict
```

Decision reducer:

```python
if r0_report["status"] != "R0_PASS":
    decision = "BLOCKED"
elif reviewer_verdict != "SUPPORT":
    decision = "BLOCKED"
elif risk_level == "R3" or set(risk_categories) & HIGH_RISK_CATEGORIES:
    decision = "HUMAN_REQUIRED"
else:
    decision = "APPROVED"
```

`APPROVE` keeps claim text, `REWORD` requires nonempty `approved_text`, `EXCLUDE` becomes `BLOCKED`, and `UNRESOLVED` remains `HUMAN_REQUIRED`. Never mutate Provider candidate files. The 10% low-risk audit sample is selected deterministically by `sha256(claim_id)` ordering and is presented in the same risk packet.

- [ ] **Step 4: Add a thin internal CLI**

Create `scripts/run_vertical_review.py` with subcommands:

```text
init --review-root --project-id --brief
prepare-study --project-dir --study-id
prepare-batch --project-dir --study-ids-file
register-study --project-dir --candidate --r0-report --reviewer
build-risk-packet --project-dir
apply-risk-decisions --project-dir --decisions
build-writer-packet --project-dir
metrics --project-dir --output
```

The CLI prints scientist-neutral status summaries only; it never prints source text, credentials, model prompts, or hidden reasoning.

- [ ] **Step 5: Add and run the projection gate**

```make
.PHONY: vertical-review-projection-check
vertical-review-projection-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest tests/test_vertical_review_projection.py -q
```

Run: `make vertical-review-projection-check`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add Makefile review_writer/project/vertical_review.py scripts/run_vertical_review.py tests/test_vertical_review_projection.py
git commit -m "feat(product): add evidence-governed review projection"
```

### Task 5: Convert the QoderWork Expert Kit to the three-interaction golden path

**Why:** Directly reduces researcher operation while preserving Qwen semantic work. No new Agent roles are added.

**Files:**
- Modify: `qoderwork/plugins/research-review-writer/.qoder-plugin/plugin.json`
- Modify: `qoderwork/plugins/research-review-writer/skills/research-review-writer/SKILL.md`
- Modify: `qoderwork/plugins/research-review-writer/agents/REVIEW_BRIEFING_AGENT.md`
- Modify: `qoderwork/plugins/research-review-writer/agents/DISCOVERY_ACQUISITION_PLANNER.md`
- Modify: `qoderwork/plugins/research-review-writer/agents/PER_STUDY_EVIDENCE_EXTRACTOR.md`
- Modify: `qoderwork/plugins/research-review-writer/agents/ADVERSARIAL_EVIDENCE_REVIEWER.md`
- Modify: `qoderwork/plugins/research-review-writer/agents/SYNTHESIS_MANUSCRIPT_WRITER.md`
- Modify: `qoderwork/plugins/research-review-writer/agents/QUALITY_RELEASE_REVIEWER.md`
- Modify: `tests/test_qoderwork_native_review_writer.py`

- [ ] **Step 1: Add failing product-contract assertions**

Extend `tests/test_qoderwork_native_review_writer.py`:

```python
def test_plugin_exposes_only_three_researcher_interactions(self):
    skill = (PLUGIN / "skills/research-review-writer/SKILL.md").read_text(encoding="utf-8")
    assert "1. Review Brief" in skill
    assert "2. Scientific Risk Packet" in skill
    assert "3. Final Review" in skill
    for forbidden in ("复制 Prompt", "编辑 JSON", "git ", "worktree", "逐篇确认", "七个检查点"):
        assert forbidden not in skill


def test_extractor_selects_atoms_and_cannot_author_locators(self):
    extractor = (PLUGIN / "agents/PER_STUDY_EVIDENCE_EXTRACTOR.md").read_text(encoding="utf-8")
    assert "existing atom_id" in extractor
    assert "Do not write source_id, page, exact_quote" in extractor


def test_writer_reads_only_approved_writer_packet(self):
    writer = (PLUGIN / "agents/SYNTHESIS_MANUSCRIPT_WRITER.md").read_text(encoding="utf-8")
    assert "writer_packet.json" in writer
    assert "APPROVED" in writer
    assert "完整 PDF" not in writer
```

- [ ] **Step 2: Run the plugin tests and verify RED**

Run: `python3 tests/test_qoderwork_native_review_writer.py`

Expected: new assertions fail against plugin v0.1.1.

- [ ] **Step 3: Rewrite the main Skill as one bounded task**

Update `SKILL.md` to this execution order:

```text
1. Review Brief
   - Ask only missing material scope questions.
   - Write review_state.json through the local product command.
   - Launch the localhost dashboard and present the Review Brief URL.
   - Show one human-readable brief in the dynamic workbench and wait for confirmation.

2. Automatic corpus and evidence work
   - Generate scholarly-search-plan.v1.
   - Run public discovery and source acquisition commands.
   - Process the three-study calibration, forecast credits, then continue in 4–6-study batches.
   - For each study, delegate semantic atom selection and adversarial review.
   - Run deterministic registration after each study; failed studies enter the exception queue.
   - Do not ask the researcher to trigger per-study tasks.

3. Scientific Risk Packet
   - Build one deduplicated packet after all processable studies close.
   - Wait once for approve/reword/exclude/unresolved decisions.

4. Draft and Final Review
   - Build writer_packet.json from APPROVED claims only.
   - Delegate section synthesis and manuscript writing.
   - Run quality/release review and deterministic export checks.
   - Present the editable workbench and DOCX for one final confirmation.
```

The main Skill may invoke only repository-maintained commands from Tasks 1–4 and the existing dashboard/export commands. It must stop before any paid run if job-level Qoder egress/credit authorization is absent. It must not ask the user to paste an internal prompt, select a sub-Agent, or open an output folder.

- [ ] **Step 4: Tighten the six existing Agent contracts**

Apply these role boundaries:

```text
REVIEW_BRIEFING_AGENT
  input: user topic/context
  output: human-readable brief fields only

DISCOVERY_ACQUISITION_PLANNER
  input: confirmed brief + candidate pool
  output: scholarly search plan, screening decisions, acquisition rows

PER_STUDY_EVIDENCE_EXTRACTOR
  input: one evidence_atom_catalog.v1 + semantic schema
  output: evidence-atom-semantic-decision.v1 only
  forbidden: source_id/page/exact_quote/coverage/self_check fields

ADVERSARIAL_EVIDENCE_REVIEWER
  input: one assembled candidate + selected source atoms
  output: SUPPORT | REJECT | AMBIGUOUS per target, with a concise reason

SYNTHESIS_MANUSCRIPT_WRITER
  input: writer_packet.json only
  output: section drafts, authoritative manuscript, and manuscript_lineage.json

QUALITY_RELEASE_REVIEWER
  input: authoritative manuscript + lineage + quality report
  output: semantic release verdict; cannot override BLOCKED/HUMAN_REQUIRED
```

Keep Writer, Reviewer, and final Reviewer in fresh contexts. Retain `Read, Write` on semantic sub-Agents. Grant `Bash` only to `DISCOVERY_ACQUISITION_PLANNER` and `QUALITY_RELEASE_REVIEWER`, restricted by their prompts to the repository-maintained commands named in this plan. This is required to remove user-run commands; no other sub-Agent receives shell access.

- [ ] **Step 5: Increment the plugin version and run checks**

Set plugin version to `0.2.0` and update the expected version in the focused test.

Run:

```bash
make qoderwork-native-review-check
make qoderwork-plugin-package
```

Expected: tests pass and `build/research-review-writer.qoder-plugin.zip` contains only the same manifest, one Skill, and six Agent files.

- [ ] **Step 6: Commit**

```bash
git add qoderwork/plugins/research-review-writer tests/test_qoderwork_native_review_writer.py
git commit -m "feat(qoderwork): enforce three-interaction review path"
```

### Task 6: Expose evidence cards and one scientific risk packet in the dynamic workbench

**Why:** Directly gives researchers the evidence and decisions they need without exposing JSON, hashes, prompts, or Agent internals.

**Files:**
- Modify: `view/serve_review_dashboard.py`
- Modify: `view/assets/dashboard/review.html`
- Modify: `view/assets/dashboard/review-ui.css`
- Modify: `tests/test_qoderwork_native_review_writer.py`
- Expand fixture: `tests/fixtures/qoderwork_native_review/review-projects/synthetic-review/`

- [ ] **Step 1: Add failing API tests**

Extend the dashboard test fixture with synthetic `evidence_cards.jsonl`, `risk_packet.json`, and `risk_decisions.json`. Add:

```python
def test_researcher_payload_hides_internal_fields(self):
    evidence = dashboard.project_evidence_payload(review_root, "synthetic-review")
    assert evidence["cards"][0]["study_id"] == "synthetic-study-01"
    serialized = json.dumps(evidence)
    for hidden in ("sha256", "schema_version", "job_id", "self_check", "prompt"):
        assert hidden not in serialized


def test_risk_decisions_are_validated_and_persisted(self):
    payload = {"decisions": [{"target_id": "claim-1", "decision": "REWORD",
                              "approved_text": "Narrow supported wording."}]}
    saved = dashboard.write_project_risk_decisions(review_root, "synthetic-review", payload)
    assert saved["decisions"][0]["decision"] == "REWORD"
    with self.assertRaises(ValueError):
        dashboard.write_project_risk_decisions(review_root, "synthetic-review",
            {"decisions": [{"target_id": "claim-1", "decision": "REWORD", "approved_text": ""}]})


def test_dashboard_routes_evidence_and_risk_packet(self):
    for route in ("evidence", "risk-packet"):
        status, _, body = self._request(
            dashboard, review_root,
            f"GET /api/project/synthetic-review/{route} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode(),
        )
        assert status == 200
        assert json.loads(body)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python3 tests/test_qoderwork_native_review_writer.py`

Expected: FAIL because evidence/risk APIs do not exist.

- [ ] **Step 3: Implement scientist-facing payload builders and routes**

Add these functions to `view/serve_review_dashboard.py`; their bodies must read the canonical files from Task 4, project only scientist-facing fields, and use atomic writes for decisions:

```text
project_evidence_payload(review_root: Path, project_id: str) -> dict[str, Any]
project_risk_payload(review_root: Path, project_id: str) -> dict[str, Any]
write_project_risk_decisions(review_root: Path, project_id: str, data: Any) -> dict[str, Any]
```

Routes:

```text
GET /api/project/{project_id}/evidence
GET /api/project/{project_id}/risk-packet
PUT /api/project/{project_id}/risk-decisions
```

Evidence payload fields are limited to `study_id`, `citation`, `activation_mode`, `reaction_class`, `observations`, `limitations`, `claims`, `source_excerpt`, and scientist-readable locators. Risk payload fields are limited to `target_id`, `claim_text`, `risk_categories`, `evidence_summary`, `source_excerpt`, `source_label`, `page`, `proposed_action`, and existing decision. Reject duplicate target IDs and decisions outside `APPROVE|REWORD|EXCLUDE|UNRESOLVED`.

- [ ] **Step 4: Replace the home page with four researcher tabs**

Keep one existing HTML file. Add tabs:

```text
Overview | Evidence | Decisions | Manuscript
```

Requirements:

- Overview: brief, stage, coverage, processable/blocked counts;
- Evidence: filter by study and activation mode; expandable evidence cards with locator links;
- Decisions: one compact list with four decision buttons and a reword field;
- Manuscript: links to the section editor and current DOCX;
- no paths, filenames, hashes, Agent names, JSON, Prompt, Git, or provider logs in visible text;
- keyboard-operable controls and no hover-only content.

- [ ] **Step 5: Run dashboard and plugin tests**

```bash
python3 tests/test_qoderwork_native_review_writer.py
make qoderwork-native-review-check
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add view/serve_review_dashboard.py view/assets/dashboard/review.html view/assets/dashboard/review-ui.css tests/test_qoderwork_native_review_writer.py tests/fixtures/qoderwork_native_review
git commit -m "feat(workbench): add evidence and risk review surfaces"
```

### Task 7: Make the section editor and DOCX consume one authoritative manuscript

**Why:** Directly prevents manuscript/DOCX drift and lets researchers edit without understanding Markdown synchronization.

**Files:**
- Create: `review_writer/delivery/project_release.py`
- Modify: `view/serve_review_dashboard.py`
- Modify: `view/assets/dashboard/draft.html`
- Modify: `view/assets/dashboard/final.html`
- Create: `tests/test_project_release.py`
- Modify: `tests/test_qoderwork_native_review_writer.py`

- [ ] **Step 1: Write failing manuscript and release tests**

Create `tests/test_project_release.py`:

```python
def test_section_round_trip_preserves_authoritative_manuscript():
    original = "# Title\n\nIntro text.\n\n## Results\n\nEvidence-backed text [1].\n\n## References\n\n[1] Example."
    sections = split_manuscript_sections(original)
    sections[1]["body"] = "Revised evidence-backed text [1]."
    rebuilt = render_manuscript_sections(sections)
    assert "## Results\n\nRevised evidence-backed text [1]." in rebuilt
    assert rebuilt.count("## References") == 1


def test_release_snapshots_exact_authoritative_bytes(tmp_path):
    project = make_release_ready_project(tmp_path)
    result = build_project_release(project)
    assert (project / "05_final_audit/final_draft.md").read_bytes() == (
        project / "04_first_draft/first_draft.md").read_bytes()
    assert result["manuscript_sha256"] == sha256_file(project / "04_first_draft/first_draft.md")
    assert (project / "05_final_audit/final_draft.docx").is_file()


def test_release_fails_on_blocked_claim_or_lineage_drift(tmp_path):
    project = make_release_ready_project(tmp_path, blocked_claim_in_manuscript=True)
    with pytest.raises(ProjectReleaseError):
        build_project_release(project)
```

The test file must define `make_release_ready_project` with an authoritative manuscript, claim projection, writer packet, manuscript lineage, references, and a tiny local image fixture. It must not depend on Case 01/M2 artifacts.

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m pytest tests/test_project_release.py -q`

Expected: FAIL because `review_writer.delivery.project_release` is absent.

- [ ] **Step 3: Implement section parsing and release creation**

Create `review_writer/delivery/project_release.py` with these public functions and the exact release order below:

```text
split_manuscript_sections(markdown: str) -> list[dict[str, str]]
render_manuscript_sections(sections: list[dict[str, str]]) -> str
validate_manuscript_lineage(project: Path, markdown: str) -> dict
build_project_release(project: Path, python_executable: Path = Path(sys.executable)) -> dict
```

Release order:

1. read `04_first_draft/first_draft.md` once;
2. reject blocked/human-required claim references, missing references, broken images, or lineage mismatch;
3. atomically copy those exact bytes to `05_final_audit/final_draft.md` as a release snapshot;
4. invoke existing `skills/review-export-docx/scripts/md2docx.py` on that snapshot;
5. verify DOCX exists and record manuscript/DOCX hashes in `quality_report.json`;
6. never edit the authoritative manuscript during export.

- [ ] **Step 4: Change the dashboard editor to section data**

`GET /api/project/{project_id}/draft` returns `sections` from `split_manuscript_sections`. `PUT` accepts `sections`, validates unique ordered headings, and writes one reconstructed `04_first_draft/first_draft.md` atomically. Keep raw `first_draft_md` only as an internal compatibility field; remove the raw Markdown textarea from the researcher UI.

`draft.html` displays heading labels and one body editor for the selected section. Figures/tables render in preview and remain source-bound. `final.html` reads the authoritative manuscript until a release snapshot exists, then displays the snapshot hash status without exposing the hash value.

- [ ] **Step 5: Route DOCX export through `build_project_release`**

Replace direct `md2docx.py` subprocess logic in `export_project_docx` with `build_project_release(project)`. Return only `ok`, filename, size, and release status to the browser.

- [ ] **Step 6: Run focused release/UI tests**

```bash
python3 -m pytest tests/test_project_release.py -q
python3 tests/test_qoderwork_native_review_writer.py
python3 tests/test_docx_citation_links.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add review_writer/delivery/project_release.py view/serve_review_dashboard.py view/assets/dashboard/draft.html view/assets/dashboard/final.html tests/test_project_release.py tests/test_qoderwork_native_review_writer.py
git commit -m "feat(delivery): bind workbench and docx to one manuscript"
```

### Task 8: Add one synthetic three-study product acceptance path

**Why:** Directly guards case-neutral behavior before spending Qoder credits or processing real papers.

**Files:**
- Create: `tests/fixtures/scaled_vertical_review/**`
- Create: `tests/test_scaled_vertical_review.py`
- Modify: `Makefile`

- [ ] **Step 1: Create a minimal synthetic fixture**

The fixture contains three neutral studies, each with MAIN/SI text layers, atom catalog, semantic decision, adversarial verdict, and expected claim decision. Include:

```text
Study A: R1 observation -> APPROVED
Study B: R3 mechanism claim -> HUMAN_REQUIRED
Study C: invalid quote or AMBIGUOUS review -> BLOCKED and exception queue
```

No allene, Katritzky, real DOI, private path, or real source text is allowed in the fixture.

- [ ] **Step 2: Write the failing full-path test**

```python
def test_three_study_vertical_product_path(tmp_path):
    project = initialize_review(tmp_path, "synthetic-scaled-review", BRIEF)
    run_fixture_studies(project, FIXTURE)
    packet = build_writer_packet(project)
    assert packet["approved_claim_count"] == 1
    assert packet["human_required_count"] == 1
    assert packet["blocked_count"] == 1
    write_fixture_manuscript(project, packet)
    release = build_project_release(project)
    assert release["status"] == "AI_REVIEWED_BENCHMARK"
    assert dashboard.project_evidence_payload(tmp_path, "synthetic-scaled-review")["coverage"]["studies"] == 3
```

The test file must define `BRIEF`, `run_fixture_studies`, and `write_fixture_manuscript`; all three read only `tests/fixtures/scaled_vertical_review/` and use the public APIs from Tasks 3, 4, 6, and 7.

- [ ] **Step 3: Run and repair only real integration gaps**

Run: `python3 -m pytest tests/test_scaled_vertical_review.py -q`

Expected initially: FAIL only where the new generic components do not yet interoperate. Fix those exact interfaces; do not add a generic workflow engine.

- [ ] **Step 4: Add the single product acceptance target**

```make
.PHONY: scaled-review-check
scaled-review-check:
	$(MAKE) public-corpus-acquisition-check
	$(MAKE) scholarly-discovery-check
	$(MAKE) evidence-grounding-check
	$(MAKE) vertical-review-projection-check
	$(MAKE) qoderwork-native-review-check
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest tests/test_project_release.py tests/test_scaled_vertical_review.py -q
```

- [ ] **Step 5: Run the product acceptance path**

Run: `make scaled-review-check`

Expected: PASS with no network or Provider use.

- [ ] **Step 6: Commit**

```bash
git add Makefile tests/fixtures/scaled_vertical_review tests/test_scaled_vertical_review.py
git commit -m "test(product): add three-study vertical acceptance path"
```

### Task 9: Run Case 02 discovery and freeze the first real Review Brief

**Why:** Starts the actual benchmark rather than another synthetic/demo loop. This task writes only ignored project data.

**Runtime paths:**
- Windows-native QoderWork repository workspace: `C:\Users\26960\QW-RW\review-writer\`
- Windows-native ignored project: `C:\Users\26960\QW-RW\review-writer\review-projects\case-02-katritzky-deaminative-functionalization\`

- [ ] **Step 1: Create or refresh one Windows-native runtime clone without remote writes**

Use the local implementation branch as source so QoderWork receives an ordinary `C:\` workspace even before remote integration:

```bash
SOURCE_REPO=/home/kenqia/my_folder/review-writer/.worktrees/qoderwork-native-review-workbench
WINDOWS_REPO=/mnt/c/Users/26960/QW-RW/review-writer
if [ ! -e "$WINDOWS_REPO/.git" ]; then
  git clone --no-local --branch feat/qoderwork-native-review-workbench "$SOURCE_REPO" "$WINDOWS_REPO"
else
  git -C "$WINDOWS_REPO" status --short --branch
  git -C "$WINDOWS_REPO" fetch "$SOURCE_REPO" feat/qoderwork-native-review-workbench
  git -C "$WINDOWS_REPO" merge --ff-only FETCH_HEAD
fi
```

If the existing Windows clone is dirty or cannot fast-forward, stop and preserve it; do not overwrite or reset it.

- [ ] **Step 2: Build and install the current Expert Kit once**

Inside the Windows-native clone, run `make qoderwork-plugin-package`. Upload the resulting Expert Kit to QoderWork CN only if version `0.2.0` is not already installed. This one-time UI installation is the only setup action exposed to the user; select `C:\Users\26960\QW-RW\review-writer` as the task workspace.

- [ ] **Step 3: Obtain one Case 02 job-level authorization before the first Qoder run**

Show only:

```text
runtime: QoderWork CN / Qwen3.7-Max
purpose: one Case 02 discovery-to-DOCX benchmark
egress: one-study locator catalogs/crops for extraction; approved claims for writing
credit target: 3,500
credit hard cap: 4,500
finalization reserve: 500
automatic purchase: false
automatic model fallback: false
```

One authorization covers the frozen Case 02 job; there are no per-study authorization prompts. If available credits are below 4,500, the calibration forecast must fit the actual remaining balance minus the 500-credit reserve.

- [ ] **Step 4: Start one QoderWork task and initialize the approved brief**

Create a scientist-readable brief input with:

```json
{
  "topic": "Katritzky salt deaminative functionalization",
  "review_question": "How do 2017–2025 activation modes differ in reaction class, scope, practical limits, and mechanistic support?",
  "from_year": 2017,
  "to_year": 2025,
  "target_primary_studies": 24,
  "acceptable_core_range": [20, 30],
  "required_modes": ["photoredox", "EDA_or_catalyst_free", "electrochemical", "transition_metal_or_dual"],
  "exclusions": ["N-centered radical", "non-deaminative use", "abstract-only evidence", "pure computation without independent synthesis"],
  "output_language": "English",
  "deliverables": ["dynamic workbench", "editable DOCX", "benchmark report"]
}
```

The researcher starts “科研综述专家” once with the approved topic. The Expert Kit, not the researcher, runs:

```bash
WINDOWS_REPO=/mnt/c/Users/26960/QW-RW/review-writer
CASE02_PROJECT_ID=case-02-katritzky-deaminative-functionalization
cd "$WINDOWS_REPO"
python3 scripts/run_vertical_review.py init \
  --review-root "$WINDOWS_REPO" \
  --project-id "$CASE02_PROJECT_ID" \
  --brief /tmp/case02-review-brief.json
```

Expected: one ignored project with `00_brief/review_state.json`, status `AWAITING_BRIEF_CONFIRMATION`.

- [ ] **Step 5: Open the dynamic workbench for Interaction 1**

The Expert Kit launches the dashboard and presents `/review`. The researcher sees only the one-page brief and clicks confirm. Do not ask them to inspect files or JSON. Keep this same QoderWork task open through Tasks 10–12.

Acceptance: `review_state.json` records a confirmed brief and the UI has no Agent/Prompt/Git terminology.

- [ ] **Step 6: Generate and validate a search plan**

Have `DISCOVERY_ACQUISITION_PLANNER` produce a bounded plan containing 4–8 search queries and 2–4 review/seed DOIs. Validate `2017 <= from_year <= to_year <= 2025`; reject topic drift.

Representative queries:

```text
Katritzky salt deaminative functionalization
N-alkylpyridinium photoredox deamination
Katritzky salt EDA catalyst-free reaction
electrochemical deaminative pyridinium salt
transition-metal dual catalysis Katritzky salt
```

These are runtime data, not production constants.

- [ ] **Step 7: Run public discovery**

```bash
WINDOWS_REPO=/mnt/c/Users/26960/QW-RW/review-writer
CASE02_PROJECT="$WINDOWS_REPO/review-projects/case-02-katritzky-deaminative-functionalization"
cd "$WINDOWS_REPO"
python3 scripts/discovery/discover_scholarly_corpus.py \
  --plan "$CASE02_PROJECT/00_discovery/search_plan.json" \
  --output "$CASE02_PROJECT/00_discovery/candidate_pool.json" \
  --allow-network
```

Expected: the Expert Kit successfully runs the local command and produces a deterministic candidate pool with query/seed/chaining provenance and no scientific inclusion claims. If it cannot run the declared command, stop with `PRODUCT_RUNTIME_AUTOMATION_GAP`; do not transfer the command to the researcher.

- [ ] **Step 8: Screen and build the acquisition manifest**

Qwen screens titles/abstracts into `INCLUDE_FOR_FULL_TEXT`, `EXCLUDE_TITLE_ABSTRACT`, or `UNCERTAIN`. Local validation requires one disposition for every candidate. Then generate a `public-corpus-acquisition.v1` manifest only for likely/uncertain studies with public direct MAIN/SI URLs; landing-page-only rows go directly to the manual queue.

- [ ] **Step 9: Acquire public sources and inspect the single missing-source queue**

```bash
WINDOWS_REPO=/mnt/c/Users/26960/QW-RW/review-writer
CASE02_PROJECT="$WINDOWS_REPO/review-projects/case-02-katritzky-deaminative-functionalization"
cd "$WINDOWS_REPO"
python3 scripts/acquisition/acquire_public_corpus.py \
  --manifest "$CASE02_PROJECT/00_discovery/acquisition_manifest.json" \
  --output-root "$CASE02_PROJECT/00_sources"
```

Expected: downloaded/verified sources plus one consolidated manual queue. Do not use credentials, session cookies, paywall bypass, CAPTCHA bypass, or Sci-Hub.

- [ ] **Step 10: Apply the discovery capacity gate**

Continue automatically when 20–30 likely eligible primary studies have MAIN and required SI coverage. If fewer than 20, complete citation chaining before declaring sparsity. If more than 30 are scientifically eligible, do not cherry-pick; either process all or return to the brief only for a scientific scope refinement.

No Git commit is made in this task.

### Task 10: Calibrate three real studies through QoderWork CN

**Why:** Verifies the real Qoder model/runtime, grounding, costs, and product UX before scaling to the full corpus.

- [ ] **Step 1: Select three in-corpus calibration studies**

Choose three studies spanning at least three activation modes and differing in SI complexity. Record the reason in ignored project state. They remain part of the final corpus.

- [ ] **Step 2: Build local source layers and atom catalogs**

For each selected study, use the Task 4 product command so source paths are resolved from registered SourceRecords rather than copied into user prompts:

```bash
WINDOWS_REPO=/mnt/c/Users/26960/QW-RW/review-writer
CASE02_PROJECT="$WINDOWS_REPO/review-projects/case-02-katritzky-deaminative-functionalization"
cd "$WINDOWS_REPO"
python3 scripts/run_vertical_review.py prepare-batch \
  --project-dir "$CASE02_PROJECT" \
  --study-ids-file "$CASE02_PROJECT/00_discovery/calibration_studies.json"
```

Create page crops only for figures/tables that could support displayed chemistry. Do not crop every page.

- [ ] **Step 3: Continue the same QoderWork task for all three studies**

Without another researcher submission, the Skill delegates the three per-study semantic atom selections and fresh adversarial reviews. It writes only declared outputs. Record credits before/after at job level.

If QoderWork cannot invoke local commands or continue the three-study loop without another researcher message, classify it as `PRODUCT_RUNTIME_AUTOMATION_GAP`; do not disguise operator prompts as product UX.

- [ ] **Step 4: Run deterministic assembly and registration**

For each study, assemble the candidate from atom IDs, run the R0 validator, then register it with its fresh reviewer verdict. The original Qoder outputs remain unchanged.

Acceptance:

```text
3/3 studies have a deterministic status
0 model-authored locators/pages/quotes enter candidates
all failed targets are BLOCKED or HUMAN_REQUIRED
no per-study researcher interaction
```

- [ ] **Step 5: Forecast full cost and lock the evidence fields once**

Compute:

```text
projected_credits = measured_three_study_credits / 3 * eligible_study_count
                    + measured_synthesis_and_finalization_estimate
                    + 20% contingency
```

Continue only if the forecast is within the confirmed job budget. Evidence fields may be revised once based on these three real studies; after that, new needs become limitations or a separately justified scope change.

- [ ] **Step 6: Commit only generic fixes proven necessary by calibration**

For every candidate fix, name the failed acceptance criterion and add a regression test before code. Do not commit Case 02 sources or Provider outputs.

Commit each generic calibration fix only after its failing regression test passes. Stage the exact test and production files shown by `git status --short`; never stage `review-projects/`, PDFs, source excerpts, or Qoder output.

Repeat the commit step only for distinct, user-visible or scientific blockers; cosmetic and diagnostic-only changes wait.

### Measured-runtime amendment before Task 11

实测表明逐篇由模型驱动浏览器下载速度慢且 credits 成本高。规模化路线允许一次条件性的 consolidated source ZIP handoff：研究者从单一 queue 下载剩余来源并上传一个 ZIP，系统确定性导入；不做 model-driven browser download。语义解析复用既有 MinerU，exact page locator 与 verbatim quote 继续以 `pdftotext` reading/layout layers 为准。当前 Case 02 的 discovery、acquisition 与 MinerU assets 已存在，因此不得为当前 Case 02 重跑这些阶段。

### Task 11: Scale the same path to the complete eligible corpus

**Why:** This is the benchmark’s central proof of real-scale use.

- [ ] **Step 1: Freeze full-text eligibility for every candidate**

Each candidate receives one of:

```text
INCLUDED_CORE
EXCLUDED_SCIENTIFIC
ELIGIBILITY_UNRESOLVED_SOURCE_MISSING
ELIGIBILITY_UNRESOLVED_SCIENTIFIC
```

Every decision includes a source locator or a missing-source reason. A download failure is not a scientific exclusion.

- [ ] **Step 2: Process included studies in 4–6-study batches**

For each batch, automatically execute:

```text
source layers -> atom catalogs -> Qwen semantic selection -> deterministic assembly
-> fresh adversarial review -> registration -> project-state update
```

Persist after every study so one failure cannot erase completed work. Do not ask the researcher to trigger batches.

- [ ] **Step 3: Monitor scale acceptance after every batch**

Required live metrics:

```text
candidate dispositions / total candidates
included studies with evidence cards / included studies
R0 pass, blocked, human-required counts
MAIN/SI source coverage
credits used and projected total
provider-output manual edit count (must remain zero)
```

If first-pass pass-or-explicit-exception coverage drops below 90%, stop adding studies and fix the common generic cause. Do not create source-specific adapters until at least two studies demonstrate the same failure class.

- [ ] **Step 4: Close the corpus projection**

Run:

```bash
WINDOWS_REPO=/mnt/c/Users/26960/QW-RW/review-writer
CASE02_PROJECT="$WINDOWS_REPO/review-projects/case-02-katritzky-deaminative-functionalization"
cd "$WINDOWS_REPO"
python3 scripts/run_vertical_review.py build-risk-packet --project-dir "$CASE02_PROJECT"
python3 scripts/run_vertical_review.py build-writer-packet --project-dir "$CASE02_PROJECT"
python3 scripts/run_vertical_review.py metrics --project-dir "$CASE02_PROJECT" --output "$CASE02_PROJECT/05_final_audit/benchmark_metrics.json"
```

Expected before human risk review: 100% candidate dispositions, 100% included studies with cards or explicit exception, zero unlabelled conflicts, and writer packet containing only `APPROVED` claims.

### Task 12: Draft the comparative review, complete one risk review, and release the editable product

**Why:** Produces the actual scientific deliverable and measures whether human correction is acceptable.

- [ ] **Step 1: Build evidence clusters**

Qwen groups approved claims by activation mode, bond formation, substrate class, practical limitation, and mechanistic evidence. Every cluster lists its full comparable set and known exclusions before drafting.

- [ ] **Step 2: Draft sections from the approved writer packet**

Use fresh Writer context per major section. Required scientific rules:

```text
observation != author interpretation != cross-study synthesis
single example != trend
not reported != failed
non-comparable results cannot be ranked
mechanism proposal cannot be called proof
```

Expected manuscript: evidence-driven, approximately 6,000–9,000 English words, 2–3 lineage-backed comparison tables, and 2–4 source-bound chemistry visuals. Do not pad to targets.

- [ ] **Step 3: Present Interaction 2—the single risk packet**

The domain chemistry reviewer receives all high-risk items plus the deterministic 10% low-risk audit sample in the dynamic workbench. They choose only `APPROVE`, `REWORD`, `EXCLUDE`, or `UNRESOLVED`.

Record active review time and decisions. If the reviewer is unavailable, continue only to `AI_REVIEWED_BENCHMARK`; do not claim that correction burden has been validated.

- [ ] **Step 4: Apply decisions and regenerate only affected consumers**

```bash
WINDOWS_REPO=/mnt/c/Users/26960/QW-RW/review-writer
CASE02_PROJECT="$WINDOWS_REPO/review-projects/case-02-katritzky-deaminative-functionalization"
cd "$WINDOWS_REPO"
python3 scripts/run_vertical_review.py apply-risk-decisions --project-dir "$CASE02_PROJECT" --decisions "$CASE02_PROJECT/03_review/risk_decisions.json"
python3 scripts/run_vertical_review.py build-writer-packet --project-dir "$CASE02_PROJECT"
```

Qwen rewrites only affected sections. Re-run claim/manuscript lineage checks. Do not globally rewrite unaffected prose.

- [ ] **Step 5: Present Interaction 3—the editable manuscript and DOCX**

The researcher edits sections in the dynamic workbench, reviews citations/evidence cards, and generates DOCX. Run Word/PDF visual review for clipping, equations, tables, chemistry structures, hyperlinks, and references. Any material edit invalidates the previous release verdict.

- [ ] **Step 6: Compute benchmark acceptance**

Required outcomes:

```text
20–30 included core studies, or audited proof of objective sparsity
100% candidate dispositions
100% material assertions/tables/visuals with claim + locator
0 invented DOI, citation, number, quote, or page
>=90% studies pass or enter explicit exception without Provider-output editing
<=10% material reword/exclude rate in audited low-risk sample
<=15% material assertion reword/exclude rate in final expert review
<=90 minutes target active risk-review time
3 planned researcher interactions
```

If any criterion fails, report it honestly in the benchmark report; do not add hidden manual work or weaken the criterion.

### Task 13: Publish the product evidence, not the private corpus

**Why:** Makes the usable product and scale evidence reviewable while protecting papers and local data.

**Files:**
- Modify: `README.md`
- Modify: `docs/qoderwork/research_review_writer_quickstart.md`
- Create: `docs/benchmarks/CASE02_SCALED_VERTICAL_BENCHMARK.md`
- Modify: `.github/workflows/offline-ci.yml` only if the new offline target is not already covered

- [ ] **Step 1: Write the benchmark report from measured values**

The report contains only:

```text
brief and search dates
candidate/core counts and dispositions
MAIN/SI coverage
evidence/R0/reviewer/exception metrics
Qoder model and total credits (no credentials)
human risk-review time and correction rates
manuscript/DOCX/workbench acceptance
known limitations and release status
```

Do not include source excerpts, real PDFs/SI, local absolute paths, Provider prompts, hidden reasoning, or private review notes.

- [ ] **Step 2: Replace the developer quickstart with the researcher golden path**

README and QoderWork quickstart should present:

```text
1. Open QoderWork CN and select 科研综述专家.
2. Provide the topic and local source permission; confirm the Review Brief.
3. Return once for the Scientific Risk Packet.
4. Edit the manuscript and download DOCX.
```

Plugin packaging, Python server commands, Prompt templates, JSON files, Git commands, and worktree paths move to a clearly labelled maintainer section or are removed when the Expert Kit now performs them.

- [ ] **Step 3: Run fresh full verification**

```bash
make scaled-review-check
make smoke
make quality-check
make qoderwork-check
git diff --check
git status --short --branch
```

Expected: all checks pass; only intended generic code/docs/tests and the benchmark report are tracked.

- [ ] **Step 4: Commit product evidence**

```bash
git add README.md docs/qoderwork/research_review_writer_quickstart.md docs/benchmarks/CASE02_SCALED_VERTICAL_BENCHMARK.md .github/workflows/offline-ci.yml
git commit -m "docs(product): publish scaled review benchmark"
```

- [ ] **Step 5: Prepare remote integration without writing remotely**

```bash
git log --oneline origin/feat/qoderwork-native-review-workbench..HEAD
git diff --stat origin/feat/qoderwork-native-review-workbench...HEAD
git status --short --branch
```

Summarize commits, checks, benchmark status, and any private ignored data. Ask once for explicit authorization before `git push` or PR creation/update. Never force-push.

## Final implementation acceptance

Implementation is complete only when all of the following are true:

- a researcher can start one QoderWork review without copying prompts or operating files;
- the normal run has exactly three user-facing checkpoints;
- one real 20–30-study corpus has completed the same product path as the three-study fixture;
- Qwen supplied semantic extraction and writing, while deterministic code supplied locators and gates;
- blocked/human-required claims cannot enter the Writer packet;
- evidence cards, risk decisions, section editing, and DOCX are usable from the dynamic workbench;
- the DOCX and workbench consume one authoritative manuscript;
- measured human correction burden and credits are reported honestly;
- M2 remains a passing regression, not the active product workflow;
- remote Git remains untouched until the user explicitly authorizes push/PR operations.
