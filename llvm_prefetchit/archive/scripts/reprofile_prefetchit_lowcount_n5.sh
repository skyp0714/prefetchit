#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"
SWEEP_DIR="${SWEEP_DIR:-${LLVM_PREFETCH_DIR}/results/prefetchit_large_sweep/prefetchit_large_p16_20260623_015435}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_538240/summary.csv}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
ITERATIONS="${ITERATIONS:-5}"
PREFETCH_LABEL="${PREFETCH_LABEL:-prefetchit1}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
VARIANTS=("${@:-}")
if [[ "${#VARIANTS[@]}" -eq 0 || -z "${VARIANTS[0]:-}" ]]; then
  VARIANTS=(
    v01_cov05_tops_d4_8_b1_o1
    v02_cov05_tops_d4_16_b1_o1
    v03_cov10_tops_d4_8_b1_o1
    v04_cov10_tops_d4_16_b1_o1
  )
fi
LOG="${SWEEP_DIR}/reprofile_lowcount_n${ITERATIONS}.log"
log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }
mkdir -p "${SWEEP_DIR}/reprofile_backups"
log "low-count prefetchit reprofile start: variants=${VARIANTS[*]} iterations=${ITERATIONS} core=${PROFILE_CORE}"
for variant in "${VARIANTS[@]}"; do
  run_dir="${SWEEP_DIR}/parallel/runs/${variant}"
  bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
  result_dir="${run_dir}/detailed_profile/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}"
  if [[ ! -x "${bin}" ]]; then
    log "skip ${variant}: missing binary ${bin}"
    continue
  fi
  if [[ -d "${result_dir}" && ! -e "${run_dir}/detailed_profile/.n1_backup_done" ]]; then
    backup="${SWEEP_DIR}/reprofile_backups/${variant}_${PREFETCH_LABEL}_qsort_${MAX_CYCLES}_n1_$(date +%Y%m%d_%H%M%S)"
    cp -a "${result_dir}" "${backup}"
    touch "${run_dir}/detailed_profile/.n1_backup_done"
    log "backed up ${variant} n=1 result to ${backup}"
  fi
  rm -rf "${result_dir}"
  log "profile start ${variant}"
  "${PROFILING_DIR}/run_detailed_profile.sh" \
    --workload verilator-qsort \
    --workload-name "${PREFETCH_LABEL}_qsort_${MAX_CYCLES}" \
    --sim-binary "${bin}" \
    --max-cycles "${MAX_CYCLES}" \
    --iterations "${ITERATIONS}" \
    --profile-core "${PROFILE_CORE}" \
    --perf-scope task \
    --results-base "${run_dir}/detailed_profile" \
    > "${run_dir}/profile_${PREFETCH_LABEL}_n${ITERATIONS}.log" 2>&1
  python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
    --autotune-dir "${SWEEP_DIR}/parallel" \
    --variant "${variant}" \
    --run-dir "${run_dir}" \
    --baseline-summary "${BASELINE_SUMMARY}" \
    --max-cycles "${MAX_CYCLES}" \
    --status ok \
    --prefetch-label "${PREFETCH_LABEL}" \
    --rank-by runtime
  log "profile ok ${variant}"
done
PLOT_OUT="${SWEEP_DIR}/plots/injection_effects_line_lowcount_n${ITERATIONS}_$(date +%Y%m%d_%H%M%S)"
python3 "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_kind_injection_effects.py" \
  --results-root "${LLVM_PREFETCH_DIR}/results" \
  --baseline-summary "${BASELINE_SUMMARY}" \
  --out-dir "${PLOT_OUT}" \
  --x-scale symlog \
  --errorbar std
log "plot output: ${PLOT_OUT}"
log "low-count prefetchit reprofile done"
