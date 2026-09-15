#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

RUN_ID="${RUN_ID:-prefetcht_branch_types_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/prefetcht_branch_type_sweep/${RUN_ID}}"
RUNS_DIR="${OUT_DIR}/runs"
LOG_DIR="${OUT_DIR}/logs"
PLOTS_DIR="${OUT_DIR}/plots"
LOG="${OUT_DIR}/branch_type_sweep.log"

CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-3}"
PARALLEL_BUILDS="${PARALLEL_BUILDS:-6}"
BUILD_JOBS="${BUILD_JOBS:-8}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetcht1}"
PREFETCH_LABEL="${PREFETCH_LABEL:-prefetcht1}"
BRANCH_TYPES="${BRANCH_TYPES:-COND RET UNCOND CALL IND_CALL IND}"
FORCE_BUILD="${FORCE_BUILD:-0}"
FORCE_PROFILE="${FORCE_PROFILE:-0}"

# Best prefetcht1 parameter set from the previous exact compare run.
TOP_K="${TOP_K:-999999}"
TARGET_COVERAGE_PCT="${TARGET_COVERAGE_PCT:-50}"
DEPTH_MIN="${DEPTH_MIN:-4}"
DEPTH="${DEPTH:-24}"
SITE_BUDGET="${SITE_BUDGET:-8}"
CANDIDATE_POOL="${CANDIDATE_POOL:-0}"
SELECTION_MODE="${SELECTION_MODE:-top-sites}"
SITES_PER_DEPTH="${SITES_PER_DEPTH:-1}"
PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS:-0,64}"
BRANCH_DEPTH_POLICY="${BRANCH_DEPTH_POLICY:-}"

BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
BEST_PLAN="${BEST_PLAN:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/plateau_fixed_20260604_013311/batch_repair/runs/v02_cov50_tops_d4_24_b8_o2/plan/prefetcht1.plan.json}"
BASELINE_PER_ITER="${BASELINE_PER_ITER:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv}"
GENERAL_PER_ITER="${GENERAL_PER_ITER:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/prefetcht1_qsort_${MAX_CYCLES}/per_iteration.csv}"
TRACE_INPUTS="${TRACE_INPUTS:-}"

VARIANT_CSV="${OUT_DIR}/branch_type_variants.csv"
BUILD_STATUS_TSV="${OUT_DIR}/build_status.tsv"
PROFILE_STATUS_TSV="${OUT_DIR}/profile_status.tsv"

mkdir -p "${OUT_DIR}" "${RUNS_DIR}" "${LOG_DIR}" "${PLOTS_DIR}"

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

trace_inputs_from_plan() {
  python3 - "$1" <<'PY'
import json
import sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
trace_dirs = plan.get("trace_dirs") or plan.get("trace_inputs") or []
if isinstance(trace_dirs, str):
    trace_dirs = [item for item in trace_dirs.split(":") if item]
print(":".join(trace_dirs))
PY
}

append_status() {
  local file="$1"
  shift
  {
    flock 9
    local IFS=$'\t'
    printf '%s\n' "$*"
  } 9>"${file}.lock" >> "${file}"
}

lower_branch() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

write_variant_csv() {
  echo "variant,branch_type,plot_label,run_dir,build_status,profile_status" > "${VARIANT_CSV}"
  local idx=0 branch variant plot_label run_dir build_status profile_status
  for branch in ${BRANCH_TYPES}; do
    idx=$((idx + 1))
    variant="v$(printf '%02d' "${idx}")_branch_$(lower_branch "${branch}")"
    plot_label="${branch}"
    run_dir="${RUNS_DIR}/${variant}"
    build_status="pending"
    profile_status="pending"
    if grep -q -P "^${variant}\tok\t" "${BUILD_STATUS_TSV}" 2>/dev/null; then
      build_status="ok"
    elif grep -q -P "^${variant}\tfail\t" "${BUILD_STATUS_TSV}" 2>/dev/null; then
      build_status="fail"
    fi
    if grep -q -P "^${variant}\tok\t" "${PROFILE_STATUS_TSV}" 2>/dev/null; then
      profile_status="ok"
    elif grep -q -P "^${variant}\tfail\t" "${PROFILE_STATUS_TSV}" 2>/dev/null; then
      profile_status="fail"
    elif [[ "${build_status}" == "fail" ]]; then
      profile_status="skip_build_fail"
    fi
    printf '%s,%s,%s,%s,%s,%s\n' "${variant}" "${branch}" "${plot_label}" "${run_dir}" "${build_status}" "${profile_status}" >> "${VARIANT_CSV}"
  done
}

build_one() {
  local variant="$1" branch="$2"
  local run_dir="${RUNS_DIR}/${variant}"
  local bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
  local build_log="${LOG_DIR}/${variant}.build.log"

  if [[ "${FORCE_BUILD}" != "1" && -x "${bin}" ]]; then
    append_status "${BUILD_STATUS_TSV}" "${variant}" "ok" "0" "${run_dir}" "reuse"
    log "build reuse ${variant}: ${bin}"
    return 0
  fi

  log "build start ${variant}: branch=${branch} coverage=${TARGET_COVERAGE_PCT}% d=${DEPTH_MIN}-${DEPTH} budget=${SITE_BUDGET} offsets=${PREFETCH_BYTE_OFFSETS}"
  set +e
  RESULT_BASE="${RUNS_DIR}" \
  RUN_ID="${variant}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  TRACE_INPUT="${TRACE_INPUTS%%:*}" \
  BASELINE_BINARY="${BASELINE_BINARY}" \
  SOURCE_WORK="${SOURCE_WORK}" \
  CONFIG="${CONFIG}" \
  TOP_K="${TOP_K}" \
  TARGET_COVERAGE_PCT="${TARGET_COVERAGE_PCT}" \
  DEPTH_MIN="${DEPTH_MIN}" \
  DEPTH="${DEPTH}" \
  SITE_BUDGET="${SITE_BUDGET}" \
  CANDIDATE_POOL="${CANDIDATE_POOL}" \
  SELECTION_MODE="${SELECTION_MODE}" \
  SITES_PER_DEPTH="${SITES_PER_DEPTH}" \
  ALLOW_UNRESOLVED_TARGETS=1 \
  PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC}" \
  PREFETCH_LABEL="${PREFETCH_LABEL}" \
  PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS}" \
  BRANCH_DEPTH_POLICY="${BRANCH_DEPTH_POLICY}" \
  BRANCH_TYPE_FILTER="${branch}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  PROFILE_ITERATIONS="${PROFILE_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  OBJDUMP_BIN=llvm-objdump-19 \
  ADDR2LINE_BIN=llvm-addr2line-19 \
  RUN_BASELINE=0 \
  RUN_PROFILE=0 \
  RUN_TRACE=0 \
  CLEAN_WORKDIR=1 \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh" > "${build_log}" 2>&1
  local rc=$?
  set -e
  if [[ "${rc}" -eq 0 ]]; then
    append_status "${BUILD_STATUS_TSV}" "${variant}" "ok" "0" "${run_dir}" "built"
    log "build ok ${variant}"
  else
    append_status "${BUILD_STATUS_TSV}" "${variant}" "fail" "${rc}" "${run_dir}" "${build_log}"
    log "build fail ${variant}: rc=${rc}; log=${build_log}"
  fi
}

wait_for_slot() {
  while (( "$(jobs -rp | wc -l)" >= PARALLEL_BUILDS )); do
    sleep 20
  done
}

run_parallel_builds() {
  : > "${BUILD_STATUS_TSV}"
  local idx=0 branch variant
  for branch in ${BRANCH_TYPES}; do
    idx=$((idx + 1))
    variant="v$(printf '%02d' "${idx}")_branch_$(lower_branch "${branch}")"
    wait_for_slot
    build_one "${variant}" "${branch}" </dev/null &
  done
  wait
}

profile_successful_builds() {
  : > "${PROFILE_STATUS_TSV}"
  mapfile -t build_status_lines < <(sort -V "${BUILD_STATUS_TSV}" || true)
  local line variant status rc run_dir note bin per_iter
  for line in "${build_status_lines[@]}"; do
    IFS=$'\t' read -r variant status rc run_dir note <<< "${line}"
    if [[ "${status}" != "ok" ]]; then
      append_status "${PROFILE_STATUS_TSV}" "${variant}" "skip_build_fail" "${rc}" "${run_dir}" "${note:-}"
      continue
    fi
    bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
    per_iter="${run_dir}/detailed_profile/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}/per_iteration.csv"
    if [[ ! -x "${bin}" ]]; then
      append_status "${PROFILE_STATUS_TSV}" "${variant}" "fail" "missing_binary" "${run_dir}" ""
      log "profile skip ${variant}: missing binary"
      continue
    fi
    if [[ "${FORCE_PROFILE}" != "1" && -f "${per_iter}" ]]; then
      append_status "${PROFILE_STATUS_TSV}" "${variant}" "ok" "0" "${run_dir}" "reuse"
      log "profile reuse ${variant}: ${per_iter}"
      continue
    fi
    log "profile start ${variant}: iterations=${PROFILE_ITERATIONS} core=${PROFILE_CORE}"
    set +e
    "${PROFILING_DIR}/run_detailed_profile.sh" \
      --workload verilator-qsort \
      --workload-name "${PREFETCH_LABEL}_qsort_${MAX_CYCLES}" \
      --sim-binary "${bin}" \
      --max-cycles "${MAX_CYCLES}" \
      --iterations "${PROFILE_ITERATIONS}" \
      --profile-core "${PROFILE_CORE}" \
      --perf-scope task \
      --results-base "${run_dir}/detailed_profile" \
      > "${LOG_DIR}/${variant}.profile.log" 2>&1 </dev/null
    rc=$?
    set -e
    if [[ "${rc}" -eq 0 ]]; then
      append_status "${PROFILE_STATUS_TSV}" "${variant}" "ok" "0" "${run_dir}" "profiled"
      log "profile ok ${variant}"
    else
      append_status "${PROFILE_STATUS_TSV}" "${variant}" "fail" "${rc}" "${run_dir}" "${LOG_DIR}/${variant}.profile.log"
      log "profile fail ${variant}: rc=${rc}; log=${LOG_DIR}/${variant}.profile.log"
    fi
  done
}

write_manifest() {
  cat > "${OUT_DIR}/manifest.txt" <<EOF
run_id=${RUN_ID}
out_dir=${OUT_DIR}
config=${CONFIG}
max_cycles=${MAX_CYCLES}
profile_core=${PROFILE_CORE}
profile_iterations=${PROFILE_ITERATIONS}
parallel_builds=${PARALLEL_BUILDS}
build_jobs=${BUILD_JOBS}
prefetch_mnemonic=${PREFETCH_MNEMONIC}
prefetch_label=${PREFETCH_LABEL}
best_params=top_k=${TOP_K},target_coverage_pct=${TARGET_COVERAGE_PCT},depth=${DEPTH_MIN}-${DEPTH},site_budget=${SITE_BUDGET},selection=${SELECTION_MODE},sites_per_depth=${SITES_PER_DEPTH},candidate_pool=${CANDIDATE_POOL},offsets=${PREFETCH_BYTE_OFFSETS},branch_depth_policy=${BRANCH_DEPTH_POLICY:-default}
branch_types=${BRANCH_TYPES}
best_plan=${BEST_PLAN}
trace_inputs=${TRACE_INPUTS}
baseline_binary=${BASELINE_BINARY}
source_work=${SOURCE_WORK}
baseline_per_iteration=${BASELINE_PER_ITER}
general_per_iteration=${GENERAL_PER_ITER}
force_build=${FORCE_BUILD}
force_profile=${FORCE_PROFILE}
EOF
}

plot_results() {
  write_variant_csv
  python3 "${LLVM_PREFETCH_DIR}/tools/plot_branch_type_prefetch_results.py" \
    --metadata "${VARIANT_CSV}" \
    --baseline-per-iteration "${BASELINE_PER_ITER}" \
    --general-per-iteration "${GENERAL_PER_ITER}" \
    --profile-name "${PREFETCH_LABEL}_qsort_${MAX_CYCLES}" \
    --out-dir "${PLOTS_DIR}" | tee -a "${LOG}"
}

require_file "${BASELINE_BINARY}"
require_file "${BASELINE_PER_ITER}"
require_file "${GENERAL_PER_ITER}"
require_file "${BEST_PLAN}"
require_file "${LLVM_PREFETCH_DIR}/tools/prefetchit_trace_to_plan.py"
require_file "${LLVM_PREFETCH_DIR}/tools/plot_branch_type_prefetch_results.py"
require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh"
require_file "${PROFILING_DIR}/run_detailed_profile.sh"
require_dir "${SOURCE_WORK}"

if [[ -z "${TRACE_INPUTS}" ]]; then
  TRACE_INPUTS="$(trace_inputs_from_plan "${BEST_PLAN}")"
fi
if [[ -z "${TRACE_INPUTS}" ]]; then
  echo "[err] could not derive TRACE_INPUTS from ${BEST_PLAN}" | tee -a "${LOG}" >&2
  exit 1
fi
IFS=':' read -r -a trace_dirs <<< "${TRACE_INPUTS}"
for trace_dir in "${trace_dirs[@]}"; do
  [[ -n "${trace_dir}" ]] || continue
  require_dir "${trace_dir}"
  require_file "${trace_dir}/lbr_symbolic_dump.txt"
done

write_manifest
log "branch-type prefetcht1 sweep start: ${OUT_DIR}"
log "branches=${BRANCH_TYPES}"
log "best params: coverage=${TARGET_COVERAGE_PCT}% d=${DEPTH_MIN}-${DEPTH} budget=${SITE_BUDGET} mode=${SELECTION_MODE} offsets=${PREFETCH_BYTE_OFFSETS}"
run_parallel_builds
write_variant_csv
profile_successful_builds
plot_results
log "branch-type prefetcht1 sweep complete"
