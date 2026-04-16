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
DEV_COMPOSE_FILE := $(HARNESS_ROOT)/env/docker-compose.dev.yml

# Auto-detect docker compose v2 (plugin) vs v1 (standalone).
COMPOSE := $(shell docker compose version >/dev/null 2>&1 \
             && echo "docker compose" \
             || echo "docker-compose")

# When HARNESS_DEV=1, overlay the dev compose file so cli/ is bind-mounted
# over /opt/harness-cli — CLI edits take effect immediately, no image rebuild.
ifeq ($(HARNESS_DEV),1)
  COMPOSE_FILES := -f $(COMPOSE_FILE) -f $(DEV_COMPOSE_FILE)
else
  COMPOSE_FILES := -f $(COMPOSE_FILE)
endif

IMAGE := harness-dev

# Host UID/GID baked into the image so the non-root container user
# matches the caller, keeping bind-mounted files editable on the host.
HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)

.PHONY: help \
        bootstrap reindex report \
        image image-force \
        deps build test lint run \
        shell shell-root up down reset \
        ctx-validate policy-check \
        ci init-check ensure-up ensure-image

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
	@echo "    image          Build the dev image (only if missing)"
	@echo "    image-force    Rebuild the dev image unconditionally (use after CLI changes)"
	@echo "    shell          Open a shell inside the dev container (as non-root)"
	@echo "    shell-root     Open a shell as root (for apt-get etc.)"
	@echo "    up             Start the dev container (persistent)"
	@echo "    down           Stop all containers"
	@echo "    reset          Stop containers and wipe volumes"
	@echo ""
	@echo "  CI (one-shot):"
	@echo "    ci             up → deps → build → test → lint → report → down"
	@echo ""
	@echo "  Dev iteration on the CLI itself:"
	@echo "    HARNESS_DEV=1 make up    Bind-mount cli/ over /opt/harness-cli"
	@echo "                             so CLI edits take effect live."
	@echo ""
	@echo "  Validation:"
	@echo "    ctx-validate   Check context/ frontmatter and index freshness"
	@echo "    policy-check   Verify staged changes against agent/policies.yaml"

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

bootstrap: init-check
	harness bootstrap
	@echo ""
	@echo "Note: run 'make image-force' to rebuild the dev image if Dockerfile changed."

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

# Build the dev image only if it doesn't exist yet.
image: ensure-image

# Always rebuild the dev image. Use after changing cli/, the Dockerfile, or
# runtime_blocks in harness.yml. The HOST_UID/HOST_GID build args make the
# in-container "harness" user match the caller, so bind-mounted files stay
# editable on the host without chown dances.
image-force:
	docker build \
	  --build-arg HOST_UID=$(HOST_UID) \
	  --build-arg HOST_GID=$(HOST_GID) \
	  -f $(HARNESS_ROOT)/env/Dockerfile \
	  -t $(IMAGE) $(HARNESS_ROOT)

# Build the image only if it isn't present locally.
ensure-image:
	@docker image inspect $(IMAGE) >/dev/null 2>&1 \
	  || $(MAKE) -f $(HARNESS_ROOT)/env/Makefile image-force

up: init-check ensure-image
	$(COMPOSE) $(COMPOSE_FILES) up -d dev

down:
	$(COMPOSE) $(COMPOSE_FILES) down

reset:
	$(COMPOSE) $(COMPOSE_FILES) down -v

# Auto-start the dev container if it isn't running.
ensure-up: ensure-image
	@$(COMPOSE) $(COMPOSE_FILES) ps --services --filter "status=running" 2>/dev/null \
	  | grep -q '^dev$$' \
	  || $(COMPOSE) $(COMPOSE_FILES) up -d dev

# ---------------------------------------------------------------------------
# Project work — all exec into the persistent dev container.
# ---------------------------------------------------------------------------

deps: init-check ensure-up
	$(COMPOSE) $(COMPOSE_FILES) exec -T -w /work dev harness exec deps

build: init-check ensure-up
	$(COMPOSE) $(COMPOSE_FILES) exec -T -w /work dev harness exec build

test: init-check ensure-up
	$(COMPOSE) $(COMPOSE_FILES) exec -T -w /work dev harness exec test

lint: init-check ensure-up
	$(COMPOSE) $(COMPOSE_FILES) exec -T -w /work dev harness exec lint

run: init-check ensure-up
	$(COMPOSE) $(COMPOSE_FILES) exec -T -w /work dev harness exec run

shell: ensure-up
	$(COMPOSE) $(COMPOSE_FILES) exec -w /work dev bash

# Escape hatch for operations that require root (apt-get install, chown
# adjustments, etc.). Prefer plain `make shell` + `sudo <cmd>` for one-offs.
shell-root: ensure-up
	$(COMPOSE) $(COMPOSE_FILES) exec --user root -w /work dev bash

# ---------------------------------------------------------------------------
# CI — single entry point for automation.
# Brings up the stack, runs everything, tears it down regardless of outcome.
# ---------------------------------------------------------------------------

ci: init-check
	$(COMPOSE) $(COMPOSE_FILES) up -d dev
	$(COMPOSE) $(COMPOSE_FILES) exec -T -w /work dev \
	  bash -lc "harness exec deps && harness exec build && harness exec test && harness exec lint" ; \
	STATUS=$$? ; \
	harness report || true ; \
	$(COMPOSE) $(COMPOSE_FILES) down ; \
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
	@if [ "$(HARNESS_DEV)" = "1" ]; then \
		exit 0; \
	fi; \
	if [ ! -f "$(HARNESS_ROOT)/harness.yml" ]; then \
		echo ""; \
		echo "harness.yml not found — this harness is uninitialized."; \
		echo "Open the repo in Claude Code (or another agent) and run the"; \
		echo "'initialization' skill (skills/initialization.md)."; \
		echo ""; \
		exit 1; \
	fi
