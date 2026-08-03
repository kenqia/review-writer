PYTHON ?= python3
PROJECT_ROOT ?= projects
REQUEST ?=
PROJECT ?=
MINERU_OUTPUT ?=
MANIFEST ?=
ACTOR_LABEL ?= 肯恰大人

.PHONY: help cli start dashboard bootstrap bind preflight import

help:
	@echo "review-writer v0.1 用户入口"
	@echo "  make cli       查看离线命令"
	@echo "  make bootstrap REQUEST=inputs/<request>.json"
	@echo "  make bind PROJECT=projects/<id> MINERU_OUTPUT=<path>"
	@echo "  make preflight PROJECT=projects/<id> MANIFEST=inputs/<manifest>.json"
	@echo "  make import PROJECT=projects/<id> MANIFEST=inputs/<manifest>.json"
	@echo "  make start     打开本地工作台"

cli:
	$(PYTHON) scripts/run_vertical_review.py --help

start: dashboard

dashboard:
	$(PYTHON) view/serve_review_dashboard.py --review-root "$(PROJECT_ROOT)" --host 127.0.0.1 --port 8765

bootstrap:
	@test -n "$(REQUEST)" || (echo "请提供 REQUEST=inputs/<request>.json"; exit 2)
	$(PYTHON) scripts/run_vertical_review.py bootstrap-corpus --review-root "$(PROJECT_ROOT)" --request "$(REQUEST)"

bind:
	@test -n "$(PROJECT)" || (echo "请提供 PROJECT=projects/<project_id>"; exit 2)
	@test -n "$(MINERU_OUTPUT)" || (echo "请提供 MINERU_OUTPUT=<Generic Parse 输出目录>"; exit 2)
	$(PYTHON) scripts/run_vertical_review.py bind-generic-parse --project "$(PROJECT)" --mineru-output "$(MINERU_OUTPUT)"

preflight:
	@test -n "$(PROJECT)" || (echo "请提供 PROJECT=projects/<project_id>"; exit 2)
	@test -n "$(MANIFEST)" || (echo "请提供 MANIFEST=inputs/<manifest>.json"; exit 2)
	$(PYTHON) scripts/run_vertical_review.py preflight-corpus-inputs --project "$(PROJECT)" --manifest "$(MANIFEST)"

import:
	@test -n "$(PROJECT)" || (echo "请提供 PROJECT=projects/<project_id>"; exit 2)
	@test -n "$(MANIFEST)" || (echo "请提供 MANIFEST=inputs/<manifest>.json"; exit 2)
	$(PYTHON) scripts/run_vertical_review.py import-corpus-inputs --project "$(PROJECT)" --manifest "$(MANIFEST)" --actor-type human_researcher --actor-label "$(ACTOR_LABEL)"
