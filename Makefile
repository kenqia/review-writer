.PHONY: smoke quality-check qoderwork-check provider-check qwen-hello-dry-run judge-check tiny-e2e-check real-lite-preflight real-lite-e2e-check dashboard-real-lite-check eval-baseline-check portability-check reality-audit-check clean-3paper-recommend-check clean-3paper-approval-check clean-3paper-pdf-verify-check clean-3paper-biblio-check clean-3paper-biblio-web-check clean-3paper-claims-check clean-3paper-e2e-check clean-3paper-eval-check dashboard-clean-3paper-check bailian-rag-preflight-check rag-local-retrieval-check bailian-small-kb-payload-check bailian-payload-parse-readiness-check bailian-small-kb-pilot-dry-run bailian-small-kb-official-sdk-dry-run bailian-official-pilot-fix-check bailian-sdk-e2e-closure-check bailian-small-kb-official-sdk-real-command bailian-lease-probe-dry-run bailian-lease-probe-real-command bailian-endpoint-diagnostics-check bailian-minimal-lease-repro-dry-run bailian-minimal-lease-repro-real-command bailian-sdk-transport-introspection bailian-retrieval-contract-check bailian-retrieval-qa-dry-run bailian-phase6-final-check retrieval-generation-check grounded-section-check phase7-pilot-dry-run phase7-real-preflight phase8-preflight phase8-source-inventory-check phase8-extraction-check phase8-review-package-check phase8-dashboard-check phase8-decision-writer-check phase8-ai-adjudication-check phase8-v2-semantic-input-check phase8-v3-source-first-check phase8-v3-1-source-first-check phase8-v3-1-1-source-first-check phase8-v3-1-1-layer-b-check phase8-v3-1-1-reconciliation-check phase8-v3-1-1-closure-check phase8b-grounded-vertical-slice-check phase8b-grounded-vertical-slice-v2-check phase8b-salvage-check finished-review-delivery-check bailian-transport-matrix-dry-run bailian-transport-matrix-real-command bailian-category-introspection bailian-category-discovery-dry-run bailian-category-discovery-real-command bailian-category-lease-reprobe-real-command bailian-category-type-matrix-dry-run bailian-category-type-matrix-real-command bailian-sdk-env-check bailian-sdk-env-strict-check offline-ci-workflow-check release-readiness-check

.PHONY: m0-portability-check

PYTHON ?= python3
BAILIAN_SDK_PYTHON ?= conda run -n review-writer-bailian python
PHASE8_PYTHON ?= conda run -n review-writer-phase8 python
REPO_ROOT ?= $(CURDIR)
SEARCH_ROOT ?= $(abspath $(REPO_ROOT)/..)
REAL_LITE_OUTPUT_ROOT ?= /tmp/review_writer_real_lite_e2e

smoke:
	/usr/bin/python3 tests/test_fresh_source_syntax.py
	$(PYTHON) tests/test_project_manifest_schema.py
	$(PYTHON) tests/test_project_manifest_resolver.py
	$(PYTHON) -m py_compile $$(find skills view scripts -name '*.py' -type f)
	$(PYTHON) skills/review-writing-orchestrator/scripts/project_status.py --help >/dev/null
	$(PYTHON) skills/review-final-audit-release/scripts/final_audit_scan.py --help >/dev/null

quality-check:
	$(PYTHON) scripts/repo_safety_check.py
	$(PYTHON) tests/test_quality_validators.py
	$(PYTHON) scripts/validators/validate_review_quality.py \
		--draft tests/fixtures/quality/good_minimal_review.md \
		--output-json /tmp/review_writer_quality_check.json \
		--output-md /tmp/review_writer_quality_check.md

m0-portability-check:
	$(PYTHON) tests/test_project_manifest_schema.py
	$(PYTHON) tests/test_project_manifest_resolver.py
	$(PYTHON) tests/test_project_m0_contract.py
	@test -f tests/fixtures/m0/synthetic/project.manifest.json
	@! rg -n 'P403|F3I|F47A|44/37/7|allene' review_writer/project schemas/project scripts/project.py

finished-review-delivery-check:
	/usr/bin/python3 tests/test_fresh_source_syntax.py
	$(PYTHON) tests/test_finished_review_delivery.py
	$(PYTHON) tests/test_docx_citation_links.py
	$(PYTHON) tests/test_docx_product_quality.py
	$(PYTHON) scripts/delivery/run_finished_mini_review.py --help >/dev/null

qoderwork-check:
	$(PYTHON) scripts/check_qoderwork_skills.py \
		--skills-dir qoderwork/skills \
		--output-json /tmp/qoderwork_skill_check.json \
		--output-md /tmp/qoderwork_skill_check.md \
		--strict
	$(PYTHON) scripts/install_qoderwork_skills.py --dry-run

provider-check:
	$(PYTHON) tests/test_provider_adapters.py
	$(PYTHON) scripts/check_providers.py \
		--config config/providers.example.yaml \
		--output-json /tmp/provider_check.json \
		--output-md /tmp/provider_check.md \
		--strict

qwen-hello-dry-run:
	$(PYTHON) scripts/hello_qwen_openai_compatible.py \
		--dry-run \
		--output-json /tmp/qwen_hello_dry.json \
		--output-md /tmp/qwen_hello_dry.md

judge-check:
	$(PYTHON) tests/test_qwen_judge_safety.py
	$(PYTHON) tests/test_qwen_judge_timeout_hardening.py
	$(PYTHON) scripts/llm_judges/qwen_review_quality_judge.py --dry-run
	$(PYTHON) scripts/validators/validate_review_quality.py \
		--draft tests/fixtures/judge/bad_title_alignment.md \
		--judge-mode offline \
		--output-json /tmp/quality_with_judge.json \
		--output-md /tmp/quality_with_judge.md \
		--judge-output-json /tmp/judge_report.json \
		--judge-output-md /tmp/judge_report.md

tiny-e2e-check:
	$(PYTHON) tests/test_tiny_e2e_workflow.py
	$(PYTHON) scripts/demo/run_tiny_e2e.py \
		--demo-root demo_projects/tiny_allene_review \
		--output-root /tmp/review_writer_tiny_e2e \
		--strict

real-lite-preflight:
	$(PYTHON) scripts/demo/build_real_lite_manifest.py \
		--search-root "$(SEARCH_ROOT)" \
		--repo-root "$(REPO_ROOT)" \
		--output-json /tmp/real_lite_asset_manifest.json \
		--output-md /tmp/real_lite_asset_manifest.md \
		--max-papers 5 \
		--strict
	$(PYTHON) tests/test_real_lite_manifest.py

real-lite-e2e-check:
	$(PYTHON) tests/test_real_lite_e2e_workflow.py
	$(PYTHON) scripts/demo/run_real_lite_e2e.py \
		--demo-root demo_projects/real_lite_allene_review \
		--output-root "$(REAL_LITE_OUTPUT_ROOT)" \
		--strict

dashboard-real-lite-check:
	$(PYTHON) tests/test_dashboard_real_lite_payload.py

eval-baseline-check:
	$(PYTHON) tests/test_eval_baseline.py
	$(PYTHON) scripts/eval/run_eval_baseline.py \
		--output-root "$(REAL_LITE_OUTPUT_ROOT)" \
		--baseline evals/baselines/real_lite_v1.yaml \
		--expected evals/fixtures/real_lite_expected_metrics.json \
		--output-json /tmp/real_lite_eval_report.json \
		--output-md /tmp/real_lite_eval_report.md \
		--strict

portability-check:
	$(PYTHON) tests/test_portability.py
	$(PYTHON) scripts/check_portability.py \
		--output-json /tmp/portability_report.json \
		--output-md /tmp/portability_report.md \
		--strict

reality-audit-check:
	$(PYTHON) tests/test_real_lite_input_audit.py
	$(PYTHON) tests/test_real_lite_output_audit.py
	$(PYTHON) scripts/audit/audit_real_lite_inputs.py \
		--demo-root demo_projects/real_lite_allene_review \
		--output-json /tmp/real_lite_input_audit.json \
		--output-md /tmp/real_lite_input_audit.md \
		--strict
	$(PYTHON) scripts/audit/audit_real_lite_outputs.py \
		--output-root /tmp/review_writer_real_lite_e2e \
		--input-demo-root demo_projects/real_lite_allene_review \
		--output-json /tmp/real_lite_output_audit.json \
		--output-md /tmp/real_lite_output_audit.md \
		--strict

clean-3paper-recommend-check:
	$(PYTHON) tests/test_clean_3paper_recommendation.py
	$(PYTHON) scripts/demo/recommend_clean_3paper_candidates.py \
		--paper-root chem_papers \
		--real-lite-root demo_projects/real_lite_allene_review \
		--output-json /tmp/clean_3paper_recommendations.json \
		--output-md /tmp/clean_3paper_recommendations.md \
		--strict

clean-3paper-approval-check:
	$(PYTHON) tests/test_clean_3paper_approval_pack.py
	$(PYTHON) scripts/demo/check_clean_3paper_approval_pack.py \
		--dataset-root demo_projects/clean_3paper_allene_review \
		--strict

clean-3paper-pdf-verify-check:
	$(PYTHON) tests/test_clean_3paper_pdf_verification.py
	$(PYTHON) scripts/demo/verify_clean_3paper_pdfs.py \
		--dataset-root demo_projects/clean_3paper_allene_review \
		--paper-root chem_papers \
		--output-json /tmp/clean_3paper_pdf_verification.json \
		--output-md /tmp/clean_3paper_pdf_verification.md \
		--strict
	$(PYTHON) tests/test_clean_3paper_audit.py
	$(PYTHON) scripts/audit/audit_clean_3paper_dataset.py \
		--dataset-root demo_projects/clean_3paper_allene_review \
		--output-json /tmp/clean_3paper_audit.json \
		--output-md /tmp/clean_3paper_audit.md \
		--strict

clean-3paper-biblio-check:
	$(PYTHON) tests/test_clean_3paper_bibliography_verification.py
	$(PYTHON) scripts/demo/verify_clean_3paper_bibliography.py \
		--dataset-root demo_projects/clean_3paper_allene_review \
		--paper-root chem_papers \
		--output-json /tmp/clean_3paper_bibliography_verification.json \
		--output-md /tmp/clean_3paper_bibliography_verification.md \
		--strict

clean-3paper-biblio-web-check:
	$(PYTHON) scripts/demo/verify_clean_3paper_bibliography.py \
		--dataset-root demo_projects/clean_3paper_allene_review \
		--paper-root chem_papers \
		--allow-network-metadata \
		--output-json /tmp/clean_3paper_bibliography_verification_web.json \
		--output-md /tmp/clean_3paper_bibliography_verification_web.md \
		--strict

clean-3paper-claims-check:
	$(PYTHON) tests/test_clean_3paper_claims_figures.py
	$(PYTHON) scripts/demo/extract_clean_3paper_claims_figures.py \
		--dataset-root demo_projects/clean_3paper_allene_review \
		--paper-root chem_papers \
		--output-json /tmp/clean_3paper_claims_figures.json \
		--output-md /tmp/clean_3paper_claims_figures.md \
		--strict
	$(PYTHON) tests/test_clean_3paper_audit.py
	$(PYTHON) scripts/audit/audit_clean_3paper_dataset.py \
		--dataset-root demo_projects/clean_3paper_allene_review \
		--output-json /tmp/clean_3paper_audit.json \
		--output-md /tmp/clean_3paper_audit.md \
		--strict

clean-3paper-e2e-check:
	$(PYTHON) tests/test_clean_3paper_e2e_workflow.py
	$(PYTHON) scripts/demo/run_clean_3paper_e2e.py \
		--demo-root demo_projects/clean_3paper_allene_review \
		--output-root /tmp/review_writer_clean_3paper_e2e \
		--strict

clean-3paper-eval-check:
	$(PYTHON) tests/test_clean_3paper_eval.py
	$(PYTHON) scripts/eval/run_clean_3paper_eval.py \
		--output-root /tmp/review_writer_clean_3paper_e2e \
		--baseline evals/baselines/clean_3paper_v1.yaml \
		--expected evals/fixtures/clean_3paper_expected_metrics.json \
		--output-json /tmp/clean_3paper_eval_report.json \
		--output-md /tmp/clean_3paper_eval_report.md \
		--strict

dashboard-clean-3paper-check:
	$(PYTHON) tests/test_dashboard_clean_3paper_payload.py

bailian-rag-preflight-check:
	$(PYTHON) tests/test_bailian_preflight.py
	$(PYTHON) scripts/rag/bailian_preflight.py \
		--clean-root demo_projects/clean_3paper_allene_review \
		--config rag/bailian/preflight_config.example.yaml \
		--output-json /tmp/bailian_rag_preflight.json \
		--output-md /tmp/bailian_rag_preflight.md \
		--strict

rag-local-retrieval-check:
	$(PYTHON) tests/test_local_retrieval_baseline.py
	$(PYTHON) scripts/rag/local_retrieval_baseline.py \
		--manifest /tmp/bailian_no_upload_corpus_manifest.json \
		--questions evals/fixtures/rag_expected_questions.json \
		--output-json /tmp/local_retrieval_baseline_report.json \
		--output-md /tmp/local_retrieval_baseline_report.md \
		--strict

bailian-small-kb-payload-check:
	$(PYTHON) tests/test_bailian_small_kb_payload.py
	$(PYTHON) scripts/rag/build_bailian_small_kb_payload.py \
		--clean-root demo_projects/clean_3paper_allene_review \
		--output-jsonl /tmp/bailian_small_kb_payload.jsonl \
		--output-md /tmp/bailian_small_kb_payload.md \
		--output-manifest /tmp/bailian_small_kb_payload_manifest.json \
		--strict

bailian-payload-parse-readiness-check:
	$(PYTHON) tests/test_bailian_payload_parse_readiness.py
	$(PYTHON) scripts/rag/check_bailian_payload_parse_readiness.py \
		--payload-md /tmp/bailian_small_kb_upload_payload.md \
		--output-json /tmp/bailian_payload_parse_readiness.json \
		--output-md /tmp/bailian_payload_parse_readiness.md \
		--strict

bailian-small-kb-pilot-dry-run:
	$(PYTHON) tests/test_bailian_small_kb_pilot_safety.py
	$(PYTHON) scripts/rag/bailian_small_kb_pilot.py \
		--payload-jsonl /tmp/bailian_small_kb_payload.jsonl \
		--questions evals/fixtures/rag_expected_questions.json \
		--output-json /tmp/bailian_small_kb_pilot_dry.json \
		--output-md /tmp/bailian_small_kb_pilot_dry.md \
		--strict

bailian-small-kb-official-sdk-dry-run:
	$(PYTHON) tests/test_bailian_small_kb_pilot_safety.py
	$(PYTHON) scripts/rag/bailian_small_kb_pilot.py \
		--payload-jsonl /tmp/bailian_small_kb_payload.jsonl \
		--questions evals/fixtures/rag_expected_questions.json \
		--output-json /tmp/bailian_small_kb_pilot_official_sdk_dry.json \
		--output-md /tmp/bailian_small_kb_pilot_official_sdk_dry.md \
		--use-official-sdk \
		--strict

bailian-official-pilot-fix-check:
	$(PYTHON) tests/test_bailian_create_index_request.py
	$(PYTHON) tests/test_bailian_retrieve_success_check.py
	$(PYTHON) tests/test_bailian_small_kb_pilot_safety.py
	$(PYTHON) scripts/rag/bailian_small_kb_pilot.py \
		--payload-jsonl /tmp/bailian_small_kb_payload.jsonl \
		--questions evals/fixtures/rag_expected_questions.json \
		--output-json /tmp/bailian_small_kb_pilot_fix_dry.json \
		--output-md /tmp/bailian_small_kb_pilot_fix_dry.md \
		--use-official-sdk \
		--strict

bailian-sdk-e2e-closure-check:
	$(PYTHON) tests/test_bailian_sdk_e2e_closure.py
	$(PYTHON) scripts/rag/bailian_cleanup_orphan_file.py \
		--report-json /tmp/bailian_orphan_cleanup_fixture.json \
		--output-json /tmp/bailian_orphan_file_cleanup_dry.json \
		--output-md /tmp/bailian_orphan_file_cleanup_dry.md \
		--strict

bailian-small-kb-official-sdk-real-command:
	@printf '%s\n' 'zsh -ic '\''cd $(REPO_ROOT) && conda run -n review-writer-bailian python scripts/rag/build_bailian_small_kb_payload.py --clean-root demo_projects/clean_3paper_allene_review --output-jsonl /tmp/bailian_small_kb_payload.jsonl --output-md /tmp/bailian_small_kb_payload.md --output-manifest /tmp/bailian_small_kb_payload_manifest.json --strict && conda run -n review-writer-bailian python scripts/rag/bailian_small_kb_pilot.py --payload-jsonl /tmp/bailian_small_kb_payload.jsonl --questions evals/fixtures/rag_expected_questions.json --output-json /tmp/bailian_small_kb_pilot_real.json --output-md /tmp/bailian_small_kb_pilot_real.md --endpoint bailian.cn-beijing.aliyuncs.com --region cn-beijing --category-id default --transport-mode no_proxy --allow-network --allow-upload --use-official-sdk --cleanup --strict'\'''

bailian-lease-probe-dry-run:
	$(PYTHON) tests/test_bailian_lease_probe_safety.py
	$(PYTHON) scripts/rag/bailian_lease_probe.py \
		--payload-md /tmp/bailian_small_kb_upload_payload.md \
		--output-json /tmp/bailian_lease_probe_dry.json \
		--output-md /tmp/bailian_lease_probe_dry.md \
		--strict

bailian-lease-probe-real-command:
	@printf '%s\n' 'zsh -ic '\''cd $(REPO_ROOT) && conda run -n review-writer-bailian python scripts/rag/bailian_lease_probe.py --payload-md /tmp/bailian_small_kb_upload_payload.md --output-json /tmp/bailian_lease_probe_real.json --output-md /tmp/bailian_lease_probe_real.md --endpoint bailian.cn-beijing.aliyuncs.com --region cn-beijing --category-id default --allow-network --use-official-sdk --strict'\'''

bailian-endpoint-diagnostics-check:
	$(PYTHON) tests/test_bailian_endpoint_diagnostics.py
	$(PYTHON) scripts/rag/bailian_endpoint_diagnostics.py \
		--endpoint bailian.cn-beijing.aliyuncs.com \
		--output-json /tmp/bailian_endpoint_diagnostics.json \
		--output-md /tmp/bailian_endpoint_diagnostics.md \
		--strict

bailian-minimal-lease-repro-dry-run:
	$(PYTHON) tests/test_bailian_minimal_lease_repro_safety.py
	$(PYTHON) scripts/rag/bailian_minimal_lease_repro.py \
		--endpoint bailian.cn-beijing.aliyuncs.com \
		--category-id default \
		--output-json /tmp/bailian_minimal_lease_repro_dry.json \
		--output-md /tmp/bailian_minimal_lease_repro_dry.md \
		--strict

bailian-minimal-lease-repro-real-command:
	@printf '%s\n' 'zsh -ic '\''cd $(REPO_ROOT) && conda run -n review-writer-bailian python scripts/rag/bailian_minimal_lease_repro.py --endpoint bailian.cn-beijing.aliyuncs.com --category-id default --output-json /tmp/bailian_minimal_lease_repro_real.json --output-md /tmp/bailian_minimal_lease_repro_real.md --allow-network --strict'\'''

bailian-sdk-transport-introspection:
	$(PYTHON) tests/test_bailian_sdk_transport_introspection.py
	$(BAILIAN_SDK_PYTHON) scripts/rag/bailian_sdk_transport_introspection.py \
		--output-json /tmp/bailian_sdk_transport_introspection.json \
		--output-md /tmp/bailian_sdk_transport_introspection.md \
		--strict

bailian-retrieval-contract-check:
	$(PYTHON) tests/test_bailian_retrieve_contract_introspection.py
	$(BAILIAN_SDK_PYTHON) scripts/rag/bailian_retrieve_contract_introspection.py \
		--output-json /tmp/bailian_retrieve_contract_introspection.json \
		--output-md /tmp/bailian_retrieve_contract_introspection.md \
		--strict

bailian-retrieval-qa-dry-run:
	$(PYTHON) tests/test_bailian_retrieval_qa.py
	$(PYTHON) scripts/rag/bailian_retrieval_qa.py \
		--index-id dry-run-index-redacted \
		--questions evals/fixtures/rag_expected_questions.json \
		--output-json /tmp/bailian_retrieval_qa_dry.json \
		--output-md /tmp/bailian_retrieval_qa_dry.md \
		--strict

bailian-phase6-final-check:
	$(PYTHON) tests/test_bailian_retrieve_contract_introspection.py
	$(PYTHON) tests/test_bailian_retrieve_success_check.py
	$(PYTHON) tests/test_bailian_retrieval_qa.py
	$(PYTHON) tests/test_bailian_sdk_e2e_closure.py
	$(PYTHON) tests/test_bailian_small_kb_pilot_safety.py
	$(MAKE) bailian-retrieval-contract-check
	$(MAKE) bailian-retrieval-qa-dry-run
	$(MAKE) bailian-sdk-e2e-closure-check

retrieval-generation-check:
	$(PYTHON) tests/test_retrieval_generation_pipeline.py

grounded-section-check:
	$(PYTHON) tests/test_grounded_section_validation.py

phase7-pilot-dry-run:
	$(PYTHON) tests/test_retrieval_generation_pipeline.py
	$(PYTHON) tests/test_grounded_section_validation.py
	$(PYTHON) scripts/demo/run_retrieval_generation_pilot.py \
		--retrieval-mode offline_fixture \
		--generation-provider offline \
		--output-root /tmp/review_writer_phase7_offline \
		--strict

phase7-real-preflight:
	$(BAILIAN_SDK_PYTHON) tests/test_provider_adapters.py
	$(BAILIAN_SDK_PYTHON) tests/test_phase7_real_budget.py
	$(BAILIAN_SDK_PYTHON) tests/test_retrieval_generation_pipeline.py
	$(BAILIAN_SDK_PYTHON) tests/test_grounded_section_validation.py
	$(BAILIAN_SDK_PYTHON) scripts/demo/phase7_real_preflight.py \
		--fixture tests/fixtures/retrieval_generation/clean_3paper_retrieval_fixture.json \
		--output-json /tmp/review_writer_phase7_real_preflight.json \
		--output-md /tmp/review_writer_phase7_real_preflight.md

phase8-preflight:
	$(PHASE8_PYTHON) tests/test_phase8_evidence_package.py preflight

phase8-source-inventory-check:
	$(PHASE8_PYTHON) tests/test_phase8_evidence_package.py source_inventory

phase8-extraction-check:
	$(PHASE8_PYTHON) tests/test_phase8_evidence_package.py extraction

phase8-review-package-check:
	$(PHASE8_PYTHON) tests/test_phase8_evidence_package.py review_package

phase8-dashboard-check:
	$(PHASE8_PYTHON) tests/test_phase8_evidence_package.py dashboard

phase8-decision-writer-check:
	$(PHASE8_PYTHON) tests/test_phase8_evidence_package.py decision_writer

phase8-ai-adjudication-check:
	$(PYTHON) tests/test_phase8_ai_adjudication.py
	$(PYTHON) scripts/phase8/coordinate_ai_adjudication.py --help >/dev/null

phase8-v2-semantic-input-check:
	$(PYTHON) tests/test_phase8_v2_semantic_inputs.py
	$(PYTHON) scripts/phase8/prepare_v2_semantic_review.py --help >/dev/null

phase8-v3-source-first-check:
	$(PYTHON) tests/test_phase8_v3_source_first.py
	$(PYTHON) scripts/phase8/prepare_v3_source_first.py --help >/dev/null

phase8-v3-1-source-first-check:
	$(PYTHON) tests/test_phase8_v3_1_contract.py
	$(PYTHON) scripts/phase8/prepare_v3_1_source_first.py --help >/dev/null
	$(PYTHON) scripts/phase8/evaluate_v3_1_calibration.py --help >/dev/null

phase8-v3-1-1-source-first-check:
	$(PYTHON) scripts/phase8/prepare_v3_1_1_source_first.py --help >/dev/null

phase8-v3-1-1-layer-b-check:
	$(PYTHON) tests/test_phase8_v3_1_1_layer_b.py
	$(PYTHON) scripts/phase8/prepare_v3_1_1_layer_b.py --help >/dev/null

phase8-v3-1-1-reconciliation-check:
	$(PYTHON) tests/test_phase8_v3_1_1_reconciliation.py
	$(PYTHON) scripts/phase8/prepare_v3_1_1_final_reconciliation.py --help >/dev/null

phase8-v3-1-1-closure-check:
	$(PYTHON) tests/test_phase8_v3_1_1_closure.py
	$(PYTHON) scripts/phase8/close_v3_1_1_phase8a.py --help >/dev/null

phase8b-grounded-vertical-slice-check:
	$(PYTHON) tests/test_phase8b_grounded_vertical_slice.py
	$(PYTHON) scripts/phase8/prepare_phase8b_grounded_vertical_slice.py --help >/dev/null

phase8b-grounded-vertical-slice-v2-check:
	$(PYTHON) tests/test_phase8b_grounded_vertical_slice_v2.py
	$(PYTHON) scripts/phase8/prepare_phase8b_grounded_vertical_slice_v2.py --help >/dev/null

phase8b-salvage-check:
	$(PYTHON) tests/test_phase8b_salvage.py
	$(PYTHON) scripts/phase8/salvage_phase8b_grounded_vertical_slice_v2.py --help >/dev/null

bailian-transport-matrix-dry-run:
	$(PYTHON) tests/test_bailian_transport_matrix_safety.py
	$(PYTHON) scripts/rag/bailian_transport_matrix.py \
		--endpoint bailian.cn-beijing.aliyuncs.com \
		--category-id default \
		--output-json /tmp/bailian_transport_matrix_dry.json \
		--output-md /tmp/bailian_transport_matrix_dry.md \
		--strict

bailian-transport-matrix-real-command:
	@printf '%s\n' 'zsh -ic '\''cd $(REPO_ROOT) && conda run -n review-writer-bailian python scripts/rag/bailian_transport_matrix.py --endpoint bailian.cn-beijing.aliyuncs.com --category-id default --output-json /tmp/bailian_transport_matrix_real.json --output-md /tmp/bailian_transport_matrix_real.md --allow-network --use-official-sdk --strict'\'' >/dev/null && printf '\''bailian transport matrix wrote /tmp/bailian_transport_matrix_real.{json,md}\n'\'''

bailian-category-introspection:
	$(PYTHON) tests/test_bailian_category_introspection.py
	$(PYTHON) scripts/rag/bailian_category_introspection.py \
		--output-json /tmp/bailian_category_introspection.json \
		--output-md /tmp/bailian_category_introspection.md \
		--strict

bailian-category-discovery-dry-run:
	$(PYTHON) tests/test_bailian_category_discovery_safety.py
	$(PYTHON) scripts/rag/bailian_category_discovery.py \
		--endpoint bailian.cn-beijing.aliyuncs.com \
		--transport-mode no_proxy \
		--output-json /tmp/bailian_category_discovery_dry.json \
		--output-md /tmp/bailian_category_discovery_dry.md \
		--strict

bailian-category-discovery-real-command:
	@printf '%s\n' 'zsh -ic '\''cd $(REPO_ROOT) && conda run -n review-writer-bailian python scripts/rag/bailian_category_discovery.py --endpoint bailian.cn-beijing.aliyuncs.com --transport-mode no_proxy --output-json /tmp/bailian_category_discovery_real.json --output-md /tmp/bailian_category_discovery_real.md --allow-network --use-official-sdk --strict'\'' >/dev/null && printf '\''bailian category discovery wrote /tmp/bailian_category_discovery_real.{json,md}\n'\'''

bailian-category-lease-reprobe-real-command:
	@printf '%s\n' 'zsh -ic '\''cd $(REPO_ROOT) && conda run -n review-writer-bailian python scripts/rag/bailian_minimal_lease_repro.py --endpoint bailian.cn-beijing.aliyuncs.com --transport-mode no_proxy --category-id-from /tmp/bailian_category_discovery_real.json --output-json /tmp/bailian_minimal_lease_repro_category_real.json --output-md /tmp/bailian_minimal_lease_repro_category_real.md --allow-network --strict'\'' >/dev/null && printf '\''bailian category lease reprobe wrote /tmp/bailian_minimal_lease_repro_category_real.{json,md}\n'\'''

bailian-category-type-matrix-dry-run:
	$(PYTHON) tests/test_bailian_category_type_matrix_safety.py
	$(PYTHON) scripts/rag/bailian_category_type_matrix.py \
		--endpoint bailian.cn-beijing.aliyuncs.com \
		--transport-mode no_proxy \
		--output-json /tmp/bailian_category_type_matrix_dry.json \
		--output-md /tmp/bailian_category_type_matrix_dry.md \
		--strict

bailian-category-type-matrix-real-command:
	@printf '%s\n' 'zsh -ic '\''cd $(REPO_ROOT) && conda run -n review-writer-bailian python scripts/rag/bailian_category_type_matrix.py --endpoint bailian.cn-beijing.aliyuncs.com --transport-mode no_proxy --output-json /tmp/bailian_category_type_matrix_real.json --output-md /tmp/bailian_category_type_matrix_real.md --allow-network --use-official-sdk --strict'\'' >/dev/null && printf '\''bailian category type matrix wrote /tmp/bailian_category_type_matrix_real.{json,md}\n'\'''

bailian-sdk-env-check:
	$(PYTHON) tests/test_bailian_sdk_env_check.py
	$(PYTHON) scripts/rag/check_bailian_sdk_env.py \
		--output-json /tmp/bailian_sdk_env_check.json \
		--output-md /tmp/bailian_sdk_env_check.md

bailian-sdk-env-strict-check:
	$(PYTHON) scripts/rag/check_bailian_sdk_env.py \
		--output-json /tmp/bailian_sdk_env_check_strict.json \
		--output-md /tmp/bailian_sdk_env_check_strict.md \
		--strict

offline-ci-workflow-check:
	$(PYTHON) scripts/check_offline_ci_workflow.py

release-readiness-check:
	$(MAKE) smoke
	$(MAKE) quality-check
	$(MAKE) qoderwork-check
	$(MAKE) provider-check
	$(MAKE) qwen-hello-dry-run
	$(MAKE) judge-check
	$(MAKE) tiny-e2e-check
	$(MAKE) real-lite-preflight
	$(MAKE) real-lite-e2e-check
	$(MAKE) dashboard-real-lite-check
	$(MAKE) eval-baseline-check
	$(MAKE) portability-check
	$(MAKE) phase8-ai-adjudication-check
	$(MAKE) phase8-v3-source-first-check
	$(MAKE) phase8-v3-1-source-first-check
	$(MAKE) phase8-v3-1-1-source-first-check
	$(MAKE) phase8-v3-1-1-layer-b-check
	$(MAKE) phase8-v3-1-1-reconciliation-check
	$(MAKE) phase8-v3-1-1-closure-check
	$(MAKE) phase8b-grounded-vertical-slice-check
	$(MAKE) phase8b-grounded-vertical-slice-v2-check
	$(MAKE) phase8b-salvage-check

.PHONY: agent-orchestration-check provider-qualification-check
agent-orchestration-check:
	$(PYTHON) tests/test_agent_orchestration.py
	$(PYTHON) -m compileall -q scripts/agent-orchestration
	$(PYTHON) scripts/agent-orchestration/validate_task_package.py docs/agent-tasks/ORCH-001
	$(PYTHON) scripts/agent-orchestration/validate_policy.py
	$(PYTHON) scripts/agent-orchestration/check_orchestration.py --task-directory docs/agent-tasks/ORCH-001

provider-qualification-check:
	$(PYTHON) tests/test_provider_qualification.py
	$(PYTHON) -m compileall -q scripts/provider-qualification
	$(PYTHON) scripts/provider-qualification/qualification.py --help >/dev/null
