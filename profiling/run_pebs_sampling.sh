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
CHIPYARD_CONFIG="${CHIPYARD_CONFIG:-DualMegaBoomAndSingleRocketConfig}"
CHIPYARD_CONFIG_PACKAGE="${CHIPYARD_CONFIG_PACKAGE:-chipyard}"
SIM_BINARY="${SIM_BINARY:-}"
MAX_CYCLES="${MAX_CYCLES:-80000}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PERF_SCOPE="${PERF_SCOPE:-task}"
DURATION_SEC="${DURATION_SEC:-60}"
SAMPLE_PERIOD="${SAMPLE_PERIOD:-127}"
DURATION_L2_SEC="${DURATION_L2_SEC:-}"
DURATION_MID_SEC="${DURATION_MID_SEC:-}"
DURATION_ITLB_SEC="${DURATION_ITLB_SEC:-}"
DURATION_STLB_SEC="${DURATION_STLB_SEC:-}"
SAMPLE_PERIOD_L2="${SAMPLE_PERIOD_L2:-}"
SAMPLE_PERIOD_MID="${SAMPLE_PERIOD_MID:-}"
SAMPLE_PERIOD_ITLB="${SAMPLE_PERIOD_ITLB:-}"
SAMPLE_PERIOD_STLB="${SAMPLE_PERIOD_STLB:-}"
TRACE_MODE="${TRACE_MODE:-split}"
TRACE_SELECT="${TRACE_SELECT:-all}"
RUN_ANALYZE="${RUN_ANALYZE:-1}"
RESULTS_BASE="${RESULTS_BASE:-${PROFILING_DIR}/results/trace}"
PERF_BIN="${PERF_BIN:-perf}"
OCPERF_BIN="${OCPERF_BIN:-${REPO_ROOT}/.tmp/pmu-tools/ocperf.py}"
USE_OCPERF="${USE_OCPERF:-auto}"
RECORD_WEIGHT="${RECORD_WEIGHT:-0}"
QBIN="${QBIN:-${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv}"
MBIN="${MBIN:-${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/mm.riscv}"

L2_EVENT="${L2_EVENT:-frontend_retired.l2_miss:upp}"
MID_EVENT="${MID_EVENT:-auto}"
ITLB_EVENT="${ITLB_EVENT:-frontend_retired.itlb_miss:upp}"
STLB_EVENT="${STLB_EVENT:-frontend_retired.stlb_miss:upp}"
L2_EVENT_EXPLICIT=0
MID_EVENT_EXPLICIT=0
ITLB_EVENT_EXPLICIT=0
STLB_EVENT_EXPLICIT=0

usage() {
  cat <<'EOF'
Usage: ./run_pebs_sampling.sh [options]

Options:
  --workload <name>              Workload name: verilator-qsort | verilator-mm | verilator-custom
                                 default: verilator-qsort
  --workload-bin <path>          Custom workload binary path (required for verilator-custom)
  --workload-name <name>         Result directory name override
  --chipyard-config <Config>     Chipyard config class name
                                 default: DualMegaBoomAndSingleRocketConfig
  --chipyard-config-package <P>  Config package (default: chipyard)
  --sim-binary <path>            Simulator binary override
  --max-cycles <N>               +max-cycles for verilator workload (default: 80000)
  --profile-core <N>             Core to pin workload/perf to (default: 0)
  --perf-scope <task|cpu>        task: sample only the workload process tree;
                                 cpu: system-wide user samples on --profile-core
                                 default: task
  --duration-sec <N>             Trace wall-time limit in seconds (default: 60)
  --sample-period <N>            PEBS sample period -c N (default: 127)
  --duration-l2-sec <N>          L2 trace duration override (default: --duration-sec)
  --duration-mid-sec <N>         L3/DSB trace duration override (default: --duration-sec)
  --duration-itlb-sec <N>        ITLB trace duration override (default: --duration-sec)
  --duration-stlb-sec <N>        STLB trace duration override (default: --duration-sec)
  --sample-period-l2 <N>         L2 trace sample period override (default: --sample-period)
  --sample-period-mid <N>        L3/DSB trace sample period override (default: --sample-period)
  --sample-period-itlb <N>       ITLB trace sample period override (default: --sample-period)
  --sample-period-stlb <N>       STLB trace sample period override (default: --sample-period)
  --trace-mode <split|combined>  split: 4 traces, combined: one trace with 4 events
                                 default: split
  --trace-select <list>          For split mode, comma list from l2,mid,itlb,stlb,all
                                 default: all
  --run-analyze <0|1>            Run trace analysis after sampling (default: 1)
  --results-base <path>          Results base dir (default: profiling/results/trace)
  --perf-bin <path>              Perf binary path (default: perf)
  --ocperf-bin <path>            ocperf.py path (default: <repo>/.tmp/pmu-tools/ocperf.py)
  --use-ocperf <auto|0|1>        Use ocperf translation (default: auto)
  --record-weight <0|1>          Add perf record -W weight field (default: 0)
  --event-l2 <spec>              L2 miss event (default: frontend_retired.l2_miss:upp)
  --event-mid <spec|auto>        L3/DSB slot event (default: auto -> L3 if available else DSB)
  --event-itlb <spec>            ITLB miss event (default: frontend_retired.itlb_miss:upp)
  --event-stlb <spec>            STLB miss event (default: frontend_retired.stlb_miss:upp)
  --qbin <path>                  qsort binary path
  --mbin <path>                  mm binary path
  -h, --help                     Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workload)
      WORKLOAD="${2:-}"
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
    --duration-sec)
      DURATION_SEC="${2:-}"
      shift 2
      ;;
    --sample-period)
      SAMPLE_PERIOD="${2:-}"
      shift 2
      ;;
    --duration-l2-sec)
      DURATION_L2_SEC="${2:-}"
      shift 2
      ;;
    --duration-mid-sec)
      DURATION_MID_SEC="${2:-}"
      shift 2
      ;;
    --duration-itlb-sec)
      DURATION_ITLB_SEC="${2:-}"
      shift 2
      ;;
    --duration-stlb-sec)
      DURATION_STLB_SEC="${2:-}"
      shift 2
      ;;
    --sample-period-l2)
      SAMPLE_PERIOD_L2="${2:-}"
      shift 2
      ;;
    --sample-period-mid)
      SAMPLE_PERIOD_MID="${2:-}"
      shift 2
      ;;
    --sample-period-itlb)
      SAMPLE_PERIOD_ITLB="${2:-}"
      shift 2
      ;;
    --sample-period-stlb)
      SAMPLE_PERIOD_STLB="${2:-}"
      shift 2
      ;;
    --trace-mode)
      TRACE_MODE="${2:-}"
      shift 2
      ;;
    --trace-select)
      TRACE_SELECT="${2:-}"
      shift 2
      ;;
    --run-analyze)
      RUN_ANALYZE="${2:-}"
      shift 2
      ;;
    --results-base)
      RESULTS_BASE="${2:-}"
      shift 2
      ;;
    --perf-bin)
      PERF_BIN="${2:-}"
      shift 2
      ;;
    --ocperf-bin)
      OCPERF_BIN="${2:-}"
      shift 2
      ;;
    --use-ocperf)
      USE_OCPERF="${2:-}"
      shift 2
      ;;
    --record-weight)
      RECORD_WEIGHT="${2:-}"
      shift 2
      ;;
    --event-l2)
      L2_EVENT="${2:-}"
      L2_EVENT_EXPLICIT=1
      shift 2
      ;;
    --event-mid)
      MID_EVENT="${2:-}"
      MID_EVENT_EXPLICIT=1
      shift 2
      ;;
    --event-itlb)
      ITLB_EVENT="${2:-}"
      ITLB_EVENT_EXPLICIT=1
      shift 2
      ;;
    --event-stlb)
      STLB_EVENT="${2:-}"
      STLB_EVENT_EXPLICIT=1
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
if ! [[ "${DURATION_SEC}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --duration-sec must be a positive integer." >&2
  exit 1
fi
if ! [[ "${SAMPLE_PERIOD}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --sample-period must be a positive integer." >&2
  exit 1
fi
for n in DURATION_L2_SEC DURATION_MID_SEC DURATION_ITLB_SEC DURATION_STLB_SEC; do
  v="${!n}"
  if [[ -n "${v}" ]] && ! [[ "${v}" =~ ^[1-9][0-9]*$ ]]; then
    echo "[err] ${n} must be a positive integer when set." >&2
    exit 1
  fi
done
for n in SAMPLE_PERIOD_L2 SAMPLE_PERIOD_MID SAMPLE_PERIOD_ITLB SAMPLE_PERIOD_STLB; do
  v="${!n}"
  if [[ -n "${v}" ]] && ! [[ "${v}" =~ ^[1-9][0-9]*$ ]]; then
    echo "[err] ${n} must be a positive integer when set." >&2
    exit 1
  fi
done
if [[ "${TRACE_MODE}" != "split" && "${TRACE_MODE}" != "combined" ]]; then
  echo "[err] --trace-mode must be split or combined." >&2
  exit 1
fi
if [[ "${RUN_ANALYZE}" != "0" && "${RUN_ANALYZE}" != "1" ]]; then
  echo "[err] --run-analyze must be 0 or 1." >&2
  exit 1
fi
if [[ "${USE_OCPERF}" != "auto" && "${USE_OCPERF}" != "0" && "${USE_OCPERF}" != "1" ]]; then
  echo "[err] --use-ocperf must be auto|0|1." >&2
  exit 1
fi
if [[ "${RECORD_WEIGHT}" != "0" && "${RECORD_WEIGHT}" != "1" ]]; then
  echo "[err] --record-weight must be 0 or 1." >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  paranoid="$(cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null || echo 4)"
  if [[ "${paranoid}" =~ ^-?[0-9]+$ ]] && (( paranoid >= 1 )); then
    echo "[err] perf_event_paranoid=${paranoid} blocks CPU PMU sampling for unprivileged users." >&2
    echo "[err] Run with sudo or lower kernel.perf_event_paranoid." >&2
    exit 1
  fi
fi

setup_verilator_env
require_chipyard_tree

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
    exit 1
    ;;
esac

EMU="$(resolve_chipyard_simulator "${CHIPYARD_CONFIG}" "${CHIPYARD_CONFIG_PACKAGE}" || true)"
if [[ -n "${SIM_BINARY}" ]]; then
  EMU="${SIM_BINARY}"
fi
if [[ -z "${EMU}" ]]; then
  echo "[err] simulator binary not found for config=${CHIPYARD_CONFIG}" >&2
  exit 1
fi
require_file "${EMU}"

if [[ -z "${WORKLOAD_NAME}" ]]; then
  if [[ "${WORKLOAD}" == "verilator-custom" ]]; then
    base="$(basename "${WORKLOAD_BIN}")"
    WORKLOAD_NAME="verilator-${base%.riscv}"
  else
    WORKLOAD_NAME="${WORKLOAD}"
  fi
fi

use_ocperf=0
if [[ "${USE_OCPERF}" == "1" ]]; then
  use_ocperf=1
elif [[ "${USE_OCPERF}" == "auto" && -x "${OCPERF_BIN}" ]]; then
  use_ocperf=1
fi

ocperf_event_exists() {
  local ev="$1"
  "${OCPERF_BIN}" list 2>/dev/null | awk '{print $1}' | grep -Fxiq "${ev}"
}

if [[ "${use_ocperf}" -eq 1 ]]; then
  if [[ ! -x "${OCPERF_BIN}" ]]; then
    echo "[err] ocperf requested but not executable: ${OCPERF_BIN}" >&2
    exit 1
  fi
  if [[ "${MID_EVENT}" == "auto" ]]; then
    if ocperf_event_exists "frontend_retired.l3_miss"; then
      MID_EVENT="frontend_retired.l3_miss:upp"
    else
      MID_EVENT="frontend_retired.dsb_miss:upp"
    fi
  fi
else
  # Raw fallback for Granite Rapids FRONTEND_RETIRED events.
  if [[ "${L2_EVENT_EXPLICIT}" -eq 0 ]]; then
    L2_EVENT="cpu/event=0xc6,umask=0x3,config1=0x13,name=frontend_retired_l2_miss/upp"
  fi
  if [[ "${MID_EVENT_EXPLICIT}" -eq 0 ]]; then
    MID_EVENT="cpu/event=0xc6,umask=0x3,config1=0x11,name=frontend_retired_dsb_miss/upp"
  fi
  if [[ "${ITLB_EVENT_EXPLICIT}" -eq 0 ]]; then
    ITLB_EVENT="cpu/event=0xc6,umask=0x3,config1=0x14,name=frontend_retired_itlb_miss/upp"
  fi
  if [[ "${STLB_EVENT_EXPLICIT}" -eq 0 ]]; then
    STLB_EVENT="cpu/event=0xc6,umask=0x3,config1=0x15,name=frontend_retired_stlb_miss/upp"
  fi
fi

if [[ -z "${DURATION_L2_SEC}" ]]; then DURATION_L2_SEC="${DURATION_SEC}"; fi
if [[ -z "${DURATION_MID_SEC}" ]]; then DURATION_MID_SEC="${DURATION_SEC}"; fi
if [[ -z "${DURATION_ITLB_SEC}" ]]; then DURATION_ITLB_SEC="${DURATION_SEC}"; fi
if [[ -z "${DURATION_STLB_SEC}" ]]; then DURATION_STLB_SEC="${DURATION_SEC}"; fi
if [[ -z "${SAMPLE_PERIOD_L2}" ]]; then SAMPLE_PERIOD_L2="${SAMPLE_PERIOD}"; fi
if [[ -z "${SAMPLE_PERIOD_MID}" ]]; then SAMPLE_PERIOD_MID="${SAMPLE_PERIOD}"; fi
if [[ -z "${SAMPLE_PERIOD_ITLB}" ]]; then SAMPLE_PERIOD_ITLB="${SAMPLE_PERIOD}"; fi
if [[ -z "${SAMPLE_PERIOD_STLB}" ]]; then SAMPLE_PERIOD_STLB="${SAMPLE_PERIOD}"; fi

OUT_DIR="${RESULTS_BASE}/${WORKLOAD_NAME}"
mkdir -p "${OUT_DIR}"
MANIFEST_CSV="${OUT_DIR}/trace_manifest.csv"
echo "trace_name,event_spec,data_file,record_log,status,record_rc,duration_sec,sample_period" > "${MANIFEST_CSV}"

WORKLOAD_CMD=(taskset -c "${PROFILE_CORE}" "${EMU}" "${WORKLOAD_BIN}" "+max-cycles=${MAX_CYCLES}")

run_one_trace() {
  local trace_name="$1"
  local event_spec="$2"
  local duration_sec="$3"
  local sample_period="$4"
  local trace_dir="${OUT_DIR}/${trace_name}"
  local data_file="${trace_dir}/l2miss_profile.data"
  local record_log="${trace_dir}/record.log"
  local status="ok"
  local rc=0

  mkdir -p "${trace_dir}"
  rm -f "${data_file}"
  # Clean stale outputs from older latency-enabled flow.
  rm -f \
    "${trace_dir}/miss_latencies.txt" \
    "${trace_dir}/latency_histogram.csv" \
    "${trace_dir}/latency_histogram.png"

  local target_cmd=("${WORKLOAD_CMD[@]}")
  if (( duration_sec > 0 )); then
    target_cmd=(timeout -k 5s "${duration_sec}s" "${WORKLOAD_CMD[@]}")
  fi

  local cmd=()
  local record_opts=(record -e "${event_spec}" -b)
  if [[ "${RECORD_WEIGHT}" == "1" ]]; then
    record_opts+=(-W)
  fi
  record_opts+=(-c "${sample_period}" -o "${data_file}")
  if [[ "${PERF_SCOPE}" == "cpu" ]]; then
    record_opts+=(-C "${PROFILE_CORE}")
  fi
  record_opts+=(--)
  if [[ "${use_ocperf}" -eq 1 ]]; then
    cmd=("${OCPERF_BIN}" "${record_opts[@]}" "${target_cmd[@]}")
  else
    cmd=("${PERF_BIN}" "${record_opts[@]}" "${target_cmd[@]}")
  fi

  echo "[run] ${trace_name}: ${event_spec} (duration=${duration_sec}s period=${sample_period})"
  set +e
  "${cmd[@]}" > "${record_log}" 2>&1
  rc=$?
  set -e

  if [[ ! -s "${data_file}" ]]; then
    echo "[err] trace data not generated for ${trace_name}" >&2
    sed -n '1,80p' "${record_log}" >&2 || true
    exit 1
  fi
  if [[ "${rc}" -ne 0 && "${rc}" -ne 124 ]]; then
    if grep -Eq "Captured and wrote|\\*\\*\\* FAILED \\*\\*\\*.*\\(timeout\\)" "${record_log}"; then
      status="accepted_nonzero"
    else
      echo "[err] perf record failed for ${trace_name} (rc=${rc})" >&2
      sed -n '1,80p' "${record_log}" >&2 || true
      exit 1
    fi
  fi
  if [[ "${rc}" -eq 124 ]]; then
    status="duration_timeout"
  fi

  printf '%s,"%s","%s","%s",%s,%s,%s,%s\n' \
    "${trace_name}" "${event_spec}" "${data_file}" "${record_log}" "${status}" "${rc}" "${duration_sec}" "${sample_period}" >> "${MANIFEST_CSV}"

  if [[ "${RUN_ANALYZE}" == "1" ]]; then
    "${PROFILING_DIR}/analyze_pebs_trace.sh" \
      --data "${data_file}" \
      --out-dir "${trace_dir}" \
      --event-label "${event_spec}" \
      --binary "${EMU}" \
      --perf-bin "${PERF_BIN}"
  fi
}

echo "[inf] workload=${WORKLOAD} core=${PROFILE_CORE} duration(default)=${DURATION_SEC}s mode=${TRACE_MODE}"
echo "[inf] perf_scope=${PERF_SCOPE}"
echo "[inf] simulator=${EMU}"
echo "[inf] results_dir=${OUT_DIR}"
if [[ "${use_ocperf}" -eq 1 ]]; then
  echo "[inf] event resolver=ocperf (${OCPERF_BIN})"
else
  echo "[inf] event resolver=raw perf encoding fallback"
fi
echo "[inf] per-trace duration(s): l2=${DURATION_L2_SEC} mid=${DURATION_MID_SEC} itlb=${DURATION_ITLB_SEC} stlb=${DURATION_STLB_SEC}"
echo "[inf] per-trace period: l2=${SAMPLE_PERIOD_L2} mid=${SAMPLE_PERIOD_MID} itlb=${SAMPLE_PERIOD_ITLB} stlb=${SAMPLE_PERIOD_STLB}"

if [[ "${TRACE_MODE}" == "split" ]]; then
  MID_TRACE_NAME="dsb_miss"
  if [[ "${MID_EVENT,,}" == *"l3_miss"* ]]; then
    MID_TRACE_NAME="l3_miss"
  fi

  IFS=',' read -r -a selected_traces <<< "${TRACE_SELECT}"
  want_trace() {
    local needle="$1"
    local item
    for item in "${selected_traces[@]}"; do
      item="${item//[[:space:]]/}"
      if [[ "${item}" == "all" || "${item}" == "${needle}" ]]; then
        return 0
      fi
    done
    return 1
  }

  ran_trace_names=()
  if want_trace "l2"; then
    run_one_trace "l2_miss" "${L2_EVENT}" "${DURATION_L2_SEC}" "${SAMPLE_PERIOD_L2}"
    ran_trace_names+=("l2_miss")
  fi
  if want_trace "mid"; then
    run_one_trace "${MID_TRACE_NAME}" "${MID_EVENT}" "${DURATION_MID_SEC}" "${SAMPLE_PERIOD_MID}"
    ran_trace_names+=("${MID_TRACE_NAME}")
  fi
  if want_trace "itlb"; then
    run_one_trace "itlb_miss" "${ITLB_EVENT}" "${DURATION_ITLB_SEC}" "${SAMPLE_PERIOD_ITLB}"
    ran_trace_names+=("itlb_miss")
  fi
  if want_trace "stlb"; then
    run_one_trace "stlb_miss" "${STLB_EVENT}" "${DURATION_STLB_SEC}" "${SAMPLE_PERIOD_STLB}"
    ran_trace_names+=("stlb_miss")
  fi
  if [[ "${#ran_trace_names[@]}" -eq 0 ]]; then
    echo "[err] --trace-select selected no traces: ${TRACE_SELECT}" >&2
    exit 1
  fi
else
  run_one_trace "combined_4events" "${L2_EVENT},${MID_EVENT},${ITLB_EVENT},${STLB_EVENT}" "${DURATION_SEC}" "${SAMPLE_PERIOD}"
fi

if [[ "${RUN_ANALYZE}" == "1" && "${TRACE_MODE}" == "split" && "${#ran_trace_names[@]}" -gt 1 ]]; then
  TRACE_NAMES="$(IFS=','; echo "${ran_trace_names[*]}")"
  STACKED_DETAIL_PNG="${OUT_DIR}/top10_target_branch_stacked_detail.png"
  STACKED_DETAIL_CSV="${OUT_DIR}/top10_target_branch_stacked_detail.csv"
  STACKED_MERGED_PNG="${OUT_DIR}/top10_target_branch_stacked_merged.png"
  STACKED_MERGED_CSV="${OUT_DIR}/top10_target_branch_stacked_merged.csv"
  AB_MD="${OUT_DIR}/ab_comparison.md"
  AB_CSV="${OUT_DIR}/ab_summary.csv"
  AB_VAL_MD="${OUT_DIR}/ab_validation.md"

  echo "[run] cross-trace A/B summary"
  "${PYTHON_BIN}" "${PROFILING_DIR}/runscript/build/build_trace_ab_comparison.py" \
    --trace-root "${OUT_DIR}" \
    --trace-names "${TRACE_NAMES}" \
    --out-md "${AB_MD}" \
    --out-csv "${AB_CSV}" \
    --out-validation-md "${AB_VAL_MD}"

  echo "[run] stacked ratio plot (top10 targets + others)"
  "${PYTHON_BIN}" "${PROFILING_DIR}/runscript/plot/plot_trace_top10_target_stack.py" \
    --trace-root "${OUT_DIR}" \
    --trace-names "${TRACE_NAMES}" \
    --out-detail-png "${STACKED_DETAIL_PNG}" \
    --out-detail-csv "${STACKED_DETAIL_CSV}" \
    --out-merged-png "${STACKED_MERGED_PNG}" \
    --out-merged-csv "${STACKED_MERGED_CSV}"

  echo "[ok] saved ${AB_MD}"
  echo "[ok] saved ${AB_CSV}"
  echo "[ok] saved ${AB_VAL_MD}"
  echo "[ok] saved ${STACKED_DETAIL_PNG}"
  echo "[ok] saved ${STACKED_DETAIL_CSV}"
  echo "[ok] saved ${STACKED_MERGED_PNG}"
  echo "[ok] saved ${STACKED_MERGED_CSV}"
elif [[ "${TRACE_MODE}" == "combined" ]]; then
  echo "[inf] skip cross-trace stacked plot for combined mode (single mixed trace)."
elif [[ "${TRACE_MODE}" == "split" && "${#ran_trace_names[@]}" -le 1 ]]; then
  echo "[inf] skip cross-trace stacked plot because only one split trace was selected."
elif [[ "${RUN_ANALYZE}" != "1" ]]; then
  echo "[inf] skip cross-trace stacked plot because --run-analyze=0."
fi

echo
echo "[ok] saved ${MANIFEST_CSV}"
