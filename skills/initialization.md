---
name: initialization
description: Bootstrap an empty workspace-harness by discovering the user's projects, pulling them in as git submodules, recording state, and gathering enough context to make the harness useful.
applies_to: [setup, onboarding, empty-harness, add-project]
audience: [agent]
required_when: "harness.yml is missing OR .harness/state.json.status != 'initialized'"
---

# Skill: Initialization

Use this skill the very first time an agent opens a workspace-harness, or whenever a new submodule is being added. It is the on-ramp from an empty harness to a usable one.

## Operating Modes

### Interactive (default)

The agent walks the user through discovery, asking questions at each phase. Use this when the user opens a blank harness and says something general like "set up this harness" or "initialize".

### Fast-path (auto-detect)

When the user provides enough up front — typically a repo URL and "initialize with this" — skip the conversational phases and auto-detect as much as possible:

1. Infer project **name** from the URL (last path segment, lowercased, hyphens for separators).
2. Detect **default branch** via `git ls-remote --symref <url> HEAD`.
3. Default to **writable: true** (the user is providing their own repo).
4. Derive **purpose** from the submodule's `README.md` first paragraph after cloning.
5. Detect **language/runtime** from manifest files (see Phase 3 detection table).
6. Detect **deps / build / test / lint / run** commands from manifests and scripts.
7. Only prompt the user when something is genuinely ambiguous (see "When to prompt" below).

**When to prompt in fast-path mode:**

- Multiple conflicting build systems detected (e.g. both `Makefile` and `Justfile`).
- No test runner detected at all.
- Multiple language runtimes with no clear primary.
- The user explicitly asked to be consulted ("prompt questions when needed").

If the user said "continue all phases until done" or similar, treat ambiguity as a decision you make with a sensible default + a note in the handoff summary explaining the choice.

## Operating Principles

1. **Infer first, ask second.** Try to detect everything from the codebase. Only prompt when detection is ambiguous or impossible.
2. **Record after every phase.** Write to `.harness/state.json` and the relevant artifacts at the end of each phase, not at the end of the run. Initialization must be **resumable**.
3. **Submodule isolation.** The only write to `projects/<name>/` permitted during initialization is `git submodule add`. All harness-side artifacts (state, context snapshots, derived skills) go into the harness tree. (See `.spec/design.md` Principle 1.)
4. **Show the user what you wrote.** After each phase, print a one-line summary of what changed and where, so the user can correct course before the next phase.
5. **Scale depth to complexity.** Simple projects (single repo, no backend, no services) get a streamlined flow. Complex projects (multi-service, shared infrastructure) get the full treatment.

## Complexity Detection

After Phase 2 (pull), assess complexity to decide which phases to run in full, abbreviate, or skip:

| Signal | Low complexity | High complexity |
| --- | --- | --- |
| Number of projects | 1 | 2+ |
| Backend/DB/services | none detected | docker-compose, DB config, API schemas |
| Language count | 1 | 2+ across projects |
| Existing CI config | simple or absent | multi-stage, matrix builds |

**Low complexity** (all "low" signals): abbreviate Phases 4 & 5 — write a brief `context/architecture.md` from what's visible, skip the multi-round user interview. Note skipped areas in the handoff.

**High complexity** (any "high" signal): run Phases 4 & 5 in full.

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

**Interactive mode:** Have a short conversation with the user. Ask, in order:

1. **What is this harness for?** One sentence.
2. **Which Git repositories do you work on inside this harness?** For each: URL, short name, default branch, one-line purpose.
3. **Read-only or contributable?** Per project.

**Fast-path mode:** The user already provided the URL(s). Infer name, branch, purpose, writable from the URL and defaults. Skip the conversation.

Record each as a pending entry under `projects[]` in state.json. Update `current_phase` to `"submodule_pull"`.

## Phase 2 — Pull Submodules

For each `pending` project, in sequence:

1. Run `git submodule add --depth 1 -b <branch> <url> projects/<name>`.
   The `--depth 1` shallow clone keeps the initial pull fast and small; full
   history can be fetched later with `git -C projects/<name> fetch --unshallow`
   when needed (e.g. for `git log`, `git blame`, or bisect).
2. Verify the working tree exists and is at the expected ref.
3. Update that project's `status` to `"pulled"` in state.json.
4. Print: `Pulled <name> @ <branch> (<short-sha>)`.

If a submodule fails to clone, surface the error — never silently skip.

When all are pulled, commit the `.gitmodules` change in the harness repo.

Update `current_phase` to `"per_project_analysis"`.

## Phase 3 — Per-Project Analysis

For each pulled project, do a **read-only** scan of its tree and write findings into `context/upstream/<name>/overview.md` (in the harness tree — never inside the submodule).

### Detection table — derive facts from files, not docs

Manifests answer "what toolchain?". Lock files answer "how should deps be installed?". **When a lock file is present, prefer the locked/frozen install command** — it pins exact versions and is the correct choice for reproducible CI builds.

| Manifest | Lock file | `deps` command (prefer locked) | Other inferences |
| --- | --- | --- | --- |
| `package.json` | `package-lock.json` | `npm ci` (not `npm install`) | language=node; scripts.test for test cmd |
| `package.json` | `pnpm-lock.yaml` | `pnpm install --frozen-lockfile` | pnpm workspace |
| `package.json` | `yarn.lock` | `yarn install --frozen-lockfile` | yarn classic/berry |
| `pyproject.toml` | `poetry.lock` | `poetry install --no-interaction` | language=python |
| `pyproject.toml` | `uv.lock` | `uv sync --frozen` | language=python (uv) |
| `pyproject.toml` | `pdm.lock` | `pdm install --frozen-lockfile` | language=python (pdm) |
| `requirements.txt` | `requirements.lock` / `*.lock` | `pip install -r requirements.lock` | language=python (pip) |
| `Pipfile` | `Pipfile.lock` | `pipenv sync` | language=python (pipenv) |
| `Cargo.toml` | `Cargo.lock` | `cargo fetch --locked` | language=rust; test=`cargo test --locked` |
| `go.mod` | `go.sum` | `go mod download` (go.sum is used automatically) | language=go |
| `Gemfile` | `Gemfile.lock` | `bundle install --deployment` or `bundle config frozen 1 && bundle install` | language=ruby |
| `mix.exs` | `mix.lock` | `mix deps.get` (reads mix.lock) | language=elixir |
| `composer.json` | `composer.lock` | `composer install --no-interaction` | language=php |
| `pom.xml` / `build.gradle` | — | `mvn dependency:go-offline` / `gradle dependencies` | language=java |

Other orthogonal signals:

| File present | Infer |
| --- | --- |
| `Makefile` / `Justfile` / `Taskfile.yml` | check for `test`, `build`, `lint` targets |
| `docker-compose.yml` | service dependencies (DB, cache, etc.) |
| `.github/workflows/*.yml` | CI commands — often the most reliable source of build/test/lint |
| `playwright.config.*` / `jest.config.*` / `pytest.ini` / `.rspec` | test framework and runner |
| `.eslintrc*` / `ruff.toml` / `.golangci.yml` / `clippy.toml` | linter |

**Lock-file rule of thumb:** if the lock file is checked in, use the locked install command. If it's gitignored (uncommon), use the unlocked one. Never use an unlocked command when a lock file exists — that can silently upgrade dependencies and hide bugs.

### Derive commands

From the detection, construct the `commands:` block for `harness.yml`:

- **`deps`**: install dependencies (e.g. `npm install`, `pip install -e .`, `cargo fetch`)
- **`build`**: produce artifacts (e.g. `npm run build`, `cargo build`). **Omit** if the project has no build step — `harness exec build` will report "not configured" (exit 78).
- **`test`**: run the test suite (e.g. `npm test`, `pytest`, `cargo test`)
- **`lint`**: run static checks. **Omit** if no linter is configured for the project. Do NOT use `echo 'no linter configured'` — that exits 0 and falsely reports a pass. An omitted command returns `EXIT_NOT_CONFIGURED` (exit 78), which the report pipeline treats as "not applicable".
- **`run`**: start the service for manual testing (e.g. `npm start`, `node serve.js`)

**Omit, don't stub.** When a target doesn't apply to a project, leave the key out of the `commands:` block entirely. The CLI surfaces the gap explicitly; silent `echo ... && true` stubs hide real configuration debt.

### Native extensions — `build` must refresh the editable install

If the project has a compiled extension (Python with `.pyx` / `ext_modules=` / `cffi`, Rust with `pyo3`, Node with `node-gyp`, etc.), `make build` compiling the `.so`/`.node` file is **not enough**. The editable install's metadata still points at the old file location, so the rebuilt binary isn't picked up at import time. Agents that write a narrow `build: "make build"` and then run `test` see stale behavior and chase non-bugs.

**Pattern for Python + native extensions:**

```yaml
commands:
  deps: "pip install --user -e . pytest"
  build: "make build && pip install --user -e . --force-reinstall --no-deps"
```

The `--force-reinstall --no-deps` re-links the editable install without re-resolving every dependency — fast, and guaranteed to pick up the fresh `.so` file in `lib/yaml/` (or wherever the project puts it).

**Equivalent patterns for other ecosystems:**

- **Rust with pyo3** (maturin): `maturin develop` — one command does both build and install.
- **Node with native addons**: `npm rebuild` — recompiles and re-links.
- **Pure autotools / cmake C projects** (like xz): no editable-install concept; `make` alone is fine.

**Signal that this is needed:** `harness init detect` flags `has_native_extension: true` in its notes when it sees `.pyx`, `.pxd`, `ext_modules=`, or `Extension(` in `setup.py`. When you see that note, don't just use the plain `build` command — apply the refresh pattern.

**Signal that it wasn't applied:** tests pass once, you edit C/Cython source, `make build` reports success, tests still behave as before the edit. You are looking at the stale `.so` from the previous build.

### Forbidden facts in `overview.md`

READMEs rot, but `overview.md` sits next to live code. Copying a stale number there gives both humans and future agents false confidence. The following **must not** be transcribed from docs — they are either derived at runtime by the harness or omitted entirely:

| Fact | Why it's forbidden | Where it comes from instead |
| --- | --- | --- |
| Test count ("101 tests", "1,247 tests") | Drifts with every PR | `make test` → `.harness/reports/runs/*.json` |
| Coverage percentage | Same | A coverage command in `commands:` → reports |
| Build-time benchmarks | Machine-dependent anyway | Not reported |
| Dependency counts ("depends on 142 packages") | Drifts with every lockfile change | `make deps` output |
| "Last released on …" or version numbers | Stored in `NEWS`/`CHANGELOG` | Link, don't copy |
| Specific CI matrix sizes ("7 OS × 2 build systems = 14 jobs") | Changes with CI edits | Link to the workflow |

**What overview.md SHOULD contain:** purpose, language/toolchain family, how it's built (commands, not metrics), how it's tested (framework, not counts), service dependencies, notable directories, open questions.

**Rule of thumb:** if a `grep -c` or a `find | wc -l` would give a different answer in six months, leave it out.

Write `context/upstream/<name>/overview.md` with frontmatter + body sections.

Then — **in interactive mode** — prompt the user with open questions you couldn't answer from the files. **In fast-path mode**, note unanswered questions in the overview's "Open questions" section and mention them in the handoff, but do not block on them.

## Phase 4 — Cross-Project Analysis

**Skip entirely if single project with low complexity.** Write a brief `context/architecture.md` noting it's a single-project harness.

**Run in full for multi-project or high-complexity harnesses.** Ask the user:

1. How do these projects relate?
2. Are there shared services?
3. Which is the entry point for end-to-end debugging?
4. Are there contracts between them? (OpenAPI, protobuf, GraphQL)
5. What's the local dev story today?

Write `context/architecture.md` with frontmatter.

## Phase 5 — Capture Design & Decision Context

**Abbreviate for low-complexity projects.** Ask one question: "Is there anything a new engineer always gets wrong here?" Capture the answer and move on.

**Run in full for high-complexity harnesses.** Ask about:

1. Design docs / RFCs / ADRs
2. Requirement specs
3. Bug-tracker references
4. Dashboards & runbooks
5. Past incidents / postmortems
6. Implicit knowledge / gotchas

Don't try to exhaust the user. Two or three rounds, then move on.

## Phase 6 — Generate `harness.yml` and Finalize State

Write `harness.yml` from everything collected. Key additions from the analysis:

- **`commands.deps`** — always include, separate from build.
- **`runtime.language`** — use user-facing names (e.g. `javascript`, `python`). The CLI normalizes them internally.
- **`env.runtime_blocks`** — only include if the user needs to override the default install for a language (e.g. specific Node version, custom Python build). Otherwise omit and let the defaults handle it.

Show the generated file to the user (interactive) or print a summary (fast-path), then save.

Update `.harness/state.json` to `"initialized"`.

## Phase 6.5 — Build Code Structure Index

After `harness.yml` is written and before seeding skills, build the code
structure index so agents can immediately query symbol definitions, call
graphs, and import relationships:

```
harness ctx reindex
```

This walks each project's source tree, extracts symbols (functions, classes,
methods, macros, structs), references (call sites), and imports, and stores
them in `.harness/code.db` (SQLite with FTS5). The index is gitignored and
rebuilt on demand.

**What gets indexed:** every source file tracked by git (respecting
`.gitignore`), classified by extension. Currently supported extractors:
Python, C/C++. Other languages get file-level inventory only.

**Post-index verification:** Run `harness ctx stats` to confirm the index
was built. The output should show non-zero file and symbol counts for each
project. If a project shows zero symbols, check whether its language has
an extractor registered.

**Agent usage after initialization:** Agents should prefer the code index
over raw grep/glob for structural questions:

| Question | Command |
| --- | --- |
| Where is function X defined? | `harness ctx symbol X --json` |
| What does file Y export? | `harness ctx file Y --json` |
| Who calls function X? | `harness ctx callers X --json` |
| What imports module M? | `harness ctx imports M --reverse --json` |
| Class hierarchy for C? | `harness ctx hierarchy C --json` |
| Free-text search | `harness ctx search "query" --json` |
| Raw SQL | `harness ctx query "SELECT ..." --json` |

The `--json` flag is recommended for agent consumption — it returns
structured data that doesn't need parsing.

## Phase 7 — Seed Per-Project Skills

For each project, create a stub at `skills/projects/<name>/README.md` with frontmatter and key sections derived from Phase 3 analysis.

## Phase 8 — Handoff

Print a short summary:

- Harness purpose
- Projects pulled (name @ branch @ short-sha)
- Detected: languages, test frameworks, service deps
- Files created (count + key paths)
- **Code index:** file/symbol/ref counts from `harness ctx stats`
- **Gaps detected** (no linter, no build step, open questions)
- Suggested next steps:
  - `make -f env/Makefile bootstrap` to regenerate env files
  - `make -f env/Makefile up` to start the dev container
  - `make -f env/Makefile deps` to install project dependencies
  - `make -f env/Makefile test` to run tests
  - `harness ctx reindex` to refresh the code index after changes
  - Review `harness.yml` and `context/architecture.md`

Set `status` to `initialized`. Done.

## Failure & Recovery

- If interrupted at any phase, the next invocation reads `.harness/state.json` and resumes from `current_phase`.
- If the user wants to redo a phase, they can edit state.json and set that project's `status` back to `pending`/`pulled`/`analyzed`.
- Never delete a submodule without explicit user confirmation.

## What This Skill Does NOT Do

- It does not generate the `env/` layer (Dockerfile, compose). That is `harness bootstrap`, called after initialization.
- It does not run any code from the submodules. Read-only static analysis only.
- It does not push anything to the submodules' upstream remotes.
