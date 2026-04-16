---
name: documentation
description: What to document, where it goes, and what frontmatter to use.
audience: [agent, human]
status: stub
---

# Documentation

## What to document

- **Design decisions** that took non-trivial discussion → `context/specs/design/`
- **Requirements** (what we're building and why) → `context/specs/requirements/`
- **Implementation notes** that future-you will need → `context/specs/implementation/`
- **Bugs and postmortems** → `context/bugs/`
- **Runbooks, gotchas, oncall notes** → `context/internal/`
- **Public-facing project docs** → `context/docs/`

## What NOT to document

- Things derivable from the code (file paths, function signatures, current behaviour).
- Things derivable from git history (who changed what when).
- Step-by-step debugging walkthroughs whose fix already landed in code.

## Frontmatter (required on every file under `context/`)

```yaml
---
title: <one-line title>
tags: [<tag>, <tag>]
summary: <one-paragraph TL;DR — used in retrieval previews>
updated: YYYY-MM-DD
source: internal | upstream | generated
---
```

## After writing

- Run `make reindex` to refresh `context/index.json`.
- Commit the doc and the updated index together.

## How to update this skill

Edit and commit. If you find yourself documenting *the same thing* in code comments and in `context/`, prefer `context/` and keep the comment as a one-line pointer.
