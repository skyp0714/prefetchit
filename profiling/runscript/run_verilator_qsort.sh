#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/bench_common.sh"

setup_verilator_env

CHIPYARD_CONFIG="${CHIPYARD_CONFIG:-}"
CHIPYARD_CONFIG_PACKAGE="${CHIPYARD_CONFIG_PACKAGE:-chipyard}"
QBIN="${QBIN:-${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv}"
LOG_FILE="${LOG_ROOT}/verilator-qsort.log"
WALL_FILE="${LOG_ROOT}/verilator-qsort.wall_seconds"
VERILATOR_TIMEOUT_SECS="${VERILATOR_TIMEOUT_SECS:-180}"

if [[ -z "${CHIPYARD_CONFIG}" ]]; then
  echo "[err] CHIPYARD_CONFIG is required." >&2
  echo "[err] Set it to a Chipyard large multi-core BOOM config class." >&2
  exit 1
fi

if [[ "${FORCE_REBUILD:-0}" == "1" ]]; then
  echo "[err] FORCE_REBUILD=1 is not allowed in measured runs (compile phase would be included)." >&2
  echo "[err] Run ./runscript/build_verilator_qsort.sh separately before profiling." >&2
  exit 1
fi

require_chipyard_tree
if [[ "${SKIP_BOOM_CONFIG_CHECK:-0}" != "1" ]]; then
  validate_boom_multicore_config "${CHIPYARD_CONFIG}"
fi
EMU="$(resolve_chipyard_simulator "${CHIPYARD_CONFIG}" "${CHIPYARD_CONFIG_PACKAGE}" || true)"
if [[ -z "${EMU}" ]]; then
  echo "[err] simulator binary not found for config=${CHIPYARD_CONFIG}" >&2
  echo "[err] build first: CHIPYARD_CONFIG=${CHIPYARD_CONFIG} ./runscript/build_verilator_qsort.sh" >&2
  exit 1
fi

require_file "${EMU}"
require_file "${QBIN}"

START_SEC=$(date +%s)
: > "${LOG_FILE}"
RC=0
REPEAT_COUNT="${REPEAT_COUNT:-1}"
ALLOW_EARLY_STOP_OK="${ALLOW_EARLY_STOP_OK:-1}"
for i in $(seq 1 "${REPEAT_COUNT}"); do
  echo "[run] qsort repeat ${i}/${REPEAT_COUNT}" | tee -a "${LOG_FILE}"
  CMD=("${EMU}" "${QBIN}")

  # Chipyard simulator expects the program binary before plusargs.
  if [[ -n "${MAX_CYCLES:-}" ]]; then
    CMD+=("+max-cycles=${MAX_CYCLES}")
  elif [[ -n "${MAX_CORE_CYCLES:-}" ]]; then
    # Backward-compatible alias from older flow.
    CMD+=("+max-cycles=${MAX_CORE_CYCLES}")
  fi

  set +e
  timeout "${VERILATOR_TIMEOUT_SECS}" "${CMD[@]}" 2>&1 | tee -a "${LOG_FILE}"
  RUN_RC=${PIPESTATUS[0]}
  set -e
  if [[ "${RUN_RC}" -ne 0 ]]; then
    if [[ "${ALLOW_EARLY_STOP_OK}" == "1" ]] && \
      ([[ "${RUN_RC}" -eq 124 ]] || \
       grep -Eq "PlusArgTimeout|Assertion failed .*PlusArgTimeout|\\*\\*\\* FAILED \\*\\*\\*.*\\(timeout\\)" "${LOG_FILE}"); then
      echo "[inf] expected early stop detected (rc=${RUN_RC}); accepting run for fixed-time profiling" | tee -a "${LOG_FILE}"
      RC=0
      break
    else
      RC="${RUN_RC}"
      break
    fi
  fi
done

END_SEC=$(date +%s)
echo "$((END_SEC - START_SEC))" > "${WALL_FILE}"
exit "${RC}"
