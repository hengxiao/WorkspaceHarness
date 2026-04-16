---
name: deployment
description: How code reaches production for the projects in this harness.
audience: [agent, human]
status: stub
---

# Deployment

> **Stub — fill per project during initialization.** Deployment is project-specific; this file should hold cross-cutting rules only.

## Cross-cutting rules

- Agents may **not** trigger production deploys autonomously. Deploy commands are listed under `agent.deny:` in `harness.yml`.
- Every deploy must have a corresponding entry in the project's `CHANGELOG.md` (or equivalent).
- Rollback procedure must be documented before a new deployment path is added.

## Per-project deployment

Place project-specific deploy steps in `skills/projects/<name>/deployment.md`. Each should cover:

- Where the artifact comes from (build pipeline)
- Where it goes (target environment, region, cluster)
- How to promote between environments
- How to roll back
- Who/what to monitor during a deploy

## How to update this skill

Edit and commit. If a deploy step requires a secret, do not write the secret here — point at where it lives (1Password vault, GitHub Actions secret, etc.).
