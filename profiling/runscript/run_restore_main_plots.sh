#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${PROFILING_DIR}/results"
LOG_DIR="${RESULTS_DIR}/benchmark_runs/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/restore_main_plots_$(date +%Y%m%d_%H%M%S).log"

PYTHON_BIN="${PROFILING_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

cd "${PROFILING_DIR}"
echo "[start] $(date)" | tee -a "${LOG_FILE}"

echo "[stage] rerun only missing workloads listed in config/workloads_main_missing.txt" | tee -a "${LOG_FILE}"
"${PYTHON_BIN}" runscript/perfinvoke.py \
  -i config/perf_events_frontend_mpki_gnr.txt \
  -c 1 \
  -w config/workloads_main_missing.txt \
  --no-resume 2>&1 | tee -a "${LOG_FILE}"

echo "[stage] rebuild main CSV" | tee -a "${LOG_FILE}"
"${PYTHON_BIN}" runscript/build_main_frontend_csv.py \
  --results-dir "${RESULTS_DIR}" \
  --output "${RESULTS_DIR}/main_frontend_all.csv" 2>&1 | tee -a "${LOG_FILE}"

echo "[stage] regenerate frontend plots" | tee -a "${LOG_FILE}"
"${PYTHON_BIN}" runscript/plot_frontend_jvm_core_variants.py \
  --input "${RESULTS_DIR}/main_frontend_all.csv" \
  --results-dir "${RESULTS_DIR}" 2>&1 | tee -a "${LOG_FILE}"

echo "[stage] regenerate JVM core0 comparison plot" | tee -a "${LOG_FILE}"
CORE_SMALL="${CORE_SMALL:-1}" CORE_LARGE="${CORE_LARGE:-86}" \
MAIN_CSV="${RESULTS_DIR}/main_frontend_all.csv" \
OUT_PNG="${RESULTS_DIR}/main_jvm_core0_cmp_l1i_l2.png" \
./runscript/run_ctxswitch_core0_mpki.sh 2>&1 | tee -a "${LOG_FILE}"

echo "[done] $(date)" | tee -a "${LOG_FILE}"
echo "[log] ${LOG_FILE}" | tee -a "${LOG_FILE}"
