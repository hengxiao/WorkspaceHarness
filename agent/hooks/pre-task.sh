#!/usr/bin/env bash
# Runs before an agent starts a task.
# Snapshots state and sets up a scratch dir under .harness/agent/<task-id>/.
#
# Inputs (env vars):
#   HARNESS_TASK_ID   — required; unique id for this task
#   HARNESS_TASK_KIND — optional; one of: triage, fix, feature, review

set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TASK_ID="${HARNESS_TASK_ID:?HARNESS_TASK_ID is required}"
TASK_DIR="${HARNESS_ROOT}/.harness/agent/${TASK_ID}"

mkdir -p "${TASK_DIR}"

# Snapshot the harness git state.
{
  echo "task_id: ${TASK_ID}"
  echo "task_kind: ${HARNESS_TASK_KIND:-unspecified}"
  echo "started_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "harness_head: $(git -C "${HARNESS_ROOT}" rev-parse HEAD 2>/dev/null || echo 'no-git')"
  echo "submodule_heads:"
  if [ -f "${HARNESS_ROOT}/.gitmodules" ]; then
    git -C "${HARNESS_ROOT}" submodule status | sed 's/^/  /'
  fi
} > "${TASK_DIR}/snapshot.yaml"

echo "pre-task ok: ${TASK_DIR}"
