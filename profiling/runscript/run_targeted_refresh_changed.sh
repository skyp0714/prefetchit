#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${PROFILING_DIR}/results"
LOG_DIR="${RESULTS_DIR}/benchmark_runs/logs"
PYTHON_BIN="${PROFILING_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

mkdir -p "${LOG_DIR}"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
RUN_LOG="${LOG_DIR}/targeted_refresh_changed_${RUN_TS}.log"

THREAD_CSV="${RESULTS_DIR}/contextswitch_thread_scaling.csv"
THREAD_BENCHMARKS="${THREAD_BENCHMARKS:-tomcat}"
THREAD_CORE_COUNTS="${THREAD_CORE_COUNTS:-1 2 4 8 16 32 64 86}"

cd "${PROFILING_DIR}"

echo "[start] $(date)" | tee -a "${RUN_LOG}"

echo "[stage] drop requested rows from ${THREAD_CSV}" | tee -a "${RUN_LOG}"
if [[ -f "${THREAD_CSV}" ]]; then
  tmp="${THREAD_CSV}.tmp"
  cp "${THREAD_CSV}" "${tmp}"
  for b in ${THREAD_BENCHMARKS}; do
    for c in ${THREAD_CORE_COUNTS}; do
      awk -F, -v bench="${b}" -v core="${c}" 'NR==1 || !($1==bench && $2==core)' "${tmp}" > "${tmp}.next"
      mv "${tmp}.next" "${tmp}"
    done
  done
  mv "${tmp}" "${THREAD_CSV}"
fi

echo "[stage] rerun targeted thread-scaling rows (1-minute window)" | tee -a "${RUN_LOG}"
BENCHMARKS="${THREAD_BENCHMARKS}" \
CORE_COUNTS="${THREAD_CORE_COUNTS}" \
MEASURE_SECS="${MEASURE_SECS:-60}" \
SAMPLE_INTERVAL_SECS="${SAMPLE_INTERVAL_SECS:-1}" \
RESUME_CSV=1 \
"${SCRIPT_DIR}/run_ctxswitch_thread_scaling.sh" 2>&1 | tee -a "${RUN_LOG}"

echo "[stage] rebuild main CSV + regenerate main plots" | tee -a "${RUN_LOG}"
"${PYTHON_BIN}" "${SCRIPT_DIR}/build_main_frontend_csv.py" \
  --results-dir "${RESULTS_DIR}" \
  --output "${RESULTS_DIR}/main_frontend_all.csv" 2>&1 | tee -a "${RUN_LOG}"

"${PYTHON_BIN}" "${SCRIPT_DIR}/plot_frontend_jvm_core_variants.py" \
  --input "${RESULTS_DIR}/main_frontend_all.csv" \
  --results-dir "${RESULTS_DIR}" 2>&1 | tee -a "${RUN_LOG}"

CORE_SMALL="${CORE_SMALL:-1}" CORE_LARGE="${CORE_LARGE:-86}" \
MAIN_CSV="${RESULTS_DIR}/main_frontend_all.csv" \
OUT_PNG="${RESULTS_DIR}/main_jvm_core0_cmp_l1i_l2.png" \
"${SCRIPT_DIR}/run_ctxswitch_core0_mpki.sh" 2>&1 | tee -a "${RUN_LOG}"

echo "[done] $(date)" | tee -a "${RUN_LOG}"
echo "[log] ${RUN_LOG}"
