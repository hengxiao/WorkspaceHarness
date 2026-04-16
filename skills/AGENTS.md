---
name: agents-entry
description: Entry point for non-Claude agents (Cursor, Copilot, etc.). Same routing as CLAUDE.md.
audience: [agent]
---

# Agents — Entry Point

See `skills/CLAUDE.md` for the full routing logic. The same rules apply to all agents:

1. If the harness is uninitialized → run `skills/initialization.md`.
2. If initialized → consult `skills/` and `context/` before changing code.
3. Never write harness files into `projects/<name>/`.
4. Never deinit a submodule or push to its upstream without explicit user confirmation.
