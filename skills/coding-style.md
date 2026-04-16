---
name: coding-style
description: How code is structured, named, and commented in this harness. Per-project overrides live in skills/projects/<name>/coding-style.md.
audience: [agent, human]
status: stub
---

# Coding Style

> **Stub.** Fill in during or after initialization. Keep the rules **prescriptive** ("do X") rather than descriptive ("the code currently looks like Y" — that belongs in `context/`).

## Universal rules (apply unless a project overrides)

- Match the existing style of the file you are editing. When in doubt, mimic the nearest neighbour.
- No new abstractions until there are three concrete uses for them.
- Default to no comments. Add one only when the *why* is non-obvious.
- Don't add error handling for cases that cannot happen.
- Don't introduce dependencies without checking what's already in the manifest.

## Per-project rules

_TBD per project. Examples to fill in:_

- File and module structure
- Naming conventions (functions, types, files)
- Import / export conventions
- Error-handling conventions
- Logging conventions

## How to update this skill

Edit and commit. If a rule is project-specific, put it in `skills/projects/<name>/coding-style.md` instead.
