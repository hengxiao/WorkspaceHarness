# Workspace Harness — standardized make contract.
#
# Every harness exposes the same targets regardless of what the wrapped
# project actually uses (cargo, pnpm, pytest, bazel, ...). Targets here
# delegate to the `harness` CLI, which reads `harness.yml` and dispatches
# to the right per-project commands inside the dev container.
#
# This Makefile is INTENTIONALLY static: it does not need to be regenerated
# by `make bootstrap`. The CLI handles state and per-project differences.

# Run targets from the harness repo root:
#     make -f env/Makefile <target>
# or symlink env/Makefile to ./Makefile after init.

HARNESS_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)

.PHONY: help \
        bootstrap reindex report \
        build test lint run \
        shell up down reset \
        ctx-validate policy-check \
        init-check

help:
	@echo "Workspace Harness — targets"
	@echo ""
	@echo "  Lifecycle:"
	@echo "    bootstrap      Regenerate env/ files (Dockerfile, compose) from harness.yml"
	@echo "    reindex        Rebuild context/index.json"
	@echo "    report         Aggregate .harness/reports/ into report.md"
	@echo ""
	@echo "  Project work (runs inside the dev container):"
	@echo "    build          Build wrapped project artifacts"
	@echo "    test           Run the full test suite (emits .harness/reports/test/)"
	@echo "    lint           Run linters (emits .harness/reports/lint/)"
	@echo "    run            Start the wrapped service for manual testing"
	@echo ""
	@echo "  Environment:"
	@echo "    shell          Open a shell inside the dev container"
	@echo "    up             Bring up the service stack"
	@echo "    down           Stop the service stack"
	@echo "    reset          Stop the stack and wipe its volumes"
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
# Project work — all run inside the dev container.
# ---------------------------------------------------------------------------

build: init-check
	docker compose -f env/docker-compose.yml run --rm dev harness exec build

test: init-check
	docker compose -f env/docker-compose.yml run --rm dev harness exec test

lint: init-check
	docker compose -f env/docker-compose.yml run --rm dev harness exec lint

run: init-check
	docker compose -f env/docker-compose.yml run --rm --service-ports dev harness exec run

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

shell: init-check
	docker compose -f env/docker-compose.yml run --rm dev bash

up: init-check
	docker compose -f env/docker-compose.yml up -d

down:
	docker compose -f env/docker-compose.yml down

reset:
	docker compose -f env/docker-compose.yml down -v

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

ctx-validate:
	harness ctx validate

policy-check:
	harness policy check --staged

# ---------------------------------------------------------------------------
# Internal — guards against running project targets on an uninitialized harness.
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
