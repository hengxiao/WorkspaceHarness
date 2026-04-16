---
name: agent-policies
description: What agents may and may not do autonomously inside this harness. The machine-readable mirror is policies.yaml — keep them in sync.
audience: [agent, human]
---

# Agent Policies

The defaults below apply to **all** agents (Claude Code, Cursor, Copilot, scheduled bots). Per-project overrides go in `harness.yml` under `agent.allow:` / `agent.deny:` / `agent.require_human_for:`.

The machine-readable form (`policies.yaml`) is what the `pre-commit.sh` hook actually enforces. Keep this document and that file in sync; CI will fail if they drift.

## Default-allow

Agents may, without confirmation:

- Read any file in the harness or in `projects/<name>/` (read-only).
- Run `make build`, `make test`, `make lint`, `make shell`, `make up`, `make down`, `make reindex`, `make report`.
- Create or edit files anywhere in the harness tree (`context/`, `skills/`, `agent/`, `env/`, `.spec/`).
- Edit files inside `projects/<name>/` **only when** the active task targets that project's own work (a bug fix, feature, or its docs) AND that project has `writable: true` in `harness.yml`.
- Create branches and local commits in the harness repo and in writable submodules.

## Default-deny

Agents may **not**, without explicit user confirmation:

- Push to any remote (`git push`).
- Force-push, rewrite published history (`rebase -i`, `reset --hard` on shared refs), or delete branches.
- Run `git submodule deinit` or remove a submodule.
- Modify `.gitmodules`, `.github/`, or `harness.yml` in ways that change the project list.
- Run `make deploy` or any deploy-shaped command.
- Install or upgrade major dependency versions (patch upgrades are allowed).
- Read or write secrets (`.env`, `*.key`, `*.pem`, anything matching `secrets/`).
- Write **harness files** (anything from `context/`, `skills/`, `agent/`, `env/`, `.spec/`, `.harness/`, `.github/`, `harness.yml`) into a submodule. This is non-negotiable — see `.spec/design.md` Principle 1.

## Require-human-for

Even with all gates passing, the following require a human on the PR before merge:

- Schema migrations
- Major dependency upgrades
- Changes to `agent/policies.*` itself
- Changes to `.spec/`
- First-touch on a previously-unmodified submodule

## Enforcement

- `agent/hooks/pre-commit.sh` reads `policies.yaml` and rejects commits that violate `deny` rules.
- CI re-runs the same check on PRs (`policy-check` job) so a bypassed local hook still catches at the gate.
- The harness CLI (`harness policy check <cmd>`) lets agents test a command before running it.

## How to update this policy

1. Edit this doc and `policies.yaml` together.
2. Open a PR. The `require_human_for` rule above means a human reviews policy changes.
