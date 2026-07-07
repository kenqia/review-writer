.PHONY: smoke quality-check qoderwork-check provider-check qwen-hello-dry-run judge-check tiny-e2e-check real-lite-preflight real-lite-e2e-check

PYTHON ?= python3

smoke:
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
		--search-root /home/kenqia/my_folder \
		--repo-root /home/kenqia/my_folder/review-writer \
		--output-json /tmp/real_lite_asset_manifest.json \
		--output-md /tmp/real_lite_asset_manifest.md \
		--max-papers 5 \
		--strict
	$(PYTHON) tests/test_real_lite_manifest.py

real-lite-e2e-check:
	$(PYTHON) tests/test_real_lite_e2e_workflow.py
	$(PYTHON) scripts/demo/run_real_lite_e2e.py \
		--demo-root demo_projects/real_lite_allene_review \
		--output-root /tmp/review_writer_real_lite_e2e \
		--strict
