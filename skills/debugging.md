---
name: debugging
description: How to debug problems in the projects this harness wraps.
audience: [agent, human]
status: stub
---

# Debugging

## Methodology

1. **Reproduce first.** Write a failing test before changing any code. If you can't reproduce, say so explicitly — do not guess at fixes.
2. **Find the root cause, not a symptom.** A patch that makes the symptom go away without an explanation is a regression waiting to happen.
3. **Search context first.** `harness ctx search "<symptom>"` — there may be a prior bug, design doc, or runbook.
4. **Check the boundaries.** Most bugs live at interfaces (network, serialization, time zones, encoding, concurrency, retries).
5. **Capture what you learned.** If the bug surfaces missing knowledge, add a doc to `context/bugs/` or `context/internal/` before closing.

## Standard tools (in the dev container)

- Logs: `docker compose -f env/docker-compose.yml logs -f <service>`
- Shell into a service: `docker compose -f env/docker-compose.yml exec <service> sh`
- Reset the stack to a clean state: `make reset && make up`

## Per-project debugging

Project-specific failure modes, dashboards, and tracing entry points live in `skills/projects/<name>/debugging.md`. Fill these in as incidents teach you what's worth recording.

## How to update this skill

Edit and commit. Add a new section every time an incident teaches you something an agent should know up front.
