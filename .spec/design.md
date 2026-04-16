---
title: Workspace Harness — Design Spec
status: draft
version: 0.1
updated: 2026-04-15
---

# Workspace Harness — Design Spec

## 1. Purpose & Scope

The Workspace Harness wraps an arbitrary Git project with everything an AI coding agent (Claude Code, Cursor, Copilot, etc.) needs to operate productively and autonomously: searchable context, a reproducible environment, codified skills, and a CI loop with machine-readable feedback.

**In scope**

- A declarative way to plug in any Git repo (any language, any layout).
- A standardized contract that is the same across wrapped projects, so agents do not need bespoke knowledge per repo.
- Reproducible local + CI environments built from the same source of truth.
- A retrieval-friendly knowledge base.
- An autonomous loop: read context → write code → run tests → read CI report → iterate.

**Out of scope (for v1)**

- Hosting the agent itself (we orchestrate around existing agents, not replace them).
- Replacing the wrapped project's existing build system. The harness *invokes* it.
- Cross-repo refactors. One harness wraps one logical project (which may be a monorepo).

## 2. Design Principles

1. **Strict isolation from the wrapped project.** The harness never writes its own files (context, skills, agent config, env, CI, specs, generated artifacts) into a wrapped submodule. Only changes that the submodule itself owns — source code, its own tests, its own docs — may land there, and only as part of an explicit task targeting that submodule. This is the rule that makes the harness safe to plug into any third-party repo.
2. **One contract, many backends.** Agents always invoke `make test`, `make build`, `make shell`. The Makefile delegates to whatever the wrapped repo actually uses (cargo, pnpm, pytest, bazel...). Agents should never need language-specific knowledge to run the basics.
3. **Declarative over scripted.** A single `harness.yml` describes the wrapped project; generators produce the Dockerfile, compose file, and Makefile from it. Hand-edits are allowed but tracked. All generated files live in the harness repo, never in the submodule.
4. **Reproducible by construction.** Local dev and CI run the same container image with the same entrypoints. "Works on my machine" should not be reachable.
5. **Agent-first ergonomics.** Every output (test results, lint output, CI reports, context search) has a structured form (JSON, JUnit XML, frontmatter) in addition to a human-readable form.
6. **Idempotent and reversible.** `make` targets, reindex jobs, and bootstrap commands can be re-run safely. The harness never silently mutates the wrapped repo.
7. **Least-privilege automation.** Agent-driven actions are gated by an explicit policy file. No autonomous push to protected branches, no autonomous secret access.

## 3. High-Level Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                       Workspace Harness                       │
│                                                               │
│   ┌─────────────┐   ┌─────────────┐   ┌──────────────────┐    │
│   │  context/   │   │   skills/   │   │     agent/       │    │
│   │ (knowledge) │   │ (rules)     │   │ (hooks/policies) │    │
│   └──────┬──────┘   └──────┬──────┘   └────────┬─────────┘    │
│          │                 │                   │              │
│          └────────┬────────┴──────────┬────────┘              │
│                   │                   │                       │
│            ┌──────▼──────┐    ┌───────▼────────┐              │
│            │  harness.yml│    │  .github/wf/   │              │
│            │ (config)    │    │   (CI/CD)      │              │
│            └──────┬──────┘    └───────┬────────┘              │
│                   │                   │                       │
│            ┌──────▼───────────────────▼────────┐              │
│            │              env/                 │              │
│            │  Dockerfile / compose / Makefile  │              │
│            │  (generated from harness.yml)     │              │
│            └──────────────────┬────────────────┘              │
│                               │                               │
│                  ┌────────────▼─────────────┐                 │
│                  │   Wrapped Git project    │                 │
│                  │   (mounted, untouched)   │                 │
│                  └──────────────────────────┘                 │
└───────────────────────────────────────────────────────────────┘
```

The wrapped project is mounted into the dev container as a git submodule. The harness writes only to its own directories (`context/`, `skills/`, `agent/`, `env/`, `.spec/`, `.harness/`, `.github/`). It **never** writes to the submodule's tree as part of harness operations.

The only writes to the submodule come from agents working on tasks that target the submodule itself (a bug fix, a feature, the submodule's own docs). Those changes are committed to the submodule's own repository and proposed via PRs there — they are not commits in the harness repo.

## 4. Plug-in Model

The harness wraps a project by adding it as a **git submodule** under `projects/<name>/`. There is exactly one supported topology, because mixing harness files into third-party repos is explicitly disallowed (see Principle 1).

```
workspace-harness/
├── harness.yml
├── context/            # harness owns
├── skills/             # harness owns
├── agent/              # harness owns
├── env/                # harness owns
├── .spec/              # harness owns
├── .github/            # harness owns
└── projects/
    └── my-service/     # git submodule — harness READS, never WRITES
```

There are two distinct steps in the plug-in lifecycle:

**Initialization** — interactive, agent-driven (see `skills/initialization.md`). Runs once on an empty harness:

1. Ask the user what the harness is for and which Git projects to wrap.
2. `git submodule add` each project under `projects/<name>/` at the requested branch.
3. Read each submodule (read-only) to derive an overview into `context/upstream/<name>/`.
4. Ask the user about cross-project architecture, design docs, and gotchas.
5. Write `harness.yml` and `.harness/state.json`.

State after initialization is recorded in `.harness/state.json` (status, project list, refs at analysis time). Initialization is **resumable** — re-running picks up from the recorded `current_phase`.

**Bootstrap** — non-interactive (`make bootstrap`). Runs after initialization, and re-runs whenever `harness.yml` changes:

1. Read `harness.yml`.
2. Verify each declared submodule is present at the recorded ref; sync if not.
3. Generate `env/Dockerfile`, `env/docker-compose.yml`, `env/Makefile` from templates + config — into the harness tree.
4. Build the dev image.

Bootstrap is idempotent and one-directional: re-running it regenerates files inside the harness tree only. A `# HARNESS:KEEP` block is preserved in generated files for hand-edits.

### What may and may not be written to a submodule

| Path | May the harness write? |
| --- | --- |
| `projects/<name>/**` (any submodule file) | **No**, never, as a harness operation |
| `projects/<name>/src/**` etc. | **Yes**, only when an agent task explicitly targets that submodule's own work, and the change is committed to the submodule's repo |
| Anything outside `projects/` | Yes — this is the harness's own tree |

If the harness ever needs to "remember" something about a submodule (an ingestion manifest, a derived index, a per-project skill), that file lives in the harness tree under `context/upstream/<name>/`, `skills/projects/<name>/`, etc. — never in the submodule.

## 5. Configuration: `harness.yml`

The single source of truth.

```yaml
version: 1

harness:
  purpose: "Backend + iOS client for the AcmePay payments stack"
  initialized_at: "2026-04-15T10:00:00Z"

projects:                          # one or more wrapped submodules
  - name: my-service
    path: projects/my-service      # always under projects/, always a git submodule
    submodule:
      url: git@github.com:acme/my-service.git
      ref: main
    writable: true                 # may agents commit changes back to its repo?

    runtime:
      language: [python, typescript] # any common name; CLI normalizes internally
      python: { version: "3.12" }
      node:   { version: "20" }
    commands:                        # mapped to standard make targets
      deps:  "uv sync && pnpm install"         # install dependencies (persists in container)
      build: "uv run build && pnpm build"       # produce artifacts
      test:  "uv run pytest && pnpm test"
      lint:  "uv run ruff check && pnpm lint"
      run:   "uv run uvicorn app:main --reload"

env:
  base_image: "ubuntu:24.04"
  runtime_blocks:                # optional: override default install for a language
    node: |                      # example: pin a specific Node version
      RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
          apt-get install -y --no-install-recommends nodejs && \
          rm -rf /var/lib/apt/lists/*

services:                        # docker-compose service stack
  - name: postgres
    image: postgres:16
    ports: ["5432:5432"]
  - name: redis
    image: redis:7

context:
  ingest:                                   # READS submodule files; writes only to context/upstream/
    - source: "{project.path}/docs/**/*.md"
      into:   "context/upstream/{project.name}/docs/"
      tags:   [docs, upstream]
    - source: "{project.path}/CHANGELOG.md"
      into:   "context/upstream/{project.name}/CHANGELOG.md"
      tags:   [history, upstream]
  index:
    backend: sqlite-fts          # also: lance, qdrant
    embeddings: optional

agent:
  policy: agent/policies.md
  allow:
    - "make test"
    - "make lint"
    - "make build"
    - "git commit"
  deny:
    - "git push origin main"
    - "make deploy"
  require_human_for:
    - schema_migrations
    - dependency_upgrades_major
```

A JSON Schema for `harness.yml` lives at `.spec/schema/harness.schema.json` (TBD) and is validated in CI.

## 6. Component Designs

### 6.1 Context Library (`context/`)

**Goal:** any agent can find the right doc in <1s with a structured query.

**Document contract** — every file under `context/` carries frontmatter:

```yaml
---
title: Auth middleware design
tags: [auth, security, design]
summary: One-paragraph TL;DR for retrieval previews.
updated: 2026-04-10
source: internal                 # internal | upstream | generated
related: [bugs/AUTH-204.md]
---
```

**Index** (`context/index.json`) is regenerated by `make reindex`. Schema:

```json
{
  "version": 1,
  "generated_at": "2026-04-15T...",
  "documents": [
    {
      "path": "specs/design/auth.md",
      "title": "...",
      "tags": [...],
      "summary": "...",
      "updated": "...",
      "hash": "sha256:..."
    }
  ]
}
```

**Search interface** — a small CLI (`harness ctx search "<query>"`) backed by the chosen index backend. Default is SQLite FTS5 (zero-dep, fast enough for ~10k docs). Pluggable backends: Lance, Qdrant.

**Upstream vs. harness-native context.** Documents under `context/upstream/<name>/` are derived snapshots of submodule files — agents may read them but should treat the submodule's tree as the source of truth and never edit the snapshot directly. Documents elsewhere in `context/` are harness-native and freely editable. The reindex job re-derives `upstream/` from the submodule on every run.

**Lifecycle** — `skills/context-updates.md` codifies when agents must update context (after design changes, after postmortems, after ADRs). A pre-commit check warns when code changes touch a directory that has stale context (config-driven mapping). Because `upstream/` is derived, drift there is fixed by re-running `make reindex`, not by hand-editing.

### 6.2 Environment (`env/`)

**Container base:** `ubuntu:24.04`. Chosen for parity with `ubuntu-latest` GitHub runners and broad apt ecosystem. Configurable via `env.base_image:` in `harness.yml`.

**Image construction**

- `base` — OS + system packages installed from the apt block.
- `runtime` — language toolchains injected per project (Python/Node/Go/Rust blocks rendered from `runtime.language`).
- `dev` — adds the `harness` CLI (`pip install /opt/harness-cli` of the bind-copied `cli/` directory).

The `dev` image is what `make shell` enters and what CI uses. Same image, same behavior. The harness root is bind-mounted at `/work/`; the container has no other view of the host filesystem.

**Hooks** (`agent/hooks/*.sh`) are bash. They are thin orchestration glue that calls the `harness` CLI for any non-trivial work, so the language barrier is low.

**Service stack** — `docker-compose.yml` is generated from `services:`. A `make up` brings it up; `make down` tears it down. A `make reset` wipes volumes for a clean state.

**Makefile contract** — every harness exposes the same targets regardless of underlying tooling. The Makefile auto-detects `docker compose` (v2 plugin) vs `docker-compose` (v1 standalone).

**Persistent dev container.** Work targets (`deps`, `build`, `test`, `lint`, `run`, `shell`) use `exec` into a persistent container started by `make up`. This means installed dependencies survive across targets — `make deps` followed by `make test` works without re-installing. `make down` tears down the container.

| Target | Required | Notes |
| --- | --- | --- |
| `deps` | yes | Install project dependencies (npm install, pip install, cargo fetch, ...) |
| `build` | yes | Build artifacts inside the dev container |
| `test` | yes | Run the full suite; emits JUnit XML to `.harness/reports/test/` |
| `lint` | yes | Run linters; emits SARIF to `.harness/reports/lint/` |
| `shell` | yes | Open a shell inside the persistent dev container |
| `up` / `down` / `reset` | yes | Service stack lifecycle (persistent container) |
| `run` | optional | Start the wrapped service for manual testing |
| `bootstrap` | yes | Regenerate env files from `harness.yml` |
| `reindex` | yes | Rebuild `context/index.json` |
| `report` | yes | Aggregate `.harness/reports/` into a single Markdown summary |
| `ci` | yes | One-shot: up → deps → build → test → lint → report → down |

Reports under `.harness/reports/` are the canonical artifacts CI uploads — same format locally and in CI, so agents can train on one shape.

**Language normalization.** Users declare languages in `harness.yml` using any common name (`javascript`, `js`, `typescript`, `ts`, `python`, `py`, `golang`, `go`, `rust`, `rs`). The CLI normalizes them to canonical runtime names (`node`, `python`, `go`, `rust`) so templates and downstream code work consistently.

**Data-driven runtime blocks.** The Dockerfile template renders install instructions from a `runtime_blocks` dict (keyed by canonical language). Defaults are built into the CLI for common languages. Users can override or add new ones via `env.runtime_blocks:` in `harness.yml` — no template editing needed.

### 6.3 Skills (`skills/`)

A curated set of short, action-oriented guides. Each file has frontmatter:

```yaml
---
name: deployment
applies_to: [deploy, release]
audience: [agent, human]
---
```

Standard set:

- `CLAUDE.md` / `AGENTS.md` — entry points loaded automatically by their respective agents. Keep <200 lines; link out to specific skills. Routes to `initialization.md` when the harness is uninitialized.
- `initialization.md` — first-run skill that converts an empty harness into a populated one (submodules pulled, context seeded, `harness.yml` and `.harness/state.json` written). Also re-entered when adding a new submodule later.
- `coding-style.md` — file structure, naming, comment policy.
- `documentation.md` — what to document, where it goes in `context/`.
- `deployment.md` — release flow, rollbacks.
- `debugging.md` — common failure modes + dashboards.
- `context-updates.md` — when and how to refresh `context/`.
- `testing.md` — how to write/run tests, what coverage thresholds apply.

Per-project overrides live under `skills/projects/<name>/`. They extend (not replace) the harness-wide skills.

Skills are *prescriptive*, not descriptive. They tell agents what to do, not how the system works (that lives in `context/`).

### 6.4 Agent Integration (`agent/`)

```
agent/
  policies.md       # human-readable policy
  policies.yaml     # machine-readable mirror, enforced by hooks
  hooks/
    pre-task.sh     # runs before agent starts a task
    post-task.sh    # runs after; collects diffs, lint, test results
    pre-commit.sh   # validates change against policy before commit
  prompts/
    triage.md       # bug triage prompt
    fix.md          # bug-fix prompt
    feature.md      # feature implementation prompt
  outputs/          # per-task scratch dir; gitignored
```

**Policy enforcement** — `pre-commit.sh` reads `agent/policies.yaml` and rejects commits that touch protected paths or violate `deny:` rules from `harness.yml`. This is the safety net even when the agent is misconfigured.

**Task lifecycle**

1. Task created (issue, prompt, or scheduled trigger).
2. `pre-task.sh` snapshots state, prepares a worktree.
3. Agent runs; constrained to `allow:` commands.
4. `post-task.sh` runs `make test lint report`, captures `.harness/reports/`, summarizes diffs.
5. PR opened with the report linked in the body.

### 6.5 CI/CD (`.github/workflows/`)

**Workflows**

- `ci.yml` — on push/PR: `make build test lint report`. Uploads `.harness/reports/` as artifacts. Posts the aggregated `report.md` as a sticky PR comment.
- `context.yml` — on push that touches `context/`: validates frontmatter, rebuilds index, fails if drift detected.
- `agent-loop.yml` — scheduled or `workflow_dispatch`: runs an agent against issues labeled `agent-ready`. Opens PRs as a bot user. Disabled by default.

**Reports**

- `.harness/reports/report.md` — the single Markdown digest agents (and humans) read.
- `.harness/reports/test/junit.xml` — machine-readable test results.
- `.harness/reports/lint/results.sarif` — code scanning UI surfaces this in GitHub.
- Job summary (`$GITHUB_STEP_SUMMARY`) embeds `report.md` so it is viewable without downloading artifacts.
- Optional `gh-pages` publish for browsable history.

CI runs the same dev image as local. No "CI-only" steps.

## 7. The Autonomous Loop

End-to-end flow when an agent is given a bug:

1. Agent reads `skills/CLAUDE.md`, then `skills/debugging.md`.
2. Agent queries `harness ctx search "<symptom>"` and pulls the top 3–5 docs.
3. Agent enters the dev container (`make shell`).
4. Agent reproduces the bug, writes a failing test, fixes it.
5. Agent runs `make test lint report`.
6. If green, agent commits (filtered through `pre-commit.sh`) and opens a PR.
7. CI runs the same targets and posts `report.md`.
8. On red, the agent reads `report.md` (structured + Markdown), iterates.
9. Human reviews, merges. Agent updates `context/` if the fix revealed missing knowledge.

The loop is the same for features and refactors; only the entry prompt changes.

## 8. The `harness` CLI

Implementation: **Python 3.11+**, packaged in `cli/` and installed into the dev image via `pip install /opt/harness-cli`. Built on Click + Jinja2 + PyYAML + Rich. Source layout:

```
cli/
  pyproject.toml
  src/harness/
    cli.py           # Click root + command groups
    config.py        # load harness.yml + .harness/state.json
    bootstrap.py     # render templates → env/
    ctx.py           # context library
    policy.py        # policy enforcement
    exec_.py         # harness exec ...
    report.py        # report aggregation
    status.py        # harness status
    templates/
      Dockerfile.j2
      docker-compose.yml.j2
```

Subcommands:

```
harness bootstrap          # regenerate env/Dockerfile + docker-compose.yml from harness.yml
harness ctx search QUERY   # search the context library                   (M2 stub)
harness ctx add PATH       # add a doc with frontmatter scaffolding       (working)
harness ctx validate       # check frontmatter + index freshness          (working)
harness ctx reindex        # rebuild context/index.json                   (M2 stub)
harness exec TARGET        # run per-project build/test/lint/run          (working)
harness policy check CMD   # is this command allowed by policy?           (working)
harness policy check --staged   # check staged paths                      (working)
harness report             # aggregate .harness/reports/ → report.md      (M4 stub)
harness status             # print harness state                          (working)
```

Generated files use `# HARNESS:KEEP:BEGIN <name>` / `# HARNESS:KEEP:END <name>` markers so hand-edits inside those blocks survive `harness bootstrap`.

Subcommands map 1:1 to the user-facing make targets, so agents can use either surface.

## 9. Repository Layout (target state)

```
.
├── README.md
├── harness.yml
├── .gitmodules                # tracks wrapped projects
├── .spec/                     # design specs (this doc lives here)
│   ├── design.md
│   └── schema/
├── context/
│   ├── index.json
│   ├── docs/                  # harness-native
│   ├── internal/              # harness-native
│   ├── specs/                 # harness-native
│   ├── bugs/                  # harness-native
│   └── upstream/              # DERIVED from submodules; do not hand-edit
│       └── <project>/
├── skills/
│   ├── CLAUDE.md
│   ├── AGENTS.md
│   ├── projects/<project>/    # per-project skill overrides (harness-owned)
│   └── ...
├── agent/
│   ├── policies.md
│   ├── policies.yaml
│   ├── hooks/
│   └── prompts/
├── cli/                       # the `harness` CLI (Python)
│   ├── pyproject.toml
│   └── src/harness/
├── env/
│   ├── Dockerfile             # generated by `harness bootstrap` (fallback shipped)
│   ├── docker-compose.yml     # generated by `harness bootstrap` (fallback shipped)
│   ├── Makefile               # static contract
│   └── scripts/
├── .harness/                  # generated; gitignored except reports schema
│   └── reports/
├── .github/workflows/
│   ├── ci.yml
│   ├── context.yml
│   └── agent-loop.yml
└── projects/                  # WRAPPED PROJECTS — git submodules
    └── <project>/             # harness reads only; never writes harness files here
```

The line between "harness-owned" and "submodule-owned" is the `projects/` boundary. Everything above it is the harness's tree and may be freely edited by harness operations. Everything under `projects/<name>/` belongs to that project's own repository and is off-limits to harness writes.

## 10. Open Questions

1. **Submodule writes during agent tasks.** Harness operations never write to a submodule (Principle 1). But agent *tasks* explicitly targeting a submodule do produce code changes that land there. Open question: do those agent commits go directly to the submodule's branch + push to its origin, or stage in the harness as a patch series for human review first? Tentatively: patch-series-first for new harness deployments, direct-commit opt-in once trust is established.
2. **Secrets.** Where do credentials for the wrapped repo's services live? Proposed: `.env.local` (gitignored) + a `1password` / `sops` integration as a follow-up.
3. **Multi-repo monos.** A monorepo with multiple deployable units — one harness, multiple `services:` entries, or one harness per unit? Tentatively: one harness per logical product surface, with `harness.yml` allowed to scope to a subdirectory.
4. **Index backend default.** SQLite FTS5 covers most repos, but embeddings noticeably help on natural-language queries. Ship FTS5 by default; document an opt-in path to Lance.
5. **Agent identity.** Commits from agents — co-author trailer, separate bot account, or both? Needs an org-level decision.
6. **Cost ceilings.** Scheduled `agent-loop.yml` could burn budget. Need a per-run token/time cap and a kill switch.

## 11. Milestones

- **M0 — Spec (this doc).** ✅
- **M0.5 — Initialization skill + entry points.** ✅
- **M0.7 — Generic skeleton.** ✅ Directory tree, standard `Makefile`, skill stubs, agent policies (md + yaml), `harness` CLI scaffold (Click + Jinja2), bash hooks, fallback `env/Dockerfile` + `docker-compose.yml`, CI workflow stub.
- **M0.8 — Post-trial enhancements.** ✅ Language normalization + data-driven runtime blocks, compose v1/v2 detection, persistent dev container (`up`→`exec` pattern), `make deps`/`make ci` targets, init skill fast-path + complexity scaling.
- **M1 — Bootstrap.** `harness.yml` schema + `make bootstrap` generating `env/` for a Python sample repo.
- **M2 — Context.** Frontmatter convention, FTS5 index, `harness ctx` CLI.
- **M3 — Skills + Agent hooks.** Standard skills set, `pre-commit.sh` policy gate.
- **M4 — CI.** `ci.yml` with report aggregation and PR comment.
- **M5 — Loop.** End-to-end agent run on a seeded bug in the sample repo.
- **M6 — Second language.** Repeat M1–M5 with a TypeScript sample to validate the contract is truly generic.

## 12. Non-Goals (Restated)

- Not a build system. Not a package manager. Not an agent runtime.
- Not a replacement for the wrapped project's docs — it is a *layer* over them.
- Not a security boundary by itself; treat agent policies as defense-in-depth, not isolation.
