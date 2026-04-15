#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/results"
LOG_DIR="${RESULTS_DIR}/benchmark_runs/logs"
mkdir -p "${LOG_DIR}"
JVM_CORECMP_PNG="${RESULTS_DIR}/main_jvm_core0_cmp_l1i_l2.png"
MAIN_FRONTEND_CSV="${RESULTS_DIR}/main_frontend_all.csv"

PROFILE_CORE="${PROFILE_CORE:-1}"
EVENTS_FILE="${EVENTS_FILE:-config/perf_events_frontend_mpki_gnr.txt}"
APP_WORKLOAD_FILE="${APP_WORKLOAD_FILE:-config/workloads_bench4_singlecore.txt}"
SPEC_WORKLOAD_FILE="${SPEC_WORKLOAD_FILE:-config/workloads_spec_singlecore.txt}"
RUN_SPEC_BUILD="${RUN_SPEC_BUILD:-1}"
SYNC_VENV="${SYNC_VENV:-1}"
PERF_BIN="${PERF_BIN:-perf}"
PERF_USER_ONLY="${PERF_USER_ONLY:-1}"
APP_WARMUP_DROP_INFO="${APP_WARMUP_DROP_INFO:-PERF_DELAY_MS in workload file}"
CTX_CORE_SMALL="${CTX_CORE_SMALL:-1}"
CTX_CORE_LARGE="${CTX_CORE_LARGE:-86}"
CLEAN_RESULTS="${CLEAN_RESULTS:-0}"
RESUME_RESULTS="${RESUME_RESULTS:-1}"
CLEAN_SPLIT_ARTIFACTS="${CLEAN_SPLIT_ARTIFACTS:-1}"

cd "${SCRIPT_DIR}"

cleanup_orphans() {
  "${SCRIPT_DIR}/runscript/cleanup_benchmark_orphans.sh" 1 >/dev/null 2>&1 || true
}
trap cleanup_orphans EXIT INT TERM

echo "[inf] Pre-run orphan cleanup"
"${SCRIPT_DIR}/runscript/cleanup_benchmark_orphans.sh" 1 >/dev/null 2>&1 || true

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
    "${RESULTS_DIR}/bench4_singlecore_frontend_mpki.png" \
    "${RESULTS_DIR}/spec_frontend_mpki_avg.png" \
    "${RESULTS_DIR}/spec_frontend_mpki_per_bench.png" \
    "${RESULTS_DIR}/tomcat_core.csv" \
    "${RESULTS_DIR}/finagle_http_core.csv" \
    "${RESULTS_DIR}/finagle_chirper_core.csv" \
    "${RESULTS_DIR}/verilator_qsort_core.csv" \
    "${RESULTS_DIR}/spec602_core.csv" \
    "${RESULTS_DIR}/spec605_core.csv" \
    "${RESULTS_DIR}/spec641_core.csv" \
    "${RESULTS_DIR}/"*.perfraw \
    "${RESULTS_DIR}/frontend_l1i_l2_mpki.png" \
    "${RESULTS_DIR}/frontend_itlb_stlb_mpki.png" \
    "${RESULTS_DIR}/frontend_l1i_l2_mpki_jvm1c.png" \
    "${RESULTS_DIR}/frontend_itlb_stlb_mpki_jvm1c.png" \
    "${RESULTS_DIR}/frontend_l1i_l2_mpki_jvm86c.png" \
    "${RESULTS_DIR}/frontend_itlb_stlb_mpki_jvm86c.png" \
    "${RESULTS_DIR}/main_jvm_core0_1v128_l1i_l2.png" \
    "${JVM_CORECMP_PNG}" \
    "${MAIN_FRONTEND_CSV}" \
    "${RESULTS_DIR}/runtime_summary.csv" \
    "${RESULTS_DIR}/runtime_summary.txt"
fi

if [[ "${RESUME_RESULTS}" == "1" ]]; then
  PERFINVOKE_RESUME_ARG="--resume"
else
  PERFINVOKE_RESUME_ARG="--no-resume"
fi

if [[ "${RUN_SPEC_BUILD}" == "1" ]]; then
  echo "[inf] Building SPEC intspeed with all cores"
  ./runscript/build_spec_intspeed_allcores.sh 2>&1 | tee "${LOG_DIR}/spec_intspeed_build.log"
fi

echo "[inf] Perf dummy check (iTLB walk / sTLB hit support)"
PROFILE_CORE="${PROFILE_CORE}" PERF_BIN="${PERF_BIN}" \
  ./runscript/perf_dummy_check.sh

echo "[inf] Running app benchmarks on core ${PROFILE_CORE} (${APP_WARMUP_DROP_INFO}), perf_scope=$([[ "${PERF_USER_ONLY}" == "1" ]] && echo user-only || echo user+kernel)"
has_verilator=0
if command -v rg >/dev/null 2>&1; then
  if rg -q "run_verilator_qsort\\.sh" "${APP_WORKLOAD_FILE}"; then
    has_verilator=1
  fi
else
  if grep -q "run_verilator_qsort\\.sh" "${APP_WORKLOAD_FILE}"; then
    has_verilator=1
  fi
fi
if [[ "${has_verilator}" == "1" ]] && [[ -z "${CHIPYARD_CONFIG:-}" ]]; then
  echo "[err] APP workload includes Verilator, but CHIPYARD_CONFIG is not set." >&2
  echo "[err] Export CHIPYARD_CONFIG=<large multicore BOOM config> first." >&2
  exit 1
fi
PERF_BIN="${PERF_BIN}" PERF_USER_ONLY="${PERF_USER_ONLY}" "${PYTHON_BIN}" runscript/perfinvoke.py \
  -i "${EVENTS_FILE}" \
  -c "${PROFILE_CORE}" \
  -w "${APP_WORKLOAD_FILE}" \
  "${PERFINVOKE_RESUME_ARG}" \
  2>&1 | tee "${LOG_DIR}/perfinvoke_bench4_singlecore.log"

echo "[inf] Running SPEC benchmarks on core ${PROFILE_CORE}, perf_scope=$([[ "${PERF_USER_ONLY}" == "1" ]] && echo user-only || echo user+kernel)"
PERF_BIN="${PERF_BIN}" PERF_USER_ONLY="${PERF_USER_ONLY}" "${PYTHON_BIN}" runscript/perfinvoke.py \
  -i "${EVENTS_FILE}" \
  -c "${PROFILE_CORE}" \
  -w "${SPEC_WORKLOAD_FILE}" \
  "${PERFINVOKE_RESUME_ARG}" \
  2>&1 | tee "${LOG_DIR}/perfinvoke_spec_singlecore.log"

echo "[inf] Building single main CSV (${MAIN_FRONTEND_CSV})"
"${PYTHON_BIN}" runscript/build_main_frontend_csv.py \
  --results-dir "${RESULTS_DIR}" \
  --output "${MAIN_FRONTEND_CSV}" \
  2>&1 | tee "${LOG_DIR}/build_main_frontend_csv.log"

echo "[inf] Generating frontend variant plots from ${MAIN_FRONTEND_CSV}"
"${PYTHON_BIN}" runscript/plot_frontend_jvm_core_variants.py \
  --input "${MAIN_FRONTEND_CSV}" \
  --results-dir "${RESULTS_DIR}" \
  2>&1 | tee "${LOG_DIR}/plot_frontend_variants.log"

echo "[inf] Generating JVM core0 MPKI comparison (${CTX_CORE_SMALL} core vs ${CTX_CORE_LARGE} cores)"
CORE_SMALL="${CTX_CORE_SMALL}" \
CORE_LARGE="${CTX_CORE_LARGE}" \
MAIN_CSV="${MAIN_FRONTEND_CSV}" \
OUT_PNG="${JVM_CORECMP_PNG}" \
./runscript/run_ctxswitch_core0_mpki.sh \
  2>&1 | tee "${LOG_DIR}/plot_jvm_core0_cmp.log"

echo "[inf] Summarizing runtimes"
"${PYTHON_BIN}" runscript/summarize_runtime_logs.py \
  2>&1 | tee "${LOG_DIR}/runtime_summary.log"

if [[ "${CLEAN_SPLIT_ARTIFACTS}" == "1" ]]; then
  echo "[inf] Cleaning split benchmark artifacts (keeping unified CSV/plots)"
  rm -f \
    "${RESULTS_DIR}/tomcat_core.csv" \
    "${RESULTS_DIR}/finagle_http_core.csv" \
    "${RESULTS_DIR}/finagle_chirper_core.csv" \
    "${RESULTS_DIR}/verilator_qsort_core.csv" \
    "${RESULTS_DIR}/spec602_core.csv" \
    "${RESULTS_DIR}/spec605_core.csv" \
    "${RESULTS_DIR}/spec641_core.csv" \
    "${RESULTS_DIR}/tomcat_core.perfraw" \
    "${RESULTS_DIR}/finagle_http_core.perfraw" \
    "${RESULTS_DIR}/finagle_chirper_core.perfraw" \
    "${RESULTS_DIR}/verilator_qsort_core.perfraw" \
    "${RESULTS_DIR}/spec602_core.perfraw" \
    "${RESULTS_DIR}/spec605_core.perfraw" \
    "${RESULTS_DIR}/spec641_core.perfraw"
fi

echo "[ok] Done"
