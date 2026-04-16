# Workspace Harness — standardized make contract.
#
# Every harness exposes the same targets regardless of what the wrapped
# project actually uses. Targets delegate to the `harness` CLI inside the
# dev container. The container persists between targets (via `up`) so
# installed dependencies are not lost between `make deps` and `make test`.
#
# This Makefile is INTENTIONALLY static: it does not need to be regenerated
# by `make bootstrap`. The CLI handles state and per-project differences.

HARNESS_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
COMPOSE_FILE := $(HARNESS_ROOT)/env/docker-compose.yml

# Auto-detect docker compose v2 (plugin) vs v1 (standalone).
COMPOSE := $(shell docker compose version >/dev/null 2>&1 \
             && echo "docker compose" \
             || echo "docker-compose")

.PHONY: help \
        bootstrap reindex report \
        deps build test lint run \
        shell up down reset \
        ctx-validate policy-check \
        ci init-check ensure-up

help:
	@echo "Workspace Harness — targets"
	@echo ""
	@echo "  Lifecycle:"
	@echo "    bootstrap      Regenerate env/ files (Dockerfile, compose) from harness.yml"
	@echo "    reindex        Rebuild context/index.json"
	@echo "    report         Aggregate .harness/reports/ into report.md"
	@echo ""
	@echo "  Project work (runs inside the persistent dev container):"
	@echo "    deps           Install project dependencies"
	@echo "    build          Build wrapped project artifacts"
	@echo "    test           Run the full test suite (emits .harness/reports/test/)"
	@echo "    lint           Run linters (emits .harness/reports/lint/)"
	@echo "    run            Start the wrapped service for manual testing"
	@echo ""
	@echo "  Environment:"
	@echo "    shell          Open a shell inside the dev container"
	@echo "    up             Start the dev container (persistent)"
	@echo "    down           Stop all containers"
	@echo "    reset          Stop containers and wipe volumes"
	@echo ""
	@echo "  CI (one-shot):"
	@echo "    ci             up → deps → build → test → lint → report → down"
	@echo ""
	@echo "  Validation:"
	@echo "    ctx-validate   Check context/ frontmatter and index freshness"
	@echo "    policy-check   Verify staged changes against agent/policies.yaml"

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

bootstrap: init-check
	harness bootstrap

reindex: init-check
	harness ctx reindex

report:
	harness report

# ---------------------------------------------------------------------------
# Environment — persistent dev container.
#
# `make up` starts the dev service in the background. All work targets use
# `exec` into the running container so installed deps, caches, and state
# survive across targets. `make down` tears it down.
# ---------------------------------------------------------------------------

up: init-check
	$(COMPOSE) -f $(COMPOSE_FILE) up -d dev

down:
	$(COMPOSE) -f $(COMPOSE_FILE) down

reset:
	$(COMPOSE) -f $(COMPOSE_FILE) down -v

# Auto-start the dev container if it isn't running.
ensure-up:
	@$(COMPOSE) -f $(COMPOSE_FILE) ps --services --filter "status=running" 2>/dev/null \
	  | grep -q '^dev$$' \
	  || $(COMPOSE) -f $(COMPOSE_FILE) up -d dev

# ---------------------------------------------------------------------------
# Project work — all exec into the persistent dev container.
# ---------------------------------------------------------------------------

deps: init-check ensure-up
	$(COMPOSE) -f $(COMPOSE_FILE) exec -w /work dev harness exec deps

build: init-check ensure-up
	$(COMPOSE) -f $(COMPOSE_FILE) exec -w /work dev harness exec build

test: init-check ensure-up
	$(COMPOSE) -f $(COMPOSE_FILE) exec -w /work dev harness exec test

lint: init-check ensure-up
	$(COMPOSE) -f $(COMPOSE_FILE) exec -w /work dev harness exec lint

run: init-check ensure-up
	$(COMPOSE) -f $(COMPOSE_FILE) exec -w /work dev harness exec run

shell: ensure-up
	$(COMPOSE) -f $(COMPOSE_FILE) exec -w /work dev bash

# ---------------------------------------------------------------------------
# CI — single entry point for automation.
# Brings up the stack, runs everything, tears it down regardless of outcome.
# ---------------------------------------------------------------------------

ci: init-check
	$(COMPOSE) -f $(COMPOSE_FILE) up -d dev
	$(COMPOSE) -f $(COMPOSE_FILE) exec -w /work dev \
	  bash -lc "harness exec deps && harness exec build && harness exec test && harness exec lint" ; \
	STATUS=$$? ; \
	harness report || true ; \
	$(COMPOSE) -f $(COMPOSE_FILE) down ; \
	exit $$STATUS

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

ctx-validate:
	harness ctx validate

policy-check:
	harness policy check --staged

# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

init-check:
	@if [ ! -f "$(HARNESS_ROOT)/harness.yml" ]; then \
		echo ""; \
		echo "harness.yml not found — this harness is uninitialized."; \
		echo "Open the repo in Claude Code (or another agent) and run the"; \
		echo "'initialization' skill (skills/initialization.md)."; \
		echo ""; \
		exit 1; \
	fi
