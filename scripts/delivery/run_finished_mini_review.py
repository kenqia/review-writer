#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_writer.delivery.finished_review import (  # noqa: E402
    EXPECTED_CLOSURE_MANIFEST_SHA256,
    EXPECTED_FINAL_CLAIMS_SHA256,
    build_finished_review_plan,
    generate_finished_review_with_bounded_repair,
    render_final_review,
    validate_finished_review_payload,
    verify_frozen_inputs,
    write_failed_generation_diagnostic,
    write_finished_review_package,
)
from review_writer.docx_links import inspect_docx_citation_links  # noqa: E402
from review_writer.phase8.ai_adjudication import sha256_file  # noqa: E402
from review_writer.providers import OpenAICompatibleProvider, TextGenerationRequest  # noqa: E402


CLOSURE_RUN_ID = "phase8a_closure_v3_1_1_20260714T120245Z"
MODEL_PRIORITY = ("qwen3.7-max", "qwen3.7-plus")
BIBLIOGRAPHY = {
    "F3I": {
        "authors": ["Shichao Yu", "Shengming Ma"],
        "title": "Allenes in Catalytic Asymmetric Synthesis and Natural Product Syntheses",
        "journal": "Angewandte Chemie International Edition",
        "year": 2012,
        "volume": "51",
        "issue": "13",
        "pages": "3074-3112",
        "doi": "10.1002/anie.201101460",
    },
    "F47A": {
        "authors": ["Masamichi Ogasawara", "Hisashi Ikeda", "Takashi Nagano", "Tamio Hayashi"],
        "title": "Palladium-Catalyzed Asymmetric Synthesis of Axially Chiral Allenes: A Synergistic Effect of Dibenzalacetone on High Enantioselectivity",
        "journal": "Journal of the American Chemical Society",
        "year": 2001,
        "volume": "123",
        "issue": "9",
        "pages": "2089-2090",
        "doi": "10.1021/ja005921o",
    },
    "P403": {
        "authors": ["Yujie Dong", "Nianci Zhang", "Fazhou Yang", "Jinbao Wang", "Bo Wang", "Jun Liu", "Bing Zheng", "Cheng Zhang", "Leijie Zhou", "Hongchao Guo"],
        "title": "Pd-Catalyzed Asymmetric Allenylation of Secondary Phosphine Oxides with Enyne-Type Propargylic Carbamates for the Construction of Chiral Allenyl Phosphine Oxides",
        "journal": "ACS Catalysis",
        "year": 2025,
        "volume": "15",
        "issue": "20",
        "pages": "17215-17224",
        "doi": "10.1021/acscatal.5c05571",
    },
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _select_model() -> tuple[str, dict[str, Any]]:
    probe = OpenAICompatibleProvider.from_env(allow_network=True)
    env = probe._safe_env()
    endpoint = probe._resolve_endpoint(env)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("the explicit Qwen run requires the openai package") from exc
    api_key = os.environ.get("DASHSCOPE_API_KEY") or ""
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY is missing")
    models = OpenAI(api_key=api_key, base_url=endpoint["base_url"], timeout=20.0).models.list()
    available = {item.id for item in models.data}
    configured = os.environ.get("BAILIAN_MODEL") or ""
    fallback = sorted((item for item in available if item.startswith("qwen") and "text" not in item), reverse=True)
    selected = next((item for item in (*MODEL_PRIORITY, configured, *fallback) if item and item in available), None)
    if selected is None:
        raise ValueError("no allowed Qwen text model is available")
    return selected, {
        "status": "PASS",
        "query_count": 1,
        "method": "OpenAI-compatible models.list",
        "selected_model": selected,
        "priority": list(MODEL_PRIORITY),
        "region": endpoint["region"],
        "endpoint_class": "Alibaba Cloud OpenAI-compatible dedicated workspace endpoint",
        "base_url": "redacted",
    }


class QwenJsonProvider:
    def __init__(self, model: str, args: argparse.Namespace) -> None:
        self.model = model
        self.provider = OpenAICompatibleProvider.from_env(
            allow_network=True,
            model=model,
            connect_timeout_seconds=args.connect_timeout_seconds,
            first_byte_timeout_seconds=args.first_byte_timeout_seconds,
            total_timeout_seconds=args.total_timeout_seconds,
        )
        self.temperature = args.temperature
        self.max_output_tokens = args.max_output_tokens

    def generate(self, request: dict[str, Any]) -> dict[str, Any]:
        system = (
            "You are writing a bounded chemistry mini-review from a closed structured evidence ledger. "
            "Return one JSON object only. Never use outside knowledge, invent a fact, expose hidden reasoning, "
            "or include citation markers in sentence text."
        )
        result = self.provider.generate_text(
            TextGenerationRequest(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(request, ensure_ascii=False, separators=(",", ":"))},
                ],
                model=self.model,
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
                response_format="json_object",
            )
        )
        return {
            "status": result.status,
            "content": result.content,
            "metadata": result.metadata,
            "warnings": result.warnings,
        }


class FileJsonProvider:
    def __init__(self, path: Path) -> None:
        self.content = path.read_text(encoding="utf-8")

    def generate(self, _request: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ok",
            "content": self.content,
            "metadata": {"model": "offline-mock", "region": "offline", "usage": {"total_tokens": 0}},
            "warnings": [],
        }


def _build_codex_curated_revision(final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the local product revision from the frozen final-claim ledger only."""

    paper_by_claim = {
        row["claim_id"]: str(row["final_claim"].get("paper_id"))
        for row in final_rows
        if row.get("final_disposition") != "SOURCE_CONFLICT_RETAINED"
    }

    def sentence(sentence_id: str, role: str, text: str, claim_ids: list[str]) -> dict[str, Any]:
        paper_ids = list(dict.fromkeys(paper_by_claim[claim_id] for claim_id in claim_ids))
        row = {
            "sentence_id": sentence_id,
            "sentence_role": role,
            "text": text,
            "supporting_claim_ids": claim_ids,
            "source_paper_ids": paper_ids,
            "evidence_role": "CROSS_STUDY_INTERPRETATION" if role == "reviewer_synthesis" else "FROZEN_FINAL_CLAIM",
        }
        if role == "reviewer_synthesis":
            row["material_supporting_claim_ids_by_paper"] = {
                paper_id: [claim_id for claim_id in claim_ids if paper_by_claim[claim_id] == paper_id]
                for paper_id in paper_ids
            }
        return row

    f3_limit = "CL-SU-fa5466ea832ed9fe-007"
    f3_pd = "CL-SU-fa5466ea832ed9fe-002"
    f3_scope = "CL-SU-fa5466ea832ed9fe-005"
    f3_metal = "CL-SU-6a771b839d148d00-001"
    f47_yield = "CL-SU-eb42b7e36b700462-001"
    f47_ee = "CL-SU-eb42b7e36b700462-002"
    f47_complex = "CL-SU-eb42b7e36b700462-003"
    f47_main = "CL-SU-eb42b7e36b700462-004"
    f47_dba = "CL-SU-eb42b7e36b700462-005"
    f47_no_dba = "CL-SU-eb42b7e36b700462-006"
    f47_exchange = "CL-SU-eb42b7e36b700462-007"
    p_yield = "CL-SU-79efb84b909e8690-001"
    p_ee = "CL-SU-79efb84b909e8690-002"
    p_scope = "CL-SU-79efb84b909e8690-003"
    p_spo = "CL-SU-79efb84b909e8690-004"
    p_kr = "CL-SU-79efb84b909e8690-005"
    p_terminal = "CL-SU-79efb84b909e8690-006"
    p_proposal = "CL-SU-79efb84b909e8690-007"
    p_l19 = "CL-SU-df53ec3ac051d023-001"
    p_nmr = "CL-SU-df53ec3ac051d023-002"
    p_resting = "CL-SU-df53ec3ac051d023-003"
    p_3aa_yield = "CL-SU-c909351db94ccb77-001"
    p_3aa_ee = "CL-SU-c909351db94ccb77-002"

    abstract = [
        sentence("PQ-A01", "review_context", "The review literature frames asymmetric allene synthesis as a persistent selectivity problem because generating an axially chiral allene and transferring that information without erosion have historically been achieved by only a limited set of asymmetric variants.", [f3_limit]),
        sentence("PQ-A02", "direct_result", "In one palladium system, allene 3am was isolated in 75% yield and 89% ee from 1a and 2m with a Pd/(R)-BINAP catalyst, CsOtBu, and dichloromethane at 20 °C.", [f47_yield, f47_ee]),
        sentence("PQ-A03", "direct_result", "In a later palladium allenylation, 3aa was reported in 90% isolated yield and 90% ee under Pd2(dba)3·CHCl3/L6 conditions in DMA/THF at 25 °C.", [p_yield, p_ee]),
        sentence("PQ-RS01", "reviewer_synthesis", "These two outcomes establish a bounded comparison: each study reaches high enantioselectivity, but one does so in an axial-allene-forming coupling and the other in an allenylation whose enyne partner supplies a distinct coordinating architecture.", [f47_ee, p_ee, p_terminal]),
    ]

    sections = [
        ("1. Scope and Source Selection", [
            {"sentence_id": "PQ-01", "sentence_role": "transition", "text": "The source set is intentionally narrow: a broad review provides context, while two palladium primary studies permit a bounded comparison of selectivity, substrate dependence, and mechanistic evidence.", "supporting_claim_ids": [], "source_paper_ids": [], "evidence_role": "TRANSITION"},
            sentence("PQ-02", "review_context", "The review records that spiro bisoxazoline ligands enabled highly enantioselective palladium-catalyzed cyclic allylations of allenyl hydrazines and of 2-iodoanilines with allenes, illustrating that ligand-controlled palladium chemistry already occupied several asymmetric allene settings.", [f3_pd]),
            sentence("PQ-03", "review_context", "It also notes that only a few examples of catalytic enantioselective cyclic allylation by carbopalladation were known, so broad generalizations are not justified by that review-level record.", ["CL-SU-fa5466ea832ed9fe-001"]),
            sentence("PQ-03A", "review_context", "That limitation matters for the present scope because a compact review should distinguish a documented palladium result from an assertion of field-wide coverage. The review source is used here to set that boundary, not to supply a mechanism for either primary transformation.", [f3_limit, "CL-SU-fa5466ea832ed9fe-001"]),
            sentence("PQ-04", "review_context", "Across catalyst classes, the review reports that changing the transition metal and base can change regioselectivity: palladium systems gave endo olefins, platinum or rhodium favored exo olefins, and nickel directed aryl addition to the terminal allene carbon.", [f3_metal]),
            sentence("PQ-05", "reviewer_synthesis", "The present comparison therefore does not treat all palladium allene chemistry as one mechanism. It asks instead how catalyst environment, substrate structure, and the evidentiary force of individual experiments constrain two reported asymmetric transformations.", [f3_limit, f47_complex, p_nmr]),
            sentence("PQ-05A", "review_context", "The review itself separates palladium, platinum, rhodium, and nickel outcomes by regioselectivity and mode of addition. This source-level diversity is a reason to retain the primary-study conditions rather than compress their results into a single generic palladium rule.", [f3_metal]),
            sentence("PQ-RS02", "reviewer_synthesis", "The review-level limitation and the two primary outcomes together support a selective conclusion rather than a universal one: strong enantioselectivity is demonstrable in defined palladium systems, while the breadth of asymmetric allene methods remains a separate question.", [f3_limit, f47_ee, p_ee]),
        ]),
        ("2. Catalyst and Ligand Control of Selectivity", [
            sentence("PQ-06", "direct_result", "The F47A catalytic example used 10 mol % Pd/(R)-BINAP with CsOtBu in dichloromethane and furnished 3am in 75% isolated yield after 24 h at 20 °C.", [f47_yield]),
            sentence("PQ-07", "direct_result", "Under those same reported conditions, the measured enantiomeric excess for 3am was 89% ee; this value is an outcome for that substrate, base, solvent, catalyst, and reaction time rather than a stand-alone descriptor of the ligand.", [f47_ee]),
            sentence("PQ-08", "direct_result", "For P403, optimization entry 23 used Pd2(dba)3·CHCl3, L6, and DMA/THF (1:1) at 25 °C for 24 h and reported 90% isolated yield of 3aa.", [p_yield]),
            sentence("PQ-09", "direct_result", "The same P403 optimization entry reported 90% ee for 3aa, again tying the selectivity value to a particular enyne-type propargylic carbamate, secondary phosphine oxide, ligand, and medium.", [p_ee]),
            sentence("PQ-10", "direct_result", "A separate P403 supporting-information entry reported 80% isolated yield of 3aa with L19 in dichloromethane at 25 °C over 12 h; this result documents a distinct ligand, medium, and reaction-time combination for the same product under otherwise nonidentical conditions.", [p_l19]),
            sentence("PQ-10A", "direct_result", "The L6 optimization and the L19 supporting-information entry are reported under different media and times. Accordingly, the entries document two individual conditions for 3aa and do not by themselves establish a controlled cross-ligand performance hierarchy.", [p_yield, p_l19]),
            sentence("PQ-10B", "direct_result", "For the F47A example, the reported 75% yield and 89% ee occur together in the specified catalytic experiment. Keeping the outcome and conditions in the same sentence prevents the selectivity value from being detached from the reaction system that produced it.", [f47_yield, f47_ee]),
            sentence("PQ-10C", "reviewer_synthesis", "The comparison is most useful when it preserves this conditional structure. F47A links Pd/(R)-BINAP, base, dichloromethane, and a defined allene-forming coupling, whereas P403 links Pd2(dba)3·CHCl3, L6 or L19, different media and times, an enyne-type carbamate, and a secondary phosphine oxide; those records support system-specific interpretation rather than an abstract ligand ranking.", [f47_yield, f47_ee, p_yield, p_ee, p_l19]),
            sentence("PQ-RS03", "reviewer_synthesis", "The paired high-ee entries show that catalyst and ligand choice matter in both studies, but their numerical agreement does not establish a shared selectivity mechanism because the reacting partners, media, and reported organometallic evidence differ.", [f47_ee, p_ee, f47_complex, p_nmr]),
        ]),
        ("3. Substrate Architecture and Reaction Boundaries", [
            sentence("PQ-11", "direct_result", "P403 reports that N-ethyl substrate 2n and N-benzyl substrate 2o were unreactive under the standard Pd2(dba)3·CHCl3/L6 conditions, identifying a boundary within the enyne-type propargylic-carbamate series.", [p_scope]),
            sentence("PQ-12", "direct_result", "The para-bromophenyl secondary phosphine oxide 1f did not give the desired product under the reported protocol, so the partner scope also contains an explicit failed example.", [p_spo]),
            sentence("PQ-13", "experimental_observation", "Under standard conditions, 2v gave only trace racemic product and 2w and 2x were unreactive; the authors use this pattern as experimental support for a key role of the terminal alkene group.", [p_terminal]),
            sentence("PQ-14", "experimental_observation", "In the kinetic-resolution experiment, enyne 2a was recovered with only slight enantiomeric enrichment, an observation that supports exclusion of an obvious kinetic-resolution pathway under the tested catalytic conditions.", [p_kr]),
            sentence("PQ-15", "review_context", "The review similarly records that electron-rich imines displayed low reactivity and required higher catalyst loading in an enantioselective [3+2] cycloaddition, showing that negative scope can define a useful reaction boundary without becoming a successful allene example.", [f3_scope]),
            sentence("PQ-15A", "direct_result", "The P403 failures are chemically specific: two N-substituted enynes were unreactive, one para-bromophenyl phosphine oxide did not furnish the desired product, and terminal-alkene-altered substrates gave trace racemate or no reaction. Each observation limits a reported substrate class rather than supplying a universal exclusion rule.", [p_scope, p_spo, p_terminal]),
            sentence("PQ-15B", "experimental_observation", "The slight enrichment of recovered 2a in the kinetic-resolution experiment is also deliberately narrow evidence. It supports exclusion of an obvious kinetic-resolution explanation under that experiment, but it does not establish every stereochemical event in the proposed allenylation pathway.", [p_kr]),
            sentence("PQ-15C", "reviewer_synthesis", "Read together, the unsuccessful P403 variants and the kinetic-resolution result do more than list exclusions: they identify which structural changes were tested and which simple stereochemical explanation was disfavored under the reported conditions. That evidence should guide substrate choice within the documented reaction family, while the review's separate low-reactivity example cautions against extending the boundary across unrelated transformations.", [p_scope, p_spo, p_terminal, p_kr, f3_scope]),
            sentence("PQ-RS04", "reviewer_synthesis", "The failed P403 variants and the review's low-reactivity example give a common methodological lesson: substrate limitations are positive information for delimiting a reported transformation, but they should not be recast as evidence that all palladium allene reactions fail for the same structural reason.", [p_scope, p_terminal, f3_scope]),
        ]),
        ("4. Mechanistic Evidence: Dynamic Intermediates, Coordination, and Competing Models", [
            sentence("PQ-16", "intermediate_isolation", "The F47A supporting information reports isolation of benzylidene-π-allylpalladium complex 5 in 84% yield after the stated THF and NaBArF4/dichloromethane sequence; isolation of that complex alone does not prove the catalytic pathway.", [f47_complex]),
            sentence("PQ-17", "experimental_observation", "The main text reports 76% yield for stoichiometric conversion of isolated complex 5 to 3an in THF at 20 °C; this report is not assigned a dibenzalacetone condition here.", [f47_main]),
            sentence("PQ-18", "experimental_observation", "In the supporting-information procedure, the analogous stoichiometric reaction containing two equivalents of dibenzalacetone gave 3an in 74% isolated yield after 12 h at 20 °C.", [f47_dba]),
            sentence("PQ-19", "experimental_observation", "The corresponding procedure without dibenzalacetone gave 62% isolated yield of 3an under the same THF, 20 °C, and 12 h conditions, providing a paired stoichiometric comparison.", [f47_no_dba]),
            sentence("PQ-20", "experimental_observation", "Spin-saturation-transfer measurements showed that dibenzalacetone accelerated interconversion of the two diastereomers of isolated complex 5 without changing their relative abundance, an observation about exchange behavior rather than direct proof of catalytic turnover.", [f47_exchange]),
            sentence("PQ-21", "experimental_observation", "For P403, 31P NMR showed new secondary-phosphine-oxide-associated peaks after adding 1a that disappeared after adding enyne 2a, supporting preferential Pd/L6 coordination with 2a in that comparison.", [p_nmr]),
            sentence("PQ-22", "author_proposal", "The P403 authors propose bidentate enyne coordination, oxidative addition with carbon-dioxide extrusion to vinylidene-π-allylpalladium III, secondary-phosphine-oxide deprotonation, and reductive elimination to 3aa.", [p_proposal]),
            sentence("PQ-23", "author_proposal", "They further state cautiously that a bidentate Pd/L6/enyne complex might be a catalyst resting state or a pre-transition-state intermediate, while noting that the evidence is not comprehensive.", [p_resting]),
            sentence("PQ-23A", "experimental_observation", "The F47A paired stoichiometric procedures distinguish two stated dibenzalacetone conditions: 74% isolated yield when dibenzalacetone was present and 62% isolated yield when it was absent. This contrast reports a condition-dependent outcome for complex 5 conversion, not a direct measurement of catalytic selectivity.", [f47_dba, f47_no_dba]),
            sentence("PQ-23B", "intermediate_isolation", "Complex 5 was isolated before the stoichiometric experiments, and its isolation was reported in 84% yield. The experimentally defensible statement is therefore that the species can be isolated and tested under the stated sequence; its placement in the catalytic pathway remains unproven by isolation alone.", [f47_complex]),
            sentence("PQ-23C", "experimental_observation", "The 31P NMR comparison in P403 links the disappearance of new secondary-phosphine-oxide-associated peaks to addition of enyne 2a. It supports preferential Pd/L6 coordination with 2a in that comparison, while leaving the complete sequence of elementary steps unresolved.", [p_nmr]),
            sentence("PQ-23D", "reviewer_synthesis", "The two records therefore carry different mechanistic weights. Isolation and exchange establish behavior for a defined F47A complex, while the P403 NMR experiment establishes a coordination-sensitive response after sequential addition; both observations narrow plausible interpretations, yet neither independently measures turnover, the stereodetermining event, or every intermediate in a catalytic cycle.", [f47_complex, f47_exchange, p_nmr]),
            sentence("PQ-RS05", "reviewer_synthesis", "Complex isolation and exchange measurements in F47A, together with coordination-sensitive NMR and a cautious resting-state proposal in P403, support treating both studies as mechanistically informative but differently bounded; neither record licenses conversion of an isolated or spectroscopically implicated species into a proven full catalytic cycle.", [f47_complex, f47_exchange, p_nmr, p_resting]),
        ]),
        ("5. Transferable Design Principles and Limitations", [
            sentence("PQ-24", "review_context", "The review states that electrophilic additions had often been considered synthetically less attractive because regioselectivity and stereoselectivity are not simply controlled, a caution that keeps selectivity design connected to the underlying reactivity problem.", ["CL-SU-fa5466ea832ed9fe-006"]),
            sentence("PQ-25", "review_context", "The review also reports a catalyst-dependent contrast in allenyne-1,6-diol cyclization, where gold gave 2,5-dihydrofurans and silver gave furans because the catalysts differentiated activation of double and triple bonds.", ["CL-SU-6a771b839d148d00-002"]),
            sentence("PQ-26", "direct_result", "The characterization entry for 3aa reports 90% isolated yield after a 40 h reaction, providing a product-level record alongside the separately reported optimization outcome.", [p_3aa_yield]),
            sentence("PQ-27", "direct_result", "The HPLC analysis in that 3aa characterization entry reports 90% ee, preserving the reported product-level selectivity measurement without generalizing it beyond the documented procedure.", [p_3aa_ee]),
            sentence("PQ-28", "review_context", "The review identifies a TADDOL-derived phosphoramidite ligand class for a gold-catalyzed asymmetric [2+2] cycloaddition of ene-allenes, which is useful context for ligand diversity but is not evidence for a palladium mechanism.", ["CL-SU-fa5466ea832ed9fe-003"]),
            sentence("PQ-28A", "review_context", "The review also describes catalyst-dependent product divergence in an allenyne-diol system. Its value here is comparative context: selectivity can depend on how a catalyst activates competing unsaturated groups, but that separate gold/silver example cannot be used to prove the coordination picture of a palladium primary study.", ["CL-SU-6a771b839d148d00-002"]),
            sentence("PQ-28B", "direct_result", "The product-level P403 records give 3aa as 90% isolated yield after 40 h and 90% ee by the stated HPLC analysis. These entries reinforce that the reported product outcome is traceable, while the mechanistic interpretation still depends on other, more limited observations.", [p_3aa_yield, p_3aa_ee]),
            sentence("PQ-28C", "review_context", "The review's treatment of palladium, platinum, rhodium, and nickel systems makes a related point about reaction design. Changes in metal and base were associated with different regioselective outcomes, so catalyst identity cannot be abstracted away when an allene-derived product pattern is discussed.", [f3_metal]),
            sentence("PQ-28D", "reviewer_synthesis", "A usable design principle follows from keeping these levels separate: product characterization secures the reported outcome, scope experiments define the reaction family, and intermediate or coordination experiments set the strength of mechanistic language. Cross-metal review examples illuminate why selectivity questions are sensitive to catalyst-controlled activation, but they remain context rather than evidence for either palladium pathway considered here.", [p_3aa_yield, p_3aa_ee, p_scope, p_terminal, f47_complex, p_nmr, f3_metal]),
            sentence("PQ-RS06", "reviewer_synthesis", "Across the two palladium reports, the transferable design principle is modest: successful conditions must be read alongside substrate failures and the specific observations that bear on catalyst-substrate organization, rather than inferred from a yield or ee value alone, and must remain attached to the individual experimental records from which each interpretive inference is drawn in this comparison.", [f47_yield, p_yield, p_scope, p_terminal, f47_exchange, p_nmr]),
        ]),
        ("6. Conclusions", [
            sentence("PQ-29", "reviewer_synthesis", "This focused review supports a bounded palladium-centered comparison of two primary studies against selected review context; it does not map every asymmetric allene method or convert these examples into a universal account of the field.", [f3_limit, f47_yield, p_yield]),
            sentence("PQ-30", "direct_result", "F47A reports an 89% ee allene-forming outcome under its stated Pd/(R)-BINAP conditions, whereas P403 reports 90% ee for allenylation under its stated Pd/L6 conditions.", [f47_ee, p_ee]),
            sentence("PQ-31", "reviewer_synthesis", "These outcomes establish that defined palladium systems can deliver high enantioselectivity for the reported substrates, while the broader review retains the unresolved challenge of stereoselective allene formation and axis-to-center transfer without chirality loss. Both records remain bounded by their respective partners and conditions.", [f47_ee, p_ee, f3_limit]),
            sentence("PQ-32", "reviewer_synthesis", "The transferable lesson is to treat catalyst environment, substrate architecture, and the experimental record as one design problem rather than to rank ligands from yield or ee alone.", [f47_yield, f47_ee, p_yield, p_ee]),
            sentence("PQ-32A", "experimental_observation", "For F47A, the dibenzalacetone-containing and dibenzalacetone-free stoichiometric procedures, together with the exchange experiment, show why an additive observation must remain attached to its measured complex chemistry.", [f47_dba, f47_no_dba, f47_exchange]),
            sentence("PQ-32B", "experimental_observation", "For P403, failed N-substituted enynes, the failed phosphine oxide, terminal-alkene-sensitive variants, and the kinetic-resolution probe define a practical substrate boundary without establishing a general exclusion rule beyond the tested series.", [p_scope, p_spo, p_terminal, p_kr]),
            sentence("PQ-32C", "intermediate_isolation", "Mechanistic confidence remains correspondingly limited: F47A provides an isolated palladium complex and a measured exchange response to dibenzalacetone, but neither observation alone establishes the full catalytic sequence.", [f47_complex, f47_exchange]),
            sentence("PQ-32D", "author_proposal", "P403 provides coordination-sensitive NMR and an author-proposed bidentate-coordination sequence that includes oxidative addition, carbon-dioxide extrusion, secondary-phosphine-oxide deprotonation, and reductive elimination to 3aa; the reported resting-state evidence remains incomplete.", [p_nmr, p_proposal, p_resting]),
            sentence("PQ-RS07", "reviewer_synthesis", "Taken together, the studies make the clearest case for reading selectivity, substrate restrictions, and mechanistic evidence together: performance is condition-specific, failed variants delimit scope, and observed intermediates or spectra constrain rather than complete a mechanistic explanation. That is the appropriate scale for a palladium-centered synthesis across these records.", [f47_ee, f47_exchange, p_ee, p_terminal, p_nmr, p_resting]),
        ]),
    ]
    payload = {
        "title": "Palladium-Centered Strategies for Asymmetric Allene Synthesis: Selectivity Control, Substrate Constraints, and Mechanistic Evidence",
        "abstract_sentences": abstract,
        "keywords": ["asymmetric allene synthesis", "palladium catalysis", "axial chirality", "substrate constraints", "mechanistic evidence"],
        "sections": [
            {
                "heading": heading,
                "paragraphs": [
                    {
                        "paragraph_id": f"PQ-P{index:02d}-{paragraph_index}",
                        "purpose": heading,
                        "sentences": paragraph_rows,
                    }
                    for paragraph_index, paragraph_rows in enumerate(
                        ([rows[:3], rows[3:6], rows[6:]] if heading == "6. Conclusions" else [rows]),
                        start=1,
                    )
                    if paragraph_rows
                ],
            }
            for index, (heading, rows) in enumerate(sections, start=1)
        ],
        "comparison_table": [
            {"source_study": "F47A", "catalytic_or_reaction_strategy": "Pd/(R)-BINAP allene formation", "representative_transformation": "1a with 2m under CsOtBu/CH2Cl2", "key_supported_outcome": "3am: 75% yield, 89% ee", "mechanistic_or_control_evidence": "Complex 5 isolation; paired DBA stoichiometry; exchange measurement", "evidence_limitation_warning": "Isolation and exchange do not prove the full catalytic pathway", "evidence_role": "PRIMARY_STUDY", "supporting_claim_ids": [f47_yield, f47_ee, f47_complex, f47_dba, f47_no_dba, f47_exchange]},
            {"source_study": "P403", "catalytic_or_reaction_strategy": "Pd/L6 asymmetric allenylation", "representative_transformation": "1a with enyne 2a in DMA/THF", "key_supported_outcome": "3aa: 90% yield, 90% ee", "mechanistic_or_control_evidence": "Terminal-alkene probe; 31P NMR; bidentate-coordination proposal", "evidence_limitation_warning": "Resting-state and pathway assignments remain author proposals", "evidence_role": "PRIMARY_STUDY", "supporting_claim_ids": [p_yield, p_ee, p_terminal, p_nmr, p_proposal, p_resting]},
        ],
        "design_principles_table": [
            {"design_lever": "Catalyst and ligand environment", "direct_observation": "High ee was reported in both defined palladium systems", "substrate_boundary": "The two reactions use different partners and media", "mechanistic_evidence": "Different organometallic observations support each study", "practical_implication": "Interpret ligand performance within its reaction system", "supporting_claim_ids": [f47_ee, p_ee]},
            {"design_lever": "Substrate architecture", "direct_observation": "Several altered P403 substrates were unreactive or gave trace racemate", "substrate_boundary": "Terminal alkene and partner identity matter in the reported series", "mechanistic_evidence": "Scope failures and kinetic-resolution experiment", "practical_implication": "Use failure patterns to delimit the working substrate class", "supporting_claim_ids": [p_scope, p_spo, p_kr, p_terminal]},
            {"design_lever": "Intermediate evidence", "direct_observation": "Complex 5 was isolated and DBA changed stoichiometric outcome", "substrate_boundary": "The evidence is specific to isolated-complex experiments", "mechanistic_evidence": "Exchange measurement without changed diastereomer ratio", "practical_implication": "Do not equate an isolated species with a proven catalytic cycle", "supporting_claim_ids": [f47_complex, f47_dba, f47_no_dba, f47_exchange]},
            {"design_lever": "Coordination proposal", "direct_observation": "31P NMR changed after sequential addition of reaction partners", "substrate_boundary": "Observation is tied to the Pd/L6/enyne comparison", "mechanistic_evidence": "Bidentate and resting-state assignments are cautious author proposals", "practical_implication": "Separate coordination evidence from pathway proof", "supporting_claim_ids": [p_nmr, p_proposal, p_resting]},
        ],
    }
    selected = {claim_id for row in [*abstract, *[sentence_row for _, sentence_rows in sections for sentence_row in sentence_rows]] for claim_id in row["supporting_claim_ids"]}
    payload["selected_claim_ids"] = sorted(selected)
    payload["intentionally_omitted_claim_ids"] = sorted(set(paper_by_claim) - selected)
    return payload


def _validate_curated_editorial_shape(payload: dict[str, Any]) -> dict[str, int]:
    conclusion_sections = [section for section in payload.get("sections", []) if section.get("heading") == "6. Conclusions"]
    if len(conclusion_sections) != 1:
        raise ValueError(f"curated editorial shape requires exactly one '6. Conclusions' section; found {len(conclusion_sections)}")
    paragraphs = conclusion_sections[0].get("paragraphs", [])
    if len(paragraphs) != 3:
        raise ValueError(f"curated editorial shape requires exactly 3 conclusion paragraphs; found {len(paragraphs)}")
    conclusion_text = " ".join(
        sentence.get("text", "")
        for paragraph in paragraphs
        for sentence in paragraph.get("sentences", [])
    )
    conclusion_word_count = len(re.findall(r"\b[A-Za-z][A-Za-z'’-]*\b", conclusion_text))
    if not 280 <= conclusion_word_count <= 340:
        raise ValueError(
            "curated editorial shape requires 280-340 English prose words in conclusions; "
            f"found {conclusion_word_count}"
        )
    return {
        "conclusion_section_count": len(conclusion_sections),
        "conclusion_paragraph_count": len(paragraphs),
        "conclusion_word_count": conclusion_word_count,
    }



def _export_docx(markdown: str, python_executable: Path, repo_root: Path) -> tuple[Path, dict[str, Any], tempfile.TemporaryDirectory[str]]:
    temporary = tempfile.TemporaryDirectory(prefix="finished-review-docx-")
    root = Path(temporary.name)
    markdown_path = root / "final_review.md"
    docx_path = root / "final_review.docx"
    markdown_path.write_text(markdown, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    result = subprocess.run(
        [
            str(python_executable),
            str(repo_root / "skills/review-export-docx/scripts/md2docx.py"),
            "--input",
            str(markdown_path),
            "--output",
            str(docx_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode or not docx_path.is_file():
        temporary.cleanup()
        raise RuntimeError(f"DOCX export failed: {result.stderr.strip() or result.stdout.strip()}")
    integrity = inspect_docx_citation_links(docx_path)
    if integrity["reference_ids"] != [1, 2, 3] or integrity["cited_reference_ids"] != [1, 2, 3]:
        temporary.cleanup()
        raise ValueError("DOCX does not bind all three numbered references")
    if integrity["bookmark_count"] != 3 or integrity["doi_hyperlink_count"] != 3:
        temporary.cleanup()
        raise ValueError("DOCX bookmark or DOI link count is incomplete")
    return docx_path, integrity, temporary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the first complete bounded evidence-grounded mini-review.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--workspace-parent", type=Path, default=Path(os.environ.get("AI_REVIEW_WORKSPACES", Path.home() / "my_folder/AI_REVIEW_WORKSPACES")))
    parser.add_argument("--output-parent", type=Path, default=REPO_ROOT / "review-projects")
    parser.add_argument(
        "--baseline-markdown",
        type=Path,
        default=REPO_ROOT / "review-projects/case-01-allene-mini-review-20260715T-continuousZ/final_review.md",
        help="Read-only Markdown baseline used for the product text diff.",
    )
    parser.add_argument("--run-id")
    parser.add_argument("--docx-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--use-qwen", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--mock-response", type=Path)
    parser.add_argument("--curated-revision", action="store_true", help="Build the local Codex-authored revision from frozen final claims only.")
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--max-output-tokens", type=int, default=16000)
    parser.add_argument("--connect-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--first-byte-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--total-timeout-seconds", type=float, default=600.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        modes = [args.mock_response is not None, args.curated_revision, args.use_qwen and args.allow_network]
        if sum(modes) != 1:
            raise ValueError("choose exactly one of --curated-revision, --mock-response, or --use-qwen --allow-network")
        if (args.mock_response is not None or args.curated_revision) and (args.use_qwen or args.allow_network):
            raise ValueError("local and network generation modes are mutually exclusive")
        repo_root = args.repo_root.resolve()
        if args.mock_response is None and not args.curated_revision and _git(repo_root, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("real generation requires a clean committed tracked worktree")
        repo_head = _git(repo_root, "rev-parse", "HEAD")
        closure_root = args.workspace_parent.resolve() / CLOSURE_RUN_ID
        claims_path = closure_root / "final/final_reconciled_claims.jsonl"
        manifest_path = closure_root / "HASH_MANIFEST.sha256"
        input_hashes = verify_frozen_inputs(
            claims_path,
            manifest_path,
            EXPECTED_FINAL_CLAIMS_SHA256,
            EXPECTED_CLOSURE_MANIFEST_SHA256,
        )
        final_rows = _read_jsonl(claims_path)
        evidence_plan = build_finished_review_plan(final_rows)
        run_id = args.run_id or time.strftime("case-01-allene-mini-review-%Y%m%dT%H%M%SZ", time.gmtime())
        if not run_id.startswith("case-01-allene-mini-review-") or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
            raise ValueError("invalid run ID")
        output_root = args.output_parent.resolve() / run_id

        if args.curated_revision:
            payload = _build_codex_curated_revision(final_rows)
            _validate_curated_editorial_shape(payload)
            validation = validate_finished_review_payload(payload, final_rows, BIBLIOGRAPHY, min_words=2000, max_words=2400)
            generation = {
                "payload": payload,
                "validation": validation,
                "request_count": 0,
                "repair_used": False,
                "attempts": [],
            }
            selected_model = "not_used_current_run"
            capability = {"status": "NOT_USED_LOCAL_EDITORIAL_REVISION", "query_count": 0, "region": "offline"}
        elif args.mock_response:
            selected_model = "offline-mock"
            capability = {"status": "NOT_USED_OFFLINE_MOCK", "query_count": 0, "region": "offline"}
            provider: Any = FileJsonProvider(args.mock_response)
        else:
            selected_model, capability = _select_model()
            provider = QwenJsonProvider(selected_model, args)
        if not args.curated_revision:
            generation = generate_finished_review_with_bounded_repair(
                provider,
                final_rows,
                evidence_plan,
                BIBLIOGRAPHY,
                min_words=2000,
                max_words=2400,
            )
        if generation["validation"]["blockers"]:
            diagnostic_root = output_root.with_name(f"{output_root.name}-failed")
            write_failed_generation_diagnostic(
                output_root=diagnostic_root,
                payload=generation["payload"],
                final_rows=final_rows,
                bibliography_metadata=BIBLIOGRAPHY,
                validation=generation["validation"],
                generation_manifest={
                    "actual_model": selected_model,
                    "request_count": generation["request_count"],
                    "repair_used": generation["repair_used"],
                    "attempts": generation["attempts"],
                    "capability_check": capability,
                    "repo_head": repo_head,
                    "input_hashes": input_hashes,
                },
            )
            raise ValueError(f"Qwen output retained blockers after bounded repair: {generation['validation']['blockers']}")
        markdown, _citations = render_final_review(generation["payload"], final_rows, BIBLIOGRAPHY)
        docx_path, docx_integrity, temporary = _export_docx(markdown, args.docx_python.resolve(), repo_root)
        try:
            generation_manifest = {
                "schema_version": "finished-review-generation-2.0",
                "provider": "codex_exec_curated_revision" if args.curated_revision else ("alibaba_openai_compatible" if args.mock_response is None else "offline-mock"),
                "endpoint_class": capability.get("endpoint_class", "offline"),
                "base_url": "not_used" if (args.curated_revision or args.mock_response) else "redacted",
                "actual_model": selected_model,
                "current_run_model_requests": generation["request_count"],
                "authoring_mode": "codex_exec_curated_revision" if args.curated_revision else "provider_generation",
                "authoring_agent_model": "gpt-5.6-terra" if args.curated_revision else None,
                "final_text_origin": "CURATED_FROM_FROZEN_FINAL_CLAIMS_NO_EXTERNAL_PROVIDER_CALL" if args.curated_revision else "PROVIDER_GENERATED_FROM_FROZEN_FINAL_CLAIMS",
                "reused_upstream_generation_payload": False if args.curated_revision else None,
                "historical_generation": {
                    "model": "qwen3.7-max",
                    "request_count": 2,
                    "role": "historical provenance only; not a source of this curated final text",
                },
                "maximum_completion_requests": 0 if args.curated_revision else 2,
                "repair_used": generation["repair_used"],
                "attempts": generation["attempts"],
                "parameters": (
                    {"model_generation": "not_used"}
                    if args.curated_revision
                    else {
                        "temperature": args.temperature,
                        "max_output_tokens": args.max_output_tokens,
                        "response_format": "json_object",
                        "thinking_enabled": False,
                        "search_enabled": False,
                    }
                ),
                "capability_check": capability,
                "repo_head": repo_head,
                "input_hashes": input_hashes,
                "docx_integrity": docx_integrity,
            }
            result = write_finished_review_package(
                output_root=output_root,
                repository_root=repo_root,
                payload=generation["payload"],
                final_rows=final_rows,
                bibliography_metadata=BIBLIOGRAPHY,
                evidence_plan=evidence_plan,
                generation_manifest=generation_manifest,
                replay_performed=False,
                replay_note=(
                    "QoderWork replay was not performed; this package is a local curated revision."
                    if args.curated_revision
                    else "QoderWork replay was not performed by this delivery command."
                ),
                docx_source=docx_path,
                docx_integrity=docx_integrity,
                baseline_markdown=args.baseline_markdown.resolve(),
                min_words=2000,
                max_words=2400,
            )
        finally:
            temporary.cleanup()
        current = verify_frozen_inputs(
            claims_path,
            manifest_path,
            EXPECTED_FINAL_CLAIMS_SHA256,
            EXPECTED_CLOSURE_MANIFEST_SHA256,
        )
        if current != input_hashes:
            raise RuntimeError("a frozen input changed during finished-review delivery")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "stage": result["stage"],
                    "output_root": str(output_root),
                    "final_review_md_sha256": sha256_file(output_root / "final_review.md"),
                    "final_review_docx_sha256": sha256_file(output_root / "final_review.docx"),
                    "word_count": result["word_count"],
                    "model": selected_model,
                    "request_count": generation["request_count"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"finished-review-delivery: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
