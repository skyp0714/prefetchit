#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/runscript/bench/bench_common.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="${SCRIPT_DIR}"
PYTHON_BIN="${PROFILING_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

WORKLOAD="${WORKLOAD:-verilator-qsort}"
WORKLOAD_BIN="${WORKLOAD_BIN:-}"
WORKLOAD_NAME="${WORKLOAD_NAME:-}"
ITERATIONS="${ITERATIONS:-3}"
CHIPYARD_CONFIG="${CHIPYARD_CONFIG:-DualMegaBoomAndSingleRocketConfig}"
CHIPYARD_CONFIG_PACKAGE="${CHIPYARD_CONFIG_PACKAGE:-chipyard}"
SIM_BINARY="${SIM_BINARY:-}"
MAX_CYCLES="${MAX_CYCLES:-80000}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PERF_SCOPE="${PERF_SCOPE:-task}"
PERF_BIN="${PERF_BIN:-perf}"
EVENT_FILE="${EVENT_FILE:-${PROFILING_DIR}/config/gnr_frontend_perf_events.txt}"
RESULTS_BASE="${RESULTS_BASE:-${PROFILING_DIR}/results/detailed_profile}"
QBIN="${QBIN:-${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv}"
MBIN="${MBIN:-${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/mm.riscv}"

LATENCY_EVENT_ALIASES=(
  "frontend_retired_latency_ge_2"
  "frontend_retired_latency_ge_4"
  "frontend_retired_latency_ge_8"
  "frontend_retired_latency_ge_16"
  "frontend_retired_latency_ge_32"
  "frontend_retired_latency_ge_64"
  "frontend_retired_latency_ge_128"
)

# Granite Rapids FRONTEND_RETIRED.LATENCY_GE_* events exposed via raw PMU fields.
# Using explicit config1 keeps this script working even when perf aliases are missing.
LATENCY_EVENT_SPECS=(
  "cpu/event=0xc6,umask=0x3,config1=0x600206,name=frontend_retired_latency_ge_2/u"
  "cpu/event=0xc6,umask=0x3,config1=0x600406,name=frontend_retired_latency_ge_4/u"
  "cpu/event=0xc6,umask=0x3,config1=0x600806,name=frontend_retired_latency_ge_8/u"
  "cpu/event=0xc6,umask=0x3,config1=0x601006,name=frontend_retired_latency_ge_16/u"
  "cpu/event=0xc6,umask=0x3,config1=0x602006,name=frontend_retired_latency_ge_32/u"
  "cpu/event=0xc6,umask=0x3,config1=0x604006,name=frontend_retired_latency_ge_64/u"
  "cpu/event=0xc6,umask=0x3,config1=0x608006,name=frontend_retired_latency_ge_128/u"
)

usage() {
  cat <<'EOF'
Usage: ./run_detailed_profile.sh [options]

Options:
  --workload <name>              Workload name: verilator-qsort | verilator-mm | verilator-custom
                                 default: verilator-qsort
  --workload-bin <path>          Custom workload binary path (required for verilator-custom)
  --workload-name <name>         Result directory name override
  --iterations <N>               Number of iterations (default: 3)
  --chipyard-config <Config>     Chipyard config class name
                                 default: DualMegaBoomAndSingleRocketConfig
  --chipyard-config-package <P>  Config package for simulator resolution
                                 default: chipyard
  --sim-binary <path>            Simulator binary override
                                 default: auto-resolve from chipyard config
  --max-cycles <N>               +max-cycles for verilator workload
                                 default: 80000
  --profile-core <N>             Core to pin workload/perf to
                                 default: 0
  --perf-scope <task|cpu>        task: count only the workload process tree;
                                 cpu: system-wide user events on --profile-core
                                 default: task
  --event-file <path>            Frontend MPKI event file
                                 default: profiling/config/gnr_frontend_perf_events.txt
  --results-base <path>          Results base directory
                                 default: profiling/results/detailed_profile
  --qbin <path>                  qsort binary path (for verilator-qsort)
  --mbin <path>                  mm binary path (for verilator-mm)
  --perf-bin <path>              perf binary path
                                 default: perf
  -h, --help                     Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workload)
      WORKLOAD="${2:-}"
      shift 2
      ;;
    --iterations)
      ITERATIONS="${2:-}"
      shift 2
      ;;
    --workload-bin)
      WORKLOAD_BIN="${2:-}"
      shift 2
      ;;
    --workload-name)
      WORKLOAD_NAME="${2:-}"
      shift 2
      ;;
    --chipyard-config)
      CHIPYARD_CONFIG="${2:-}"
      shift 2
      ;;
    --chipyard-config-package)
      CHIPYARD_CONFIG_PACKAGE="${2:-}"
      shift 2
      ;;
    --sim-binary)
      SIM_BINARY="${2:-}"
      shift 2
      ;;
    --max-cycles)
      MAX_CYCLES="${2:-}"
      shift 2
      ;;
    --profile-core)
      PROFILE_CORE="${2:-}"
      shift 2
      ;;
    --perf-scope)
      PERF_SCOPE="${2:-}"
      shift 2
      ;;
    --event-file)
      EVENT_FILE="${2:-}"
      shift 2
      ;;
    --results-base)
      RESULTS_BASE="${2:-}"
      shift 2
      ;;
    --qbin)
      QBIN="${2:-}"
      shift 2
      ;;
    --mbin)
      MBIN="${2:-}"
      shift 2
      ;;
    --perf-bin)
      PERF_BIN="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[err] unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! [[ "${ITERATIONS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --iterations must be a positive integer." >&2
  exit 1
fi
if ! [[ "${MAX_CYCLES}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --max-cycles must be a positive integer." >&2
  exit 1
fi
if ! [[ "${PROFILE_CORE}" =~ ^[0-9]+$ ]]; then
  echo "[err] --profile-core must be a non-negative integer." >&2
  exit 1
fi
if [[ "${PERF_SCOPE}" != "task" && "${PERF_SCOPE}" != "cpu" ]]; then
  echo "[err] --perf-scope must be task or cpu." >&2
  exit 1
fi

setup_verilator_env
require_chipyard_tree
require_file "${EVENT_FILE}"

event0_alias="$(awk -F'|' '/^[^#].+\|/{print $1; exit}' "${EVENT_FILE}")"
event0_spec="$(awk -F'|' '/^[^#].+\|/{print $2; exit}' "${EVENT_FILE}")"
event1_alias="$(awk -F'|' '/^[^#].+\|/{n++; if(n==2){print $1; exit}}' "${EVENT_FILE}")"
event1_spec="$(awk -F'|' '/^[^#].+\|/{n++; if(n==2){print $2; exit}}' "${EVENT_FILE}")"
event2_alias="$(awk -F'|' '/^[^#].+\|/{n++; if(n==3){print $1; exit}}' "${EVENT_FILE}")"
event2_spec="$(awk -F'|' '/^[^#].+\|/{n++; if(n==3){print $2; exit}}' "${EVENT_FILE}")"
event3_alias="$(awk -F'|' '/^[^#].+\|/{n++; if(n==4){print $1; exit}}' "${EVENT_FILE}")"
event3_spec="$(awk -F'|' '/^[^#].+\|/{n++; if(n==4){print $2; exit}}' "${EVENT_FILE}")"
if [[ -z "${event0_alias}" || -z "${event0_spec}" || -z "${event1_alias}" || -z "${event1_spec}" || -z "${event2_alias}" || -z "${event2_spec}" || -z "${event3_alias}" || -z "${event3_spec}" ]]; then
  echo "[err] failed to parse first 4 events from ${EVENT_FILE}" >&2
  exit 1
fi

if [[ -n "${SIM_BINARY}" ]]; then
  EMU="${SIM_BINARY}"
else
  EMU="$(resolve_chipyard_simulator "${CHIPYARD_CONFIG}" "${CHIPYARD_CONFIG_PACKAGE}" || true)"
  if [[ -z "${EMU}" ]]; then
    echo "[err] simulator binary not found for config=${CHIPYARD_CONFIG}" >&2
    echo "[err] Build first (without clean):" >&2
    echo "[err]   make CONFIG=${CHIPYARD_CONFIG} CC=clang-18 CXX=clang++-18 LINK=clang++-18 EXTRA_SIM_CXXFLAGS='-g -fno-omit-frame-pointer -std=c++20 -Wno-c++11-narrowing' -j\$(nproc)" >&2
    exit 1
  fi
fi
require_file "${EMU}"

case "${WORKLOAD}" in
  verilator-qsort)
    WORKLOAD_BIN="${QBIN}"
    require_file "${WORKLOAD_BIN}"
    ;;
  verilator-mm)
    WORKLOAD_BIN="${MBIN}"
    require_file "${WORKLOAD_BIN}"
    ;;
  verilator-custom)
    if [[ -z "${WORKLOAD_BIN}" ]]; then
      echo "[err] --workload-bin is required for verilator-custom" >&2
      exit 1
    fi
    require_file "${WORKLOAD_BIN}"
    ;;
  *)
    echo "[err] unsupported workload: ${WORKLOAD}" >&2
    echo "[err] supported: verilator-qsort, verilator-mm, verilator-custom" >&2
    exit 1
    ;;
esac

if [[ -z "${WORKLOAD_NAME}" ]]; then
  if [[ "${WORKLOAD}" == "verilator-custom" ]]; then
    base="$(basename "${WORKLOAD_BIN}")"
    WORKLOAD_NAME="verilator-${base%.riscv}"
  else
    WORKLOAD_NAME="${WORKLOAD}"
  fi
fi

OUT_DIR="${RESULTS_BASE}/${WORKLOAD_NAME}"
RAW_DIR="${OUT_DIR}/raw"
mkdir -p "${RAW_DIR}"
MANIFEST_CSV="${OUT_DIR}/run_manifest.csv"
PER_ITER_CSV="${OUT_DIR}/per_iteration.csv"
SUMMARY_CSV="${OUT_DIR}/summary.csv"
LATENCY_CSV="${OUT_DIR}/latency_distribution.csv"
LATENCY_PNG="${OUT_DIR}/latency_distribution.png"
TABLE_MD="${OUT_DIR}/mpki_runtime_table.md"

ALL_EVENTS=("${event0_spec}" "${event1_spec}" "${event2_spec}" "${event3_spec}")
ALL_EVENTS+=("${LATENCY_EVENT_SPECS[@]}")
ALL_EVENTS+=("instructions")
EVENT_SPEC_CSV="$(IFS=,; echo "${ALL_EVENTS[*]}")"
LAT_EVENT_CSV="$(IFS=,; echo "${LATENCY_EVENT_ALIASES[*]}")"

event_check_stderr="${RAW_DIR}/perf_event_check.stderr"
set +e
"${PERF_BIN}" stat --no-big-num -x, --all-user -e "${EVENT_SPEC_CSV}" -- true >/dev/null 2>"${event_check_stderr}"
check_rc=$?
set -e
if [[ "${check_rc}" -ne 0 ]]; then
  echo "[err] perf event check failed. Please verify event names/support on this machine." >&2
  echo "[err] If perf_event_paranoid is high, run this script with sudo." >&2
  echo "[err] perf stderr:" >&2
  sed -n '1,80p' "${event_check_stderr}" >&2
  exit 1
fi

echo "iteration,perfraw,workload_log,elapsed_sec,return_code,run_status" > "${MANIFEST_CSV}"

echo "[inf] workload=${WORKLOAD} iterations=${ITERATIONS} core=${PROFILE_CORE} max_cycles=${MAX_CYCLES}"
echo "[inf] perf_scope=${PERF_SCOPE}"
echo "[inf] simulator=${EMU}"
echo "[inf] results_dir=${OUT_DIR}"

for iter in $(seq 1 "${ITERATIONS}"); do
  perfraw="${RAW_DIR}/iter$(printf '%03d' "${iter}").perfraw"
  runlog="${RAW_DIR}/iter$(printf '%03d' "${iter}").workload.log"
  workload_cmd="$(printf '%q %q +max-cycles=%q' "${EMU}" "${WORKLOAD_BIN}" "${MAX_CYCLES}")"

  echo "[run] iteration ${iter}/${ITERATIONS}"
  start_ns="$(date +%s%N)"
  perf_scope_args=()
  if [[ "${PERF_SCOPE}" == "cpu" ]]; then
    perf_scope_args=(-C "${PROFILE_CORE}")
  fi
  set +e
  "${PERF_BIN}" stat --no-big-num -x, --all-user "${perf_scope_args[@]}" -o "${perfraw}" \
    -e "${EVENT_SPEC_CSV}" -- \
    taskset -c "${PROFILE_CORE}" bash -lc "${workload_cmd}" > "${runlog}" 2>&1
  run_rc=$?
  set -e
  end_ns="$(date +%s%N)"
  elapsed_sec="$(awk "BEGIN { printf \"%.6f\", (${end_ns} - ${start_ns}) / 1000000000 }")"

  run_status="finished"
  if [[ "${run_rc}" -ne 0 ]]; then
    if grep -q "*** FAILED ***" "${runlog}" && grep -q "(timeout)" "${runlog}"; then
      run_status="max_cycles"
      echo "[inf] iteration ${iter}: max-cycles reached (rc=${run_rc}), accepting sample."
    else
      echo "[err] workload failed at iteration=${iter}, rc=${run_rc}" >&2
      echo "[err] workload log: ${runlog}" >&2
      exit 1
    fi
  fi

  printf '%s,"%s","%s",%s,%s,%s\n' \
    "${iter}" "${perfraw}" "${runlog}" "${elapsed_sec}" "${run_rc}" "${run_status}" >> "${MANIFEST_CSV}"
done

"${PYTHON_BIN}" "${PROFILING_DIR}/runscript/build/build_detailed_profile_outputs.py" \
  --manifest "${MANIFEST_CSV}" \
  --out-per-iter "${PER_ITER_CSV}" \
  --out-summary "${SUMMARY_CSV}" \
  --out-latency "${LATENCY_CSV}" \
  --out-latency-png "${LATENCY_PNG}" \
  --out-table "${TABLE_MD}" \
  --workload-name "${WORKLOAD_NAME}" \
  --event0-alias "${event0_alias}" \
  --event1-alias "${event1_alias}" \
  --event2-alias "${event2_alias}" \
  --event3-alias "${event3_alias}" \
  --latency-events "${LAT_EVENT_CSV}" \
  --strict-nonzero \
  --validation-report "${OUT_DIR}/validation_report.md"

echo
echo "[summary] MPKI + Runtime"
cat "${TABLE_MD}"
echo
echo "[ok] saved ${PER_ITER_CSV}"
echo "[ok] saved ${SUMMARY_CSV}"
echo "[ok] saved ${LATENCY_CSV}"
echo "[ok] saved ${LATENCY_PNG}"
echo "[ok] saved ${OUT_DIR}/validation_report.md"
