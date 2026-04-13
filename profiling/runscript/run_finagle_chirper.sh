#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/bench_common.sh"

require_file "${JAVA_BIN}"
require_file "${RENAISSANCE_JAR}"

LOG_FILE="${LOG_ROOT}/finagle-chirper.log"
WALL_FILE="${LOG_ROOT}/finagle-chirper.wall_seconds"
mkdir -p "${TMP_ROOT}/renaissance"
JAVA_OPTS=()
if [[ -n "${ACTIVE_CPUS:-}" ]]; then
  JAVA_OPTS+=("-XX:ActiveProcessorCount=${ACTIVE_CPUS}")
fi
START_SEC=$(date +%s)
set +e
if [[ -n "${REPETITIONS:-}" ]]; then
  "${JAVA_BIN}" "${JAVA_OPTS[@]}" -jar "${RENAISSANCE_JAR}" \
    --scratch-base "${TMP_ROOT}/renaissance" \
    -r "${REPETITIONS}" \
    finagle-chirper | tee "${LOG_FILE}"
else
  "${JAVA_BIN}" "${JAVA_OPTS[@]}" -jar "${RENAISSANCE_JAR}" \
    --scratch-base "${TMP_ROOT}/renaissance" \
    -t "${RUN_SECONDS:-300}" \
    finagle-chirper | tee "${LOG_FILE}"
fi
RC=${PIPESTATUS[0]}
set -e
END_SEC=$(date +%s)
echo "$((END_SEC - START_SEC))" > "${WALL_FILE}"
exit "${RC}"
