#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
SPEC_ROOT="${REPO_ROOT}/benchmarks/cpu2017"
LOG_DIR="${REPO_ROOT}/profiling/results/logs"
WALL_FILE="${LOG_DIR}/spec_641_leela_s.wall_seconds"
mkdir -p "${LOG_DIR}"

cd "${SPEC_ROOT}"
source shrc

SPEC_CONFIG="${SPEC_CONFIG:-gnr3-profile}"
SPEC_SIZE="${SPEC_SIZE:-train}"

START_SEC=$(date +%s)
set +e
runcpu \
  --config="${SPEC_CONFIG}" \
  --copies=1 \
  --iterations=1 \
  --tune=base \
  --size="${SPEC_SIZE}" \
  --noreportable \
  641.leela_s | tee "${LOG_DIR}/spec_641_leela_s.log"
RC=${PIPESTATUS[0]}
set -e
END_SEC=$(date +%s)
echo "$((END_SEC - START_SEC))" > "${WALL_FILE}"
exit "${RC}"
