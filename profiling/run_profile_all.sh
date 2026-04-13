#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/results"
LOG_DIR="${RESULTS_DIR}/benchmark_runs/logs"
mkdir -p "${LOG_DIR}"

PROFILE_CORE="${PROFILE_CORE:-1}"
COUNTERS_FILE="${COUNTERS_FILE:-config/ctrs_frontend_mpki_gnr.txt}"
APP_WORKLOAD_FILE="${APP_WORKLOAD_FILE:-config/workloads_bench4_singlecore.txt}"
SPEC_WORKLOAD_FILE="${SPEC_WORKLOAD_FILE:-config/workloads_spec_singlecore.txt}"
APP_SAMPLE_INTERVAL="${APP_SAMPLE_INTERVAL:-1}"
APP_WARMUP_SAMPLES="${APP_WARMUP_SAMPLES:-60}"
SPEC_SAMPLE_INTERVAL="${SPEC_SAMPLE_INTERVAL:-0}"
RUN_SPEC_BUILD="${RUN_SPEC_BUILD:-1}"
SYNC_VENV="${SYNC_VENV:-1}"

cd "${SCRIPT_DIR}"

if [[ ! -x "${SCRIPT_DIR}/.venv/bin/python" || "${SYNC_VENV}" == "1" ]]; then
  "${SCRIPT_DIR}/setup_venv.sh"
fi
PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"

PCM_CORE_BIN="${PCM_CORE_BIN:-}"
if [[ -z "${PCM_CORE_BIN}" ]]; then
  LOCAL_PCM="${SCRIPT_DIR}/../benchmarks/tools/pcm-latest-src/pcm/build/bin/pcm-core"
  if [[ -x "${LOCAL_PCM}" ]]; then
    PCM_CORE_BIN="${LOCAL_PCM}"
  elif command -v pcm-core >/dev/null 2>&1; then
    PCM_CORE_BIN="$(command -v pcm-core)"
  fi
fi
if [[ -z "${PCM_CORE_BIN}" ]]; then
  echo "[err] pcm-core not found. Set PCM_CORE_BIN=/abs/path/to/pcm-core" >&2
  exit 1
fi

for f in \
  "${RESULTS_DIR}/tomcat_core.csv" \
  "${RESULTS_DIR}/finagle_http_core.csv" \
  "${RESULTS_DIR}/finagle_chirper_core.csv" \
  "${RESULTS_DIR}/verilator_qsort_core.csv" \
  "${RESULTS_DIR}/spec602_core.csv" \
  "${RESULTS_DIR}/spec605_core.csv" \
  "${RESULTS_DIR}/spec641_core.csv"; do
  if [[ -e "${f}" && ! -w "${f}" ]]; then
    echo "[err] output file is not writable: ${f}" >&2
    exit 1
  fi
done

rm -f \
  "${RESULTS_DIR}/tomcat_core.csv" \
  "${RESULTS_DIR}/finagle_http_core.csv" \
  "${RESULTS_DIR}/finagle_chirper_core.csv" \
  "${RESULTS_DIR}/verilator_qsort_core.csv" \
  "${RESULTS_DIR}/spec602_core.csv" \
  "${RESULTS_DIR}/spec605_core.csv" \
  "${RESULTS_DIR}/spec641_core.csv" \
  "${RESULTS_DIR}/bench4_singlecore_frontend_mpki.png" \
  "${RESULTS_DIR}/spec_frontend_mpki_per_bench.png" \
  "${RESULTS_DIR}/spec_frontend_mpki_avg.png" \
  "${RESULTS_DIR}/runtime_summary.csv" \
  "${RESULTS_DIR}/runtime_summary.txt"

if [[ "${RUN_SPEC_BUILD}" == "1" ]]; then
  echo "[inf] Building SPEC intspeed with all cores"
  ./runscript/build_spec_intspeed_allcores.sh 2>&1 | tee "${LOG_DIR}/spec_intspeed_build.log"
fi

echo "[inf] Running app benchmarks on core ${PROFILE_CORE}"
APP_PCM_ARGS=()
if [[ "${APP_SAMPLE_INTERVAL}" != "0" ]]; then
  APP_PCM_ARGS+=(-t "${APP_SAMPLE_INTERVAL}")
fi
PCM_CORE_BIN="${PCM_CORE_BIN}" "${PYTHON_BIN}" runscript/pcminvoke.py \
  -i "${COUNTERS_FILE}" \
  -c "${PROFILE_CORE}" \
  "${APP_PCM_ARGS[@]}" \
  -w "${APP_WORKLOAD_FILE}" \
  2>&1 | tee "${LOG_DIR}/pcminvoke_bench4_singlecore.log"

echo "[inf] Running SPEC benchmarks on core ${PROFILE_CORE}"
SPEC_PCM_ARGS=()
if [[ "${SPEC_SAMPLE_INTERVAL}" != "0" ]]; then
  SPEC_PCM_ARGS+=(-t "${SPEC_SAMPLE_INTERVAL}")
fi
PCM_CORE_BIN="${PCM_CORE_BIN}" "${PYTHON_BIN}" runscript/pcminvoke.py \
  -i "${COUNTERS_FILE}" \
  -c "${PROFILE_CORE}" \
  "${SPEC_PCM_ARGS[@]}" \
  -w "${SPEC_WORKLOAD_FILE}" \
  2>&1 | tee "${LOG_DIR}/pcminvoke_spec_singlecore.log"

echo "[inf] Generating MPKI plots"
PROFILE_CORE="${PROFILE_CORE}" MPKI_WARMUP_SAMPLES="${APP_WARMUP_SAMPLES}" \
  "${PYTHON_BIN}" runscript/pcmparse_bench4_singlecore.py 2>&1 | tee "${LOG_DIR}/plot_bench4_singlecore.log"
PROFILE_CORE="${PROFILE_CORE}" \
  "${PYTHON_BIN}" runscript/pcmparse_frontend_specavg.py 2>&1 | tee "${LOG_DIR}/plot_spec_singlecore.log"

echo "[inf] Summarizing runtimes"
"${PYTHON_BIN}" runscript/summarize_runtime_logs.py 2>&1 | tee "${LOG_DIR}/runtime_summary.log"

echo "[ok] Done"
