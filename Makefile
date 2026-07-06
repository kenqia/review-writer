.PHONY: smoke quality-check

PYTHON ?= python3

smoke:
	$(PYTHON) -m py_compile $$(find skills view scripts -name '*.py' -type f)
	$(PYTHON) skills/review-writing-orchestrator/scripts/project_status.py --help >/dev/null
	$(PYTHON) skills/review-final-audit-release/scripts/final_audit_scan.py --help >/dev/null

quality-check:
	$(PYTHON) scripts/repo_safety_check.py
