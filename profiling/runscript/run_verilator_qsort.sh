#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/bench_common.sh"

setup_verilator_env

ROCKET_EMU_DIR="${BENCH_ROOT}/verilator-rocket-qsort/src/rocket-chip/emulator"
EMU="${ROCKET_EMU_DIR}/emulator-freechips.rocketchip.system-freechips.rocketchip.system.DefaultConfig"
QBIN="${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv"
LOG_FILE="${LOG_ROOT}/verilator-qsort.log"
WALL_FILE="${LOG_ROOT}/verilator-qsort.wall_seconds"

if [[ "${FORCE_REBUILD:-0}" == "1" || ! -x "${EMU}" ]]; then
  "$(cd "$(dirname "$0")" && pwd)/build_verilator_qsort.sh"
fi

require_file "${EMU}"
require_file "${QBIN}"

START_SEC=$(date +%s)
: > "${LOG_FILE}"
RC=0
REPEAT_COUNT="${REPEAT_COUNT:-4}"
for i in $(seq 1 "${REPEAT_COUNT}"); do
  echo "[run] qsort repeat ${i}/${REPEAT_COUNT}" | tee -a "${LOG_FILE}"
  set +e
  "${EMU}" +max-cycles="${MAX_CYCLES:-500000000}" "${QBIN}" | tee -a "${LOG_FILE}"
  RUN_RC=${PIPESTATUS[0]}
  set -e
  if [[ "${RUN_RC}" -ne 0 ]]; then
    RC="${RUN_RC}"
    break
  fi
done

END_SEC=$(date +%s)
echo "$((END_SEC - START_SEC))" > "${WALL_FILE}"
exit "${RC}"
