---
name: testing
description: How to write and run tests across the projects in this harness.
audience: [agent, human]
---

# Testing

## Principles

- **Reproduce-first for bugs.** A bug fix without a regression test is incomplete.
- **Test at the right boundary.** Prefer the highest-level test that still pinpoints the failure.
- **Don't mock what you can run.** If the dev container can spin up a real Postgres, use it instead of a mock.
- **Don't test the framework.** Test your code's behaviour, not the library's.

## Running tests

Always via the harness so reports land in the canonical place:

```
make test           # runs the wrapped project's test suite inside the dev container
make lint           # static checks
make report         # aggregates .harness/reports/ into report.md
```

Outputs:

- `.harness/reports/test/junit.xml` — machine-readable
- `.harness/reports/lint/results.sarif` — code-scanning UI surfaces this in GitHub
- `.harness/reports/report.md` — human-readable digest, also posted to PRs

## Per-project test conventions

File patterns, fixture locations, coverage thresholds, and integration vs. unit split are project-specific. Document them in `skills/projects/<name>/testing.md`.

## CI

CI runs the same `make build test lint report` inside the same dev image. There is no "CI-only" test path. If a test passes locally and fails in CI, that is a bug in the harness, not in the test.

## How to update this skill

Edit and commit. If a project introduces a new test runner, capture how to invoke it (and how to read its output) under `skills/projects/<name>/testing.md`.
