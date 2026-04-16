---
name: context-updates
description: When and how to refresh the context library so it stays useful for retrieval.
audience: [agent, human]
---

# Context Updates

The context library is only valuable if it stays current. Stale context misleads agents worse than missing context.

## When to update

Update or add a `context/` document **whenever** any of these happen:

| Trigger | What to write | Where |
| --- | --- | --- |
| A design discussion concluded | Design spec or ADR | `context/specs/design/` |
| A requirement changed | Requirement spec | `context/specs/requirements/` |
| An incident happened | Postmortem | `context/bugs/` |
| You discovered an undocumented gotcha | Internal note | `context/internal/` |
| A submodule's docs changed | (none — re-derived) | `context/upstream/<name>/` (auto via `make reindex`) |

## When NOT to update

- The change is purely in the code and is self-explanatory from the diff.
- The information is already in the wrapped project's own docs (let `upstream/` derive it).
- You're tempted to write a "what I just did" log — that's the PR description, not context.

## How to update

1. Create or edit the file under the right `context/` subdirectory.
2. Include the standard frontmatter (see `skills/documentation.md`).
3. Set `updated:` to today.
4. Run `make reindex`.
5. Commit the doc and the updated `index.json` together.

## Removing stale context

If a doc is no longer accurate, **delete or rewrite it**. Do not leave a "deprecated" header. The index will reflect the deletion on the next `make reindex`.

## How to update this skill

Edit and commit. If a new context category emerges (e.g. `context/security/`), add it to the table here.
