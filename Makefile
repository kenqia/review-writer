.PHONY: smoke quality-check qoderwork-check

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
