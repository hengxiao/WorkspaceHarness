---
name: initialization
description: Bootstrap an empty workspace-harness by discovering the user's projects, pulling them in as git submodules, recording state, and gathering enough context to make the harness useful.
applies_to: [setup, onboarding, empty-harness, add-project]
audience: [agent]
required_when: "harness.yml is missing OR .harness/state.json.status != 'initialized'"
---

# Skill: Initialization

Use this skill the very first time an agent opens a workspace-harness, or whenever a new submodule is being added. It is the on-ramp from an empty harness to a usable one.

## Operating Principles

1. **Ask, don't assume.** Initialization is a conversation. Every project, branch, design decision, and integration relationship comes from the user. Do not invent answers; do not pick defaults silently.
2. **Record after every phase.** Write to `.harness/state.json` and the relevant artifacts at the end of each phase, not at the end of the run. Initialization must be **resumable**.
3. **Submodule isolation.** The only write to `projects/<name>/` permitted during initialization is `git submodule add`. All harness-side artifacts (state, context snapshots, derived skills) go into the harness tree. (See `.spec/design.md` Principle 1.)
4. **Show the user what you wrote.** After each phase, print a one-line summary of what changed and where, so the user can correct course before the next phase.

## Pre-flight

Before phase 0:

- Confirm you are at the harness repo root (the directory containing this `skills/` folder).
- If `harness.yml` already exists AND `.harness/state.json.status == "initialized"`, switch modes:
  - If the user is asking to add a new project, jump to **Phase 2** for the new project only.
  - Otherwise, tell the user the harness is already initialized and stop.

## Phase 0 — Detect State

1. Read `.harness/state.json` if it exists. It is the resume token.
2. If absent, create it with:
   ```json
   {
     "version": 1,
     "status": "in_progress",
     "started_at": "<ISO timestamp>",
     "current_phase": "discovery",
     "harness_purpose": null,
     "projects": []
   }
   ```
3. Resume from `current_phase` if the file already exists. Skip phases that are already complete.

## Phase 1 — Discovery

Have a short conversation with the user. Ask, in order:

1. **What is this harness for?** One sentence — e.g. *"Backend + iOS client for the AcmePay payments stack"*. Record as `harness_purpose`.
2. **Which Git repositories do you work on inside this harness?** For each:
   - Repository URL (SSH or HTTPS)
   - Short name (used as the directory under `projects/`)
   - Default branch to track (`main`, `develop`, etc.)
   - Optional: a one-line purpose for that project
3. **Read-only or contributable?** For each project, ask whether the user expects agents to commit changes back to that submodule's repo, or only read it.

Record each as a pending entry under `projects[]` in state.json:

```json
{
  "name": "my-service",
  "url": "git@github.com:acme/my-service.git",
  "branch": "main",
  "purpose": "...",
  "writable": true,
  "status": "pending"
}
```

Confirm the full list with the user before moving on. Update `current_phase` to `"submodule_pull"`.

## Phase 2 — Pull Submodules

For each `pending` project, in sequence (not in parallel — easier to recover from failures):

1. Run `git submodule add <url> projects/<name>`.
2. Run `git -C projects/<name> checkout <branch>`.
3. Verify the working tree exists and is at the expected ref.
4. Update that project's `status` to `"pulled"` in state.json.
5. Print: `Pulled <name> @ <branch> (<short-sha>)`.

If a submodule fails to clone (auth, network, wrong URL), do NOT silently skip — surface the error to the user, ask whether to fix the URL or remove the entry, and update state.json accordingly.

When all are pulled, commit the `.gitmodules` change in the harness repo:

```
git add .gitmodules projects/
git commit -m "harness: add submodules <names>"
```

Update `current_phase` to `"per_project_analysis"`.

## Phase 3 — Per-Project Analysis

For each pulled project, do a **read-only** scan of its tree and write findings into `context/upstream/<name>/overview.md` (in the harness tree — never inside the submodule).

What to look at:

- `README.md`, `CHANGELOG.md`, `LICENSE`
- Build/dependency manifests: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `Gemfile`, etc.
- Container/orchestration: `Dockerfile`, `docker-compose.yml`, `Makefile`, `Justfile`, `Taskfile.yml`
- Test config: `pytest.ini`, `jest.config.*`, `*_test.go` patterns
- CI: `.github/workflows/`, `.gitlab-ci.yml`, etc.
- Top-level directory structure (one level deep is usually enough)

Write `context/upstream/<name>/overview.md` with frontmatter:

```yaml
---
title: <name> — overview
tags: [upstream, overview, <language>]
summary: <one-paragraph TL;DR>
updated: <date>
source: derived
project: <name>
project_ref: <commit sha at analysis time>
---
```

Body sections to fill in: **Purpose**, **Language & Toolchain**, **How it's built**, **How it's tested**, **Service dependencies**, **Notable directories**, **Open questions for the user**.

Then **prompt the user** with the open questions you collected — anything you couldn't determine from the files. Examples:

- "I see Django + Postgres. What database does production actually use?"
- "There's a `Makefile`, but no `test` target. How do you run tests today?"
- "I see two HTTP frameworks imported. Which is the real one?"

Capture answers back into `overview.md`. Update that project's `status` to `"analyzed"` in state.json.

## Phase 4 — Cross-Project Analysis

Only if there is more than one project. Ask the user:

1. **How do these projects relate?** (client/server, producer/consumer, library/app, monorepo split, ...)
2. **Are there shared services?** (Postgres used by both? A single Redis? Same Kafka cluster?)
3. **Which is the entry point** for someone debugging end-to-end?
4. **Are there contracts between them?** (REST schema, protobuf, OpenAPI, GraphQL)
5. **What's the local dev story today?** (Each runs standalone? Compose stack? Tilt? Skaffold?)

Write the answers to `context/architecture.md` (harness-native, not under `upstream/`):

```yaml
---
title: Cross-project architecture
tags: [architecture, integration]
summary: How the projects in this harness fit together.
updated: <date>
source: internal
---
```

If the user provides a diagram, save it next to the doc and link it.

## Phase 5 — Capture Design & Decision Context

Ask the user about supporting material that lives outside the repos:

1. **Design docs / RFCs / ADRs** — links or paths. For each, ask whether to (a) link only, (b) ingest into `context/specs/design/`, or (c) summarize and store the summary.
2. **Requirement specs** — same options, into `context/specs/requirements/`.
3. **Bug-tracker references** — Linear/Jira/GitHub project URLs. Save as a reference doc in `context/internal/trackers.md`.
4. **Dashboards & runbooks** — Grafana, oncall docs. Save as reference entries.
5. **Past incidents / postmortems** worth knowing about. Capture summaries into `context/bugs/`.
6. **Implicit knowledge** — ask: *"What's the one thing a new engineer always gets wrong here?"* and write the answer somewhere prominent (likely `skills/coding-style.md` or `context/internal/gotchas.md`).

Each captured doc must have proper frontmatter (see `.spec/design.md` §6.1).

Don't try to exhaust the user. Two or three rounds, then move on — context is built incrementally and the agent loop will surface gaps later.

## Phase 6 — Generate `harness.yml` and Finalize State

Write `harness.yml` from everything collected. Sketch:

```yaml
version: 1

harness:
  purpose: "<harness_purpose>"
  initialized_at: "<ISO timestamp>"

projects:
  - name: my-service
    path: projects/my-service
    submodule:
      url: git@github.com:acme/my-service.git
      ref: main
    writable: true
    runtime:
      language: [python]
      python: { version: "3.12" }
    commands:
      build: "<from analysis>"
      test:  "<from analysis>"
      lint:  "<from analysis>"

services:
  # populated from cross-project analysis (shared db, redis, etc.)

context:
  ingest:
    - source: "{project.path}/docs/**/*.md"
      into:   "context/upstream/{project.name}/docs/"
      tags:   [docs, upstream]

agent:
  policy: agent/policies.md
  # populated with sensible defaults; user reviews
```

Show the generated file to the user, ask for corrections, then save.

Update `.harness/state.json`:

```json
{
  "version": 1,
  "status": "initialized",
  "initialized_at": "<ISO timestamp>",
  "harness_purpose": "...",
  "projects": [
    { "name": "...", "url": "...", "branch": "...", "ref": "<sha>", "writable": true, "status": "analyzed" }
  ]
}
```

## Phase 7 — Seed Per-Project Skills

For each project, create a stub at `skills/projects/<name>/README.md`:

```yaml
---
name: <name>-skills
description: Project-specific skills for <name>. Override or extend the harness defaults.
audience: [agent]
project: <name>
---
```

Body: `# <name>` plus a "What's special about this project" section that the user fills in (or that future agent runs add to as they learn).

## Phase 8 — Handoff

Print a short summary to the user:

- Harness purpose
- Projects pulled (name @ branch @ short-sha)
- Files created (count + a few key paths)
- Suggested next steps:
  - Review `harness.yml` and `context/architecture.md`
  - Run `make bootstrap` once the env layer exists (M1)
  - Open an issue or task and let the agent loop run

Set `status` to `initialized`. Done.

## Failure & Recovery

- If interrupted at any phase, the next invocation reads `.harness/state.json` and resumes from `current_phase`.
- If the user wants to *redo* a phase (e.g. they realized they listed the wrong branch), they can edit state.json and set that project's `status` back to `pending`/`pulled`/`analyzed` accordingly. Document this in the handoff message.
- Never delete a submodule without explicit user confirmation — `git submodule deinit` + `rm -rf .git/modules/<name>` + `git rm projects/<name>` is destructive.

## What This Skill Does NOT Do

- It does not generate the `env/` layer (Dockerfile, compose, Makefile). That is the bootstrap step (M1), separate from initialization.
- It does not run any code from the submodules. Read-only static analysis only.
- It does not push anything to the submodules' upstream remotes.
