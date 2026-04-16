---
title: Harness architecture — QuestionnaireHelper
tags: [architecture, single-project]
summary: Single-project harness wrapping a client-side YAML-driven questionnaire app. No backend, no shared services.
updated: 2026-04-15
source: internal
---

# Architecture

This harness wraps a single project: **questionnaire-helper**.

## Stack

- **Frontend only** — vanilla HTML/CSS/JS, no framework, no build step.
- **No backend** — all data stays client-side (localStorage + YAML file export).
- **No shared services** — no database, cache, or message queue.

## Dev workflow

1. `node serve.js 4001` starts a zero-dependency static file server.
2. Open `http://localhost:4001/questionnaire.html?yaml=example.yaml` in a browser.
3. Tests: `npm test` (Playwright, Chromium, 101 tests).

## Deployment

GitHub Pages — push to `main` and the live demo updates automatically.
