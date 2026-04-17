---
name: claude-entry
description: Entry point loaded automatically by Claude Code. Routes to the right skill based on harness state.
audience: [agent]
---

# Claude Code — Entry Point

This is a **workspace-harness** repo. It wraps Git projects (as submodules under `projects/`) with context, skills, and a dev environment so AI agents can work productively across them.

## Read these first

- `.spec/design.md` — what the harness is and how it is meant to work. **Principle 1** (submodule isolation) is non-negotiable.
- `harness.yml` — declarative config for this specific harness (may not exist yet if uninitialized).
- `.harness/state.json` — runtime state (may not exist yet if uninitialized).

## Routing

1. **If `harness.yml` is missing OR `.harness/state.json.status != "initialized"`**:
   → Run the `initialization` skill at `skills/initialization.md`. That is the only correct first action; do not start improvising structure.

2. **If the user asks to add a new submodule to an already-initialized harness**:
   → Re-enter the `initialization` skill at Phase 2 for the new project only.

3. **If initialized and the user asks to do real work** (fix a bug, add a feature, investigate):
   → Read `skills/` for the relevant guide, then `context/` for relevant background, then proceed.

## Code structure index

The harness maintains a SQLite index (`.harness/code.db`) of every
project's source structure — symbols, references, imports, and type
hierarchies. **Use it instead of grep/glob for structural questions.**

| Task | Command |
| --- | --- |
| Find where a symbol is defined | `harness ctx symbol <name> --json` |
| Search symbols by keyword | `harness ctx search "<query>" --json` |
| List top-level symbols in a file | `harness ctx file <path> --json` |
| Find all callers of a function | `harness ctx callers <name> --json` |
| Find files that import a module | `harness ctx imports <module> --reverse --json` |
| Show class hierarchy | `harness ctx hierarchy <class> --json` |
| Check index freshness | `harness ctx stats` |
| Rebuild after code changes | `harness ctx reindex` |
| Custom query | `harness ctx query "SELECT ..." --json` |

Always use `--json` for programmatic consumption. The index is rebuilt
automatically during initialization (Phase 6.5) and can be refreshed
incrementally at any time with `harness ctx reindex`.

If `harness ctx stats` shows the index is empty or stale, run
`harness ctx reindex` before relying on structural queries.

## Hard rules

- Never write harness files into `projects/<name>/`. See `.spec/design.md` Principle 1.
- Never `git submodule deinit` / `git rm` a submodule without explicit user confirmation.
- Never push to a submodule's upstream remote without confirmation.
