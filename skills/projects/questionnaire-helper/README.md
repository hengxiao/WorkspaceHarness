---
name: questionnaire-helper-skills
description: Project-specific skills for the QuestionnaireHelper client-side questionnaire app.
audience: [agent]
project: questionnaire-helper
---

# questionnaire-helper

## What's special about this project

- **No build step.** Plain HTML/CSS/JS — edit and refresh.
- **YAML-driven content.** All survey content lives in YAML files. The code is generic; only the YAML changes per questionnaire.
- **Bilingual support.** Any text field can be a plain string or `{en: "...", zh: "..."}`. Use `txt(val)` for HTML rendering, `plainText(val)` for bare strings.
- **UMD validator.** `validator.js` runs in both browser (`<script>`) and Node.js (`require()`). Changes must preserve both paths.
- **AI-first YAML authoring.** The repo ships skill files for five AI coding assistants. When generating questionnaire YAMLs, always validate with `node -e "..."` (see AGENTS.md) before declaring success.

## Testing

- 101 Playwright tests, Chromium only, single worker, serial execution.
- Dev server auto-starts via Playwright's `webServer` config on port 4001.
- After any change to `validator.js`, `questionnaire.js`, `reader.js`, or `tests/`: run `npm test`.

## Coding style

- No frameworks, no bundler, no transpiler.
- All HTML escaping through `escHtml()`.
- Question IDs: `Q<section>.<n>` for sections, `S<n>` for summary.
- Never interpolate YAML content directly into innerHTML.

## Deployment

GitHub Pages — automatic on push to `main`.
