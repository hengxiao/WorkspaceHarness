---
title: questionnaire-helper — overview
tags: [upstream, overview, javascript, html, css, playwright]
summary: A lightweight, purely client-side questionnaire app driven by YAML files. No build step. Respondents fill a form that auto-saves to localStorage and export answers as YAML. An organizer reader loads multiple answer files for side-by-side review. 101 Playwright E2E tests.
updated: 2026-04-15
source: derived
project: questionnaire-helper
project_ref: cff9245
---

# questionnaire-helper

## Purpose

Generic, reusable client-side survey / questionnaire tool. All survey content lives in a YAML file; the HTML/CSS/JS is content-agnostic and can serve any questionnaire. Supports bilingual (or multilingual) text via a `TextValue` convention (plain string or `{en: "...", zh: "..."}`). Hosted on GitHub Pages.

## Language & Toolchain

- **Languages:** JavaScript (vanilla, no framework), HTML, CSS
- **Build step:** none — plain files served directly
- **Runtime:** browser (client-side) + Node.js (dev server + tests)
- **Node version:** not pinned; uses `require()` (CommonJS)
- **Package manager:** npm (minimal — only Playwright as a devDependency)

## How it's built

No build step. The app is four static files:

| File | Role |
| --- | --- |
| `questionnaire.html` + `questionnaire.js` + `questionnaire.css` | Respondent form — fetches YAML via `?yaml=` URL param, validates, renders |
| `reader.html` + `reader.js` + `reader.css` | Organizer viewer — loads answer YAML files via drag-and-drop |
| `validator.js` | UMD schema validator — used both in-browser and in Node.js |
| `serve.js` | Minimal Node.js static file server (zero dependencies) |

Configuration is in `settings.yaml` (app-level defaults) and the questionnaire YAML file itself.

## How it's tested

- **Framework:** Playwright (Chromium only)
- **101 tests** across 3 spec files:
  - `tests/questionnaire.spec.js` (614 lines) — respondent form E2E
  - `tests/reader.spec.js` (306 lines) — answer reader E2E
  - `tests/validation.spec.js` (372 lines) — YAML validator unit/integration
- **Config:** `playwright.config.js` — single worker, serial, baseURL `http://localhost:4001`
- **Dev server:** Playwright auto-starts `node serve.js 4001` via `webServer` config
- **Run:** `npm install && npx playwright install chromium && npm test`
- **Reports:** HTML reporter at `playwright-report/` (open=never by default)

## Service dependencies

None. Purely client-side; no database, no backend API. The dev server (`serve.js`) is a zero-dependency Node HTTP static file server.

## Notable directories

```
.claude/commands/new-questionnaire.md  — Claude Code slash command for generating YAML
.cursor/rules/                         — Cursor AI rules for YAML editing
.github/copilot-instructions.md        — GitHub Copilot instructions
.windsurf/rules/                       — Windsurf AI rules
AGENTS.md                              — Full YAML schema reference for AI agents
CLAUDE.md                              — Claude Code project context
tests/                                 — Playwright test suite
```

## AI agent integration

The repo ships skill files for Claude Code, Cursor, Copilot, Codex, and Windsurf. Each teaches the agent the YAML schema so generated questionnaires validate on the first try. The Claude Code slash command `/new-questionnaire <description>` generates a complete YAML.

## Key conventions

- All YAML text rendered via `txt(val)` (HTML) or `plainText(val)` (bare string) — never raw interpolation into innerHTML
- HTML escaping goes through `escHtml()`
- Question IDs: `Q<section>.<n>` for section questions, `S<n>` for summary questions
- Section IDs: plain integers as strings (`"1"`, `"2"`, ...)
