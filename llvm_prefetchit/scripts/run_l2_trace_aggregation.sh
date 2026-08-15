#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

RUN_ID="${RUN_ID:-trace_agg_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/trace_aggregation/${RUN_ID}}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
TRACE_RUNS="${TRACE_RUNS:-3}"
TRACE_DURATION_SEC="${TRACE_DURATION_SEC:-60}"
TRACE_SAMPLE_PERIOD="${TRACE_SAMPLE_PERIOD:-100000}"
TRACE_EVENT_L2="${TRACE_EVENT_L2:-cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp}"
TRACE_USE_OCPERF="${TRACE_USE_OCPERF:-0}"
TRACE_PERF_SCOPE="${TRACE_PERF_SCOPE:-cpu}"
TRACE_COLLECTOR="${TRACE_COLLECTOR:-direct}"
TRACE_INPUTS="${TRACE_INPUTS:-}"
COLLECT_TRACES="${COLLECT_TRACES:-1}"
GENERATE_PLANS="${GENERATE_PLANS:-1}"
DEPTH_MIN="${DEPTH_MIN:-4}"
DEPTH="${DEPTH:-16}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetcht1}"
PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS:-0}"
ADDR2LINE_BIN="${ADDR2LINE_BIN:-llvm-addr2line-19}"
NM_BIN="${NM_BIN:-nm}"
PERF_BIN="${PERF_BIN:-perf}"
QBIN="${QBIN:-${REPO_ROOT}/benchmarks/tools/rocket-tools/riscv/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv}"

TRACES_BASE="${OUT_DIR}/traces"
PLANS_BASE="${OUT_DIR}/plans"
MANIFEST="${OUT_DIR}/manifest.txt"
LOG="${OUT_DIR}/trace_aggregation.log"

mkdir -p "${OUT_DIR}" "${TRACES_BASE}" "${PLANS_BASE}"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[err] missing file: ${path}" | tee -a "${LOG}" >&2
    exit 1
  fi
}

require_dir() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "[err] missing directory: ${path}" | tee -a "${LOG}" >&2
    exit 1
  fi
}

append_trace_input() {
  local trace_dir="$1"
  if [[ -z "${TRACE_INPUTS}" ]]; then
    TRACE_INPUTS="${trace_dir}"
  else
    TRACE_INPUTS="${TRACE_INPUTS}:${trace_dir}"
  fi
}

write_manifest() {
  cat > "${MANIFEST}" <<EOF
run_id=${RUN_ID}
out_dir=${OUT_DIR}
baseline_binary=${BASELINE_BINARY}
max_cycles=${MAX_CYCLES}
profile_core=${PROFILE_CORE}
trace_runs=${TRACE_RUNS}
trace_duration_sec=${TRACE_DURATION_SEC}
trace_sample_period=${TRACE_SAMPLE_PERIOD}
trace_event_l2=${TRACE_EVENT_L2}
trace_use_ocperf=${TRACE_USE_OCPERF}
trace_perf_scope=${TRACE_PERF_SCOPE}
trace_collector=${TRACE_COLLECTOR}
trace_inputs=${TRACE_INPUTS}
depth_min=${DEPTH_MIN}
depth=${DEPTH}
prefetch_mnemonic=${PREFETCH_MNEMONIC}
prefetch_byte_offsets=${PREFETCH_BYTE_OFFSETS}
EOF
}

require_file "${BASELINE_BINARY}"
require_file "${QBIN}"

trace_sample_count() {
  local trace_dir="$1"
  awk -F: '/LBR samples parsed/ {gsub(/ /, "", $2); print $2; exit}' \
    "${trace_dir}/trace_summary.md" 2>/dev/null || true
}

require_nonzero_trace() {
  local trace_dir="$1"
  local samples
  samples="$(trace_sample_count "${trace_dir}")"
  if [[ -z "${samples}" || ! "${samples}" =~ ^[0-9]+$ || "${samples}" -le 0 ]]; then
    echo "[err] trace has zero parsed LBR samples: ${trace_dir}" | tee -a "${LOG}" >&2
    [[ -f "${trace_dir}/record.log" ]] && sed -n '1,80p' "${trace_dir}/record.log" >&2
    exit 1
  fi
  log "trace samples=${samples}: ${trace_dir}"
}

collect_direct_l2_trace() {
  local run_name="$1"
  local trace_dir="${TRACES_BASE}/${run_name}/l2_miss"
  local data_file="${trace_dir}/l2miss_profile.data"
  local record_log="${trace_dir}/record.log"
  local rc=0

  mkdir -p "${trace_dir}"
  rm -f "${data_file}" "${trace_dir}/lbr_raw_dump.txt" "${trace_dir}/lbr_symbolic_dump.txt"
  log "direct perf record: ${run_name}"
  set +e
  "${PERF_BIN}" record \
    -e "${TRACE_EVENT_L2}" \
    -b \
    -c "${TRACE_SAMPLE_PERIOD}" \
    -o "${data_file}" \
    -C "${PROFILE_CORE}" \
    -- timeout -k 5s "${TRACE_DURATION_SEC}s" \
    taskset -c "${PROFILE_CORE}" \
    "${BASELINE_BINARY}" "${QBIN}" "+max-cycles=${MAX_CYCLES}" \
    > "${record_log}" 2>&1
  rc=$?
  set -e
  if [[ ! -s "${data_file}" ]]; then
    echo "[err] perf data not generated: ${data_file}" | tee -a "${LOG}" >&2
    sed -n '1,80p' "${record_log}" >&2 || true
    exit 1
  fi
  if [[ "${rc}" -ne 0 && "${rc}" -ne 124 ]]; then
    if ! grep -Eq "Captured and wrote|\\*\\*\\* FAILED \\*\\*\\*.*\\(timeout\\)" "${record_log}"; then
      echo "[err] direct perf record failed rc=${rc}: ${run_name}" | tee -a "${LOG}" >&2
      sed -n '1,80p' "${record_log}" >&2 || true
      exit 1
    fi
  fi
  bash "${PROFILING_DIR}/analyze_pebs_trace.sh" \
    --data "${data_file}" \
    --out-dir "${trace_dir}" \
    --event-label "${TRACE_EVENT_L2}" \
    --binary "${BASELINE_BINARY}" \
    --perf-bin "${PERF_BIN}" \
    2>&1 | tee -a "${LOG}"
}

if [[ "${COLLECT_TRACES}" == "1" ]]; then
  log "collect ${TRACE_RUNS} L2 traces into ${TRACES_BASE}"
  TRACE_INPUTS=""
  for idx in $(seq 1 "${TRACE_RUNS}"); do
    run_name="$(printf 'baseline_qsort_%s_trace%02d' "${MAX_CYCLES}" "${idx}")"
    log "trace ${idx}/${TRACE_RUNS}: ${run_name}"
    if [[ "${TRACE_COLLECTOR}" == "direct" ]]; then
      collect_direct_l2_trace "${run_name}"
    elif [[ "${TRACE_COLLECTOR}" == "wrapper" ]]; then
      bash "${PROFILING_DIR}/run_pebs_sampling.sh" \
        --workload verilator-qsort \
        --workload-name "${run_name}" \
        --sim-binary "${BASELINE_BINARY}" \
        --max-cycles "${MAX_CYCLES}" \
        --profile-core "${PROFILE_CORE}" \
        --perf-scope "${TRACE_PERF_SCOPE}" \
        --duration-sec "${TRACE_DURATION_SEC}" \
        --sample-period "${TRACE_SAMPLE_PERIOD}" \
        --event-l2 "${TRACE_EVENT_L2}" \
        --use-ocperf "${TRACE_USE_OCPERF}" \
        --trace-mode split \
        --trace-select l2 \
        --run-analyze 1 \
        --results-base "${TRACES_BASE}" \
        2>&1 | tee -a "${LOG}"
    else
      echo "[err] TRACE_COLLECTOR must be direct or wrapper: ${TRACE_COLLECTOR}" | tee -a "${LOG}" >&2
      exit 1
    fi
    trace_dir="${TRACES_BASE}/${run_name}/l2_miss"
    require_file "${trace_dir}/lbr_symbolic_dump.txt"
    require_nonzero_trace "${trace_dir}"
    append_trace_input "${trace_dir}"
  done
else
  [[ -n "${TRACE_INPUTS}" ]] || {
    echo "[err] COLLECT_TRACES=0 requires TRACE_INPUTS" | tee -a "${LOG}" >&2
    exit 1
  }
fi

write_manifest
log "aggregated TRACE_INPUTS=${TRACE_INPUTS}"

if [[ "${GENERATE_PLANS}" == "1" ]]; then
  IFS=':' read -r -a trace_dirs <<< "${TRACE_INPUTS}"
  trace_args=()
  for trace_dir in "${trace_dirs[@]}"; do
    [[ -n "${trace_dir}" ]] || continue
    require_dir "${trace_dir}"
    require_file "${trace_dir}/lbr_symbolic_dump.txt"
    trace_args+=(--trace-dir "${trace_dir}")
  done

  offset_tag="$(printf '%s' "${PREFETCH_BYTE_OFFSETS}" | tr ', ' '__')"
  for cov in 50 75 100; do
    plan_dir="${PLANS_BASE}/cov${cov}_allpaths_d${DEPTH_MIN}_${DEPTH}_o${offset_tag}"
    mkdir -p "${plan_dir}"
    log "generate plan coverage=${cov}% all-paths"
    python3 "${LLVM_PREFETCH_DIR}/tools/prefetchit_trace_to_plan.py" \
      "${trace_args[@]}" \
      --binary "${BASELINE_BINARY}" \
      --top-k 999999 \
      --target-coverage-pct "${cov}" \
      --depth "${DEPTH}" \
      --depth-min "${DEPTH_MIN}" \
      --site-budget-per-target 0 \
      --candidate-pool 0 \
      --selection-mode all-paths \
      --sites-per-depth 1 \
      --prefetch-mnemonic "${PREFETCH_MNEMONIC}" \
      --prefetch-byte-offsets "${PREFETCH_BYTE_OFFSETS}" \
      --allow-unresolved-targets \
      --addr2line "${ADDR2LINE_BIN}" \
      --nm "${NM_BIN}" \
      --summary-dir "${plan_dir}" \
      --output "${plan_dir}/${PREFETCH_MNEMONIC}.plan.json" \
      2>&1 | tee -a "${LOG}"
  done
fi

log "done: ${OUT_DIR}"
