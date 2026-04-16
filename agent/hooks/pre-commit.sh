#!/usr/bin/env bash
# Pre-commit hook: enforces agent/policies.yaml on the staged change set.
# Install with:
#   ln -sf ../../agent/hooks/pre-commit.sh .git/hooks/pre-commit
# CI runs the same check; this is the local first line of defense.

set -euo pipefail

if ! command -v harness >/dev/null 2>&1; then
  echo "harness CLI not on PATH; skipping policy check." >&2
  echo "Install it with: pip install -e cli/" >&2
  exit 0
fi

if ! harness policy check --staged; then
  echo ""
  echo "Pre-commit blocked by agent/policies.yaml."
  echo "If this is intentional, commit with --no-verify ONLY with explicit user approval."
  exit 1
fi
