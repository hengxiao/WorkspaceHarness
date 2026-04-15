# Workspace Harness

A pluggable harness that wraps any Git project with the context, environment, skills, and automation that AI coding agents (Claude Code, Cursor, GitHub Copilot, etc.) need to work autonomously and effectively.

## What it is

Drop in a Git repo and the harness gives it a consistent surface for both humans and AI agents:

- A searchable knowledge base of supporting context.
- A reproducible build/test/run environment.
- Codified skills and guidelines for how to work in the repo.
- A CI/CD pipeline with reports that agents can read.
- A loop where agents can develop, test, and fix on their own.

## Components

### 1. Context Library (`context/`)

The supportive corpus for the wrapped Git project — designed for fast retrieval by AI agents.

```
context/
  docs/             # public documentation
  internal/         # internal docs, runbooks, ADRs
  specs/
    design/         # design specs
    requirements/   # requirement specs
    implementation/ # implementation notes
  bugs/             # bug reports, postmortems, incident notes
  index.json        # searchable manifest (path, tags, summary, embeddings ref)
```

Conventions:

- Every document has YAML frontmatter (`title`, `tags`, `summary`, `updated`).
- A `make reindex` target rebuilds `index.json` and any vector store used for semantic search.
- Agents are expected to consult `context/` *before* writing code.

### 2. Working Environment (`env/`)

A reproducible dev/test environment. The Git project is mounted into a container so the harness never mutates the host.

```
env/
  Dockerfile              # base dev image
  docker-compose.yml      # service stack (db, cache, mocks, etc.)
  Makefile                # single entry point for common tasks
  scripts/                # helper scripts called by the Makefile
```

Standard Makefile targets every harness exposes:

| Target | Purpose |
| --- | --- |
| `make build` | Build the dev container image |
| `make shell` | Open a shell inside the dev container |
| `make up` | Bring up the full service stack |
| `make down` | Tear down the service stack |
| `make test` | Run the project's test suite inside the container |
| `make lint` | Run linters/formatters |
| `make reindex` | Rebuild the context index |

### 3. Skills & Guidelines (`skills/`)

Codified, agent-readable instructions for how work is done in this repo.

```
skills/
  coding-style.md       # how code should be constructed
  documentation.md      # how/when to document
  deployment.md         # how to deploy
  debugging.md          # debugging playbooks
  context-updates.md    # how to keep context/ fresh
  CLAUDE.md             # entry point loaded by Claude Code
  AGENTS.md             # entry point for other agents
```

These are the rules of the road. Both humans and agents should treat them as authoritative.

### 4. CI/CD Pipeline (`.github/workflows/`)

Runs on GitHub Actions. Every workflow produces a viewable report.

```
.github/workflows/
  ci.yml          # build, lint, test on every push/PR
  context.yml     # validates context/ frontmatter and rebuilds the index
  agent-loop.yml  # optional: scheduled agent runs against open issues
```

Reports are published as:

- GitHub Actions job summaries (Markdown, viewable in the run UI)
- Uploaded artifacts for test results, coverage, and lint output
- A `gh-pages` site (when enabled) for browsable historical reports

### 5. Agent Loop

The end goal: an environment where Claude Code, Cursor, or Copilot can pick up a task and carry it through.

A typical loop:

1. Agent reads `skills/CLAUDE.md` (or equivalent) and queries `context/` for relevant background.
2. Agent enters the dev container via `make shell` and works against the wrapped repo.
3. Agent runs `make test` / `make lint` to validate changes.
4. Agent opens a PR; CI runs and produces a report.
5. On failure, the agent reads the report from `.github/workflows/` artifacts and iterates.

Hooks for automation live in `agent/`:

```
agent/
  hooks/          # pre-task / post-task scripts
  prompts/        # reusable prompt fragments
  policies.md     # what agents may and may not do autonomously
```

## Getting Started

1. Clone this harness alongside (or around) the target Git project.
2. Point `env/` at the project root (a `harness.yml` at the repo root configures paths).
3. Run `make build && make up`.
4. Populate `context/` with the project's existing docs and specs.
5. Run `make reindex`.
6. Open the repo in your AI agent of choice — it will pick up `skills/CLAUDE.md` and `AGENTS.md` automatically.

## Repository Layout

```
.
├── README.md
├── harness.yml              # harness configuration (target repo, paths, etc.)
├── context/                 # searchable project knowledge
├── env/                     # containers, Makefile, service stack
├── skills/                  # guidelines for humans and agents
├── agent/                   # agent hooks, prompts, policies
└── .github/workflows/       # CI/CD pipelines
```

## Status

Early scaffolding. Components are being added incrementally — see open issues for the roadmap.
