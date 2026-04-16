#!/usr/bin/env bash
# Runs after an agent finishes a task.
# Runs make test/lint/report and writes a per-task summary.
#
# Inputs (env vars):
#   HARNESS_TASK_ID — required
#   HARNESS_SKIP_TESTS=1 — optional; skip make test (e.g. for doc-only tasks)

set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TASK_ID="${HARNESS_TASK_ID:?HARNESS_TASK_ID is required}"
TASK_DIR="${HARNESS_ROOT}/.harness/agent/${TASK_ID}"

mkdir -p "${TASK_DIR}"
cd "${HARNESS_ROOT}"

if [ -z "${HARNESS_SKIP_TESTS:-}" ]; then
  make -f env/Makefile test  || echo "test: failed"  >> "${TASK_DIR}/results.txt"
  make -f env/Makefile lint  || echo "lint: failed"  >> "${TASK_DIR}/results.txt"
fi
make -f env/Makefile report || true

# Capture the diff against pre-task state.
git -C "${HARNESS_ROOT}" diff --stat > "${TASK_DIR}/diffstat.txt" || true
git -C "${HARNESS_ROOT}" diff         > "${TASK_DIR}/diff.patch"   || true

# Per-submodule diffs.
if [ -f "${HARNESS_ROOT}/.gitmodules" ]; then
  while IFS= read -r path; do
    [ -d "${HARNESS_ROOT}/${path}" ] || continue
    git -C "${HARNESS_ROOT}/${path}" diff --stat > "${TASK_DIR}/diff.${path//\//_}.stat" || true
  done < <(git -C "${HARNESS_ROOT}" config -f .gitmodules --get-regexp 'submodule\..*\.path' | awk '{print $2}')
fi

{
  echo "ended_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "report: $(test -f .harness/reports/report.md && echo present || echo missing)"
} >> "${TASK_DIR}/snapshot.yaml"

echo "post-task ok: ${TASK_DIR}"
