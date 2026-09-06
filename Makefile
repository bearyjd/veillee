# Veillée. `make verify` passing is the definition of done.
.DEFAULT_GOAL := help
SHELL := /bin/bash
UV ?= uv
VEILLEE_IMAGE ?= ghcr.io/<owner>/veillee:latest
RUN := $(UV) run

# Docker if present, podman otherwise. Both speak the Compose spec.
COMPOSE := $(shell if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; \
	then echo "docker compose"; else echo "podman compose"; fi)

.PHONY: help install lint fmt typecheck test e2e verify verify-fast smoke \
        morning-check backup reindex export run worker clean browsers up down logs relocate publish

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies and the Chromium browser
	$(UV) sync --all-groups
	$(RUN) playwright install chromium

browsers: ## Install the Playwright browser only
	$(RUN) playwright install chromium

lint: ## ruff + mypy
	$(RUN) ruff check src tests
	$(RUN) ruff format --check src tests
	$(RUN) mypy

fmt: ## Reformat and autofix
	$(RUN) ruff format src tests
	$(RUN) ruff check --fix src tests

test: ## Unit and integration tests
	$(RUN) pytest tests -m "not e2e" -q

e2e: ## Browser tests, including crash recovery and MediaRecorder
	$(RUN) pytest tests/e2e -q

verify: lint test e2e smoke ## Everything. This passing is the definition of done.
	@echo ""
	@echo "  ✓ verify passed — lint, tests, browser, and the full container stack."

verify-fast: lint test e2e ## Everything except the container smoke test
	@echo "  ✓ verify-fast passed (container smoke test skipped)."

smoke: ## Full-stack smoke test against real containers, from an empty data dir
	./scripts/smoke.sh

morning-check: ## 30 seconds: is it working right now?
	./scripts/morning-check.sh

publish: ## Build and push the image to ghcr.io (needs a registry login)
	$(COMPOSE) build
	podman tag veillee:latest $(VEILLEE_IMAGE)
	podman push $(VEILLEE_IMAGE)
	@echo "pushed $(VEILLEE_IMAGE)"

relocate: ## Package everything for a move to another machine
	./scripts/relocate.sh

backup: ## Back up the index and the archive
	./scripts/backup.sh

reindex: ## Rebuild the SQLite index from data/ alone
	$(RUN) veillee reindex

export: ## Write a dated export folder
	$(RUN) veillee export

up: ## Build and start the containers (docker or podman, whichever is here)
	./scripts/up.sh

down: ## Stop the containers
	./scripts/down.sh

logs: ## Follow the container logs
	$(COMPOSE) logs -f --tail 100

run: ## Development server on 127.0.0.1:8000
	$(RUN) veillee serve --reload

worker: ## Transcription worker in the foreground
	$(RUN) veillee worker

clean: ## Remove caches and the rebuildable index
	rm -rf .pytest_cache .mypy_cache .ruff_cache test-results
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -f veillee.db veillee.db-wal veillee.db-shm
