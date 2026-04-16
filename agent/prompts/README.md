---
name: agent-prompts
description: Reusable prompt fragments for common agent tasks. Loaded by the agent runner before a task starts.
audience: [agent]
---

# Agent Prompts

Each file is a self-contained prompt fragment. The agent runner concatenates the relevant fragment with the task-specific input.

## Standard set (to be filled in)

| File | Use case |
| --- | --- |
| `triage.md` | Classifying a fresh issue or bug report |
| `fix.md` | Implementing a bug fix (reproduce → fix → test → PR) |
| `feature.md` | Implementing a new feature |
| `review.md` | Reviewing a PR opened by another agent or human |

## Conventions

- Lead with the role / task in one sentence.
- Reference skills by relative path so the agent loads the right ones (e.g. "Read `skills/debugging.md` before starting").
- End with the success criteria — what the agent's output should look like.
- Keep each prompt under ~100 lines; link out to context rather than inlining.
