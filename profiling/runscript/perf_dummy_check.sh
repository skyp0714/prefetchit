#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${PROFILING_ROOT}/results/benchmark_runs/logs"
mkdir -p "${LOG_DIR}"

PROFILE_CORE="${PROFILE_CORE:-1}"
PERF_BIN="${PERF_BIN:-perf}"
OUT="${LOG_DIR}/perf_dummy_check.log"

EVENTS=(
  "cpu/event=0x24,umask=0xe4,name=L1I_CODE_RD/"
  "cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/"
  "cpu/event=0x11,umask=0x0e,name=ITLB_WALK/"
  "cpu/event=0x11,umask=0x20,name=ITLB_STLB_HIT/"
  "instructions"
)

EVENT_CSV="$(IFS=,; echo "${EVENTS[*]}")"

{
  echo "[inf] perf dummy check on core ${PROFILE_CORE}"
  "${PERF_BIN}" stat --no-big-num -x, -e "${EVENT_CSV}" \
    -- taskset -c "${PROFILE_CORE}" bash -lc 'for i in $(seq 1 400); do sha1sum /usr/bin/python3 >/dev/null; done'
} > "${OUT}" 2>&1

echo "[ok] perf dummy check log: ${OUT}"
