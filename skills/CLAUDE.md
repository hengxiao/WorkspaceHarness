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

## Hard rules

- Never write harness files into `projects/<name>/`. See `.spec/design.md` Principle 1.
- Never `git submodule deinit` / `git rm` a submodule without explicit user confirmation.
- Never push to a submodule's upstream remote without confirmation.
