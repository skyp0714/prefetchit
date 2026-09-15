#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_ROOT="${SCRIPT_DIR}/results"
LOG_DIR="${RESULTS_ROOT}/logs"
BENCH_CSV_DIR="${RESULTS_ROOT}/benchmark_profiling/csv"
BENCH_PNG_DIR="${RESULTS_ROOT}/benchmark_profiling/png"
JVM_CSV_DIR="${RESULTS_ROOT}/jvm_context_switch/csv"
JVM_PNG_DIR="${RESULTS_ROOT}/jvm_context_switch/png"
mkdir -p "${LOG_DIR}"
mkdir -p "${BENCH_CSV_DIR}" "${BENCH_PNG_DIR}" "${JVM_CSV_DIR}" "${JVM_PNG_DIR}"
JVM_CORECMP_PNG="${JVM_PNG_DIR}/main_jvm_core0_cmp_l1i_l2.png"
MAIN_FRONTEND_CSV="${BENCH_CSV_DIR}/main_frontend_all.csv"

PROFILE_CORE="${PROFILE_CORE:-1}"
EVENTS_FILE="${EVENTS_FILE:-config/gnr_frontend_perf_events.txt}"
BENCHMARK_FILE="${BENCHMARK_FILE:-config/benchmarks.txt}"
RUN_SPEC_BUILD="${RUN_SPEC_BUILD:-1}"
SYNC_VENV="${SYNC_VENV:-1}"
PERF_BIN="${PERF_BIN:-perf}"
PERF_USER_ONLY="${PERF_USER_ONLY:-1}"
APP_WARMUP_DROP_INFO="${APP_WARMUP_DROP_INFO:-PERF_DELAY_MS in benchmark file}"
CTX_CORE_SMALL="${CTX_CORE_SMALL:-1}"
CTX_CORE_LARGE="${CTX_CORE_LARGE:-86}"
CLEAN_RESULTS="${CLEAN_RESULTS:-0}"
RESUME_RESULTS="${RESUME_RESULTS:-1}"
CLEAN_SPLIT_ARTIFACTS="${CLEAN_SPLIT_ARTIFACTS:-1}"

cd "${SCRIPT_DIR}"

cleanup_orphans() {
  "${SCRIPT_DIR}/runscript/bench/cleanup_benchmark_orphans.sh" 1 >/dev/null 2>&1 || true
}
trap cleanup_orphans EXIT INT TERM

echo "[inf] Pre-run orphan cleanup"
"${SCRIPT_DIR}/runscript/bench/cleanup_benchmark_orphans.sh" 1 >/dev/null 2>&1 || true

if [[ ! -x "${SCRIPT_DIR}/.venv/bin/python" || "${SYNC_VENV}" == "1" ]]; then
  "${SCRIPT_DIR}/setup_venv.sh"
fi
PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"

if [[ "$(id -u)" -ne 0 ]]; then
  PARANOID="$(cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null || echo 4)"
  if [[ "${PARANOID}" -gt 1 ]]; then
    echo "[err] perf_event_paranoid=${PARANOID}. Run this script as root (sudo)." >&2
    exit 1
  fi
fi

if [[ "${CLEAN_RESULTS}" == "1" ]]; then
  rm -f \
    "${BENCH_CSV_DIR}/"*.csv \
    "${BENCH_CSV_DIR}/"*.perfraw \
    "${BENCH_PNG_DIR}/"*.png \
    "${JVM_CSV_DIR}/"*.csv \
    "${JVM_PNG_DIR}/"*.png \
    "${JVM_CORECMP_PNG}" \
    "${MAIN_FRONTEND_CSV}" \
    "${BENCH_CSV_DIR}/runtime_summary.csv" \
    "${BENCH_CSV_DIR}/runtime_summary.txt"
fi

if [[ "${RESUME_RESULTS}" == "1" ]]; then
  PERFINVOKE_RESUME_ARG="--resume"
else
  PERFINVOKE_RESUME_ARG="--no-resume"
fi

if [[ "${RUN_SPEC_BUILD}" == "1" ]]; then
  echo "[inf] Building SPEC intspeed with all cores"
  ./runscript/build/build_spec_intspeed_allcores.sh 2>&1 | tee "${LOG_DIR}/spec_intspeed_build.log"
fi

echo "[inf] Perf dummy check (iTLB walk / sTLB hit support)"
PROFILE_CORE="${PROFILE_CORE}" PERF_BIN="${PERF_BIN}" \
  ./runscript/build/perf_dummy_check.sh

echo "[inf] Running benchmarks on core ${PROFILE_CORE} (${APP_WARMUP_DROP_INFO}), perf_scope=$([[ "${PERF_USER_ONLY}" == "1" ]] && echo user-only || echo user+kernel)"
has_verilator=0
if command -v rg >/dev/null 2>&1; then
  if rg -q "run_verilator_qsort\\.sh" "${BENCHMARK_FILE}"; then
    has_verilator=1
  fi
else
  if grep -q "run_verilator_qsort\\.sh" "${BENCHMARK_FILE}"; then
    has_verilator=1
  fi
fi
if [[ "${has_verilator}" == "1" ]] && [[ -z "${CHIPYARD_CONFIG:-}" ]]; then
  echo "[err] APP workload includes Verilator, but CHIPYARD_CONFIG is not set." >&2
  echo "[err] Export CHIPYARD_CONFIG=<large multicore BOOM config> first." >&2
  exit 1
fi
PERF_BIN="${PERF_BIN}" PERF_USER_ONLY="${PERF_USER_ONLY}" "${PYTHON_BIN}" runscript/bench/perfinvoke.py \
  -i "${EVENTS_FILE}" \
  -c "${PROFILE_CORE}" \
  -w "${BENCHMARK_FILE}" \
  "${PERFINVOKE_RESUME_ARG}" \
  2>&1 | tee "${LOG_DIR}/perfinvoke_benchmarks.log"

echo "[inf] Building single main CSV (${MAIN_FRONTEND_CSV})"
"${PYTHON_BIN}" runscript/build/build_main_frontend_csv.py \
  --results-dir "${RESULTS_ROOT}" \
  --output "${MAIN_FRONTEND_CSV}" \
  2>&1 | tee "${LOG_DIR}/build_main_frontend_csv.log"

echo "[inf] Generating frontend variant plots from ${MAIN_FRONTEND_CSV}"
"${PYTHON_BIN}" runscript/plot/plot_frontend_jvm_core_variants.py \
  --input "${MAIN_FRONTEND_CSV}" \
  --results-dir "${BENCH_PNG_DIR}" \
  2>&1 | tee "${LOG_DIR}/plot_frontend_variants.log"

echo "[inf] Generating JVM core0 MPKI comparison (${CTX_CORE_SMALL} core vs ${CTX_CORE_LARGE} cores)"
CORE_SMALL="${CTX_CORE_SMALL}" \
CORE_LARGE="${CTX_CORE_LARGE}" \
MAIN_CSV="${MAIN_FRONTEND_CSV}" \
OUT_PNG="${JVM_CORECMP_PNG}" \
./run_jvm_profiling.sh \
  2>&1 | tee "${LOG_DIR}/plot_jvm_core0_cmp.log"

echo "[inf] Summarizing runtimes"
"${PYTHON_BIN}" runscript/build/summarize_runtime_logs.py \
  2>&1 | tee "${LOG_DIR}/runtime_summary.log"

if [[ "${CLEAN_SPLIT_ARTIFACTS}" == "1" ]]; then
  echo "[inf] Cleaning split benchmark artifacts (keeping unified CSV/plots)"
  rm -f \
    "${BENCH_CSV_DIR}/tomcat_core.csv" \
    "${BENCH_CSV_DIR}/finagle_http_core.csv" \
    "${BENCH_CSV_DIR}/finagle_chirper_core.csv" \
    "${BENCH_CSV_DIR}/verilator_qsort_core.csv" \
    "${BENCH_CSV_DIR}/spec602_core.csv" \
    "${BENCH_CSV_DIR}/spec605_core.csv" \
    "${BENCH_CSV_DIR}/spec641_core.csv" \
    "${BENCH_CSV_DIR}/tomcat_core.perfraw" \
    "${BENCH_CSV_DIR}/finagle_http_core.perfraw" \
    "${BENCH_CSV_DIR}/finagle_chirper_core.perfraw" \
    "${BENCH_CSV_DIR}/verilator_qsort_core.perfraw" \
    "${BENCH_CSV_DIR}/spec602_core.perfraw" \
    "${BENCH_CSV_DIR}/spec605_core.perfraw" \
    "${BENCH_CSV_DIR}/spec641_core.perfraw"
fi

echo "[ok] Done"
