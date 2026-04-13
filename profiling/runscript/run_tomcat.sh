#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/bench_common.sh"

require_file "${JAVA_BIN}"
require_file "${DACAPO_JAR}"

LOG_FILE="${LOG_ROOT}/tomcat.log"
WALL_FILE="${LOG_ROOT}/tomcat.wall_seconds"
mkdir -p "${TMP_ROOT}/dacapo-scratch"

DACAPO_ARGS=(
  --scratch-directory "${TMP_ROOT}/dacapo-scratch"
  -s "${SIZE:-default}"
  --watchdog "${WATCHDOG_SECS:-3600}"
)
if [[ "${DACAPO_CONVERGE:-0}" == "1" ]]; then
  DACAPO_ARGS+=(
    -C
    --max-iterations "${MAX_ITERATIONS:-30}"
    --variance "${VARIANCE_PCT:-3.0}"
    --window "${CONVERGE_WINDOW:-3}"
  )
else
  DACAPO_ARGS+=(-n "${ITERATIONS:-20}")
fi

START_SEC=$(date +%s)
set +e
"${JAVA_BIN}" -jar "${DACAPO_JAR}" "${DACAPO_ARGS[@]}" tomcat | tee "${LOG_FILE}"
RC=${PIPESTATUS[0]}
set -e
END_SEC=$(date +%s)
echo "$((END_SEC - START_SEC))" > "${WALL_FILE}"
exit "${RC}"
