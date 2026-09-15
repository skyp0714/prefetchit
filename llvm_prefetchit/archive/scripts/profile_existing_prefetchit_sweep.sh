#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

SWEEP_DIR="${SWEEP_DIR:-}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-1}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PREFETCH_LABEL="${PREFETCH_LABEL:-prefetchit1}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv}"
SUMMARY_RANK_BY="${SUMMARY_RANK_BY:-runtime}"
REPROFILE_EXISTING="${REPROFILE_EXISTING:-0}"
PLOT_RESULTS_ROOT="${PLOT_RESULTS_ROOT:-${LLVM_PREFETCH_DIR}/results}"

if [[ -z "${SWEEP_DIR}" ]]; then
  echo "[err] SWEEP_DIR is required" >&2
  exit 1
fi

PARALLEL_DIR="${SWEEP_DIR}/parallel"
BUILD_STATUS_TSV="${PARALLEL_DIR}/build_status.tsv"
PROFILE_STATUS_TSV="${PARALLEL_DIR}/profile_status_full.tsv"
LOG="${SWEEP_DIR}/profile_existing_${PREFETCH_LABEL}.log"

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[err] missing file: ${path}" | tee -a "${LOG}" >&2
    exit 1
  fi
}

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

require_file "${BUILD_STATUS_TSV}"
require_file "${BASELINE_SUMMARY}"
require_file "${PROFILING_DIR}/run_detailed_profile.sh"
require_file "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py"
require_file "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_kind_injection_effects.py"

: > "${PROFILE_STATUS_TSV}"
log "profile existing sweep start: ${SWEEP_DIR}"
log "iterations=${PROFILE_ITERATIONS} core=${PROFILE_CORE} reprofile_existing=${REPROFILE_EXISTING}"

mapfile -t build_status_lines < <(sort -V "${BUILD_STATUS_TSV}")
for line in "${build_status_lines[@]}"; do
  IFS=$'\t' read -r variant status rc run_dir <<< "${line}"
  if [[ "${status}" != "ok" ]]; then
    printf '%s\t%s\t%s\t%s\n' "${variant}" "skip_build_${status}" "${rc}" "${run_dir}" >> "${PROFILE_STATUS_TSV}"
    continue
  fi

  bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
  summary="${run_dir}/detailed_profile/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}/summary.csv"
  if [[ ! -x "${bin}" ]]; then
    log "skip ${variant}: missing binary ${bin}"
    printf '%s\t%s\t%s\t%s\n' "${variant}" "missing_binary" "1" "${run_dir}" >> "${PROFILE_STATUS_TSV}"
    continue
  fi
  if [[ "${REPROFILE_EXISTING}" != "1" && -f "${summary}" ]]; then
    log "skip ${variant}: existing summary"
    python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
      --autotune-dir "${PARALLEL_DIR}" \
      --variant "${variant}" \
      --run-dir "${run_dir}" \
      --baseline-summary "${BASELINE_SUMMARY}" \
      --max-cycles "${MAX_CYCLES}" \
      --status ok \
      --prefetch-label "${PREFETCH_LABEL}" \
      --rank-by "${SUMMARY_RANK_BY}"
    printf '%s\t%s\t%s\t%s\n' "${variant}" "skip_existing" "0" "${run_dir}" >> "${PROFILE_STATUS_TSV}"
    continue
  fi

  rm -rf "${run_dir}/detailed_profile/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}"
  log "profile start ${variant}"
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
    > "${run_dir}/profile_${PREFETCH_LABEL}_resume.log" 2>&1 </dev/null
  prc=$?
  set -e
  if [[ "${prc}" -ne 0 ]]; then
    log "profile fail ${variant}: rc=${prc}"
    python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
      --autotune-dir "${PARALLEL_DIR}" \
      --variant "${variant}" \
      --run-dir "${run_dir}" \
      --baseline-summary "${BASELINE_SUMMARY}" \
      --max-cycles "${MAX_CYCLES}" \
      --status fail \
      --prefetch-label "${PREFETCH_LABEL}" \
      --rank-by "${SUMMARY_RANK_BY}" \
      --note "resume_profile_rc=${prc}" || true
    printf '%s\t%s\t%s\t%s\n' "${variant}" "fail" "${prc}" "${run_dir}" >> "${PROFILE_STATUS_TSV}"
    continue
  fi

  python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
    --autotune-dir "${PARALLEL_DIR}" \
    --variant "${variant}" \
    --run-dir "${run_dir}" \
    --baseline-summary "${BASELINE_SUMMARY}" \
    --max-cycles "${MAX_CYCLES}" \
    --status ok \
    --prefetch-label "${PREFETCH_LABEL}" \
    --rank-by "${SUMMARY_RANK_BY}"
  printf '%s\t%s\t%s\t%s\n' "${variant}" "ok" "0" "${run_dir}" >> "${PROFILE_STATUS_TSV}"
  log "profile ok ${variant}"
done

PLOT_OUT="${SWEEP_DIR}/plots/injection_effects_line_resume_$(date +%Y%m%d_%H%M%S)"
python3 "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_kind_injection_effects.py" \
  --results-root "${PLOT_RESULTS_ROOT}" \
  --baseline-summary "${BASELINE_SUMMARY}" \
  --out-dir "${PLOT_OUT}" \
  --x-scale symlog

log "plot output: ${PLOT_OUT}"
log "profile existing sweep done"
