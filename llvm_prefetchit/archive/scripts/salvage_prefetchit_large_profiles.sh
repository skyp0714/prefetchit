#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <prefetchit-large-parallel-dir>" >&2
  exit 1
fi

OUT_DIR="$(cd "$1" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-1}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
PREFETCH_LABEL="${PREFETCH_LABEL:-prefetchit1}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetchit1}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv}"
LOG="${OUT_DIR}/salvage_prefetchit_profiles.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[err] missing file: ${path}" | tee -a "${LOG}" >&2
    exit 1
  fi
}

require_file "${BASELINE_SUMMARY}"
cp -f "${OUT_DIR}/aggregate.csv" "${OUT_DIR}/aggregate.before_salvage.csv" 2>/dev/null || true
cp -f "${OUT_DIR}/profile_status.tsv" "${OUT_DIR}/profile_status.before_salvage.tsv" 2>/dev/null || true
rm -f "${OUT_DIR}/aggregate.csv" "${OUT_DIR}/leaderboard.md" "${OUT_DIR}/best_variant.txt" "${OUT_DIR}/profile_status.tsv"
: > "${OUT_DIR}/profile_status.tsv"

log "salvage profile start: ${OUT_DIR}"
log "iterations=${PROFILE_ITERATIONS}; core=${PROFILE_CORE}; label=${PREFETCH_LABEL}"

for run_dir in $(find "${OUT_DIR}/runs" -mindepth 1 -maxdepth 1 -type d -name 'v*' | sort -V); do
  variant="$(basename "${run_dir}")"
  bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
  plan="${run_dir}/plan/${PREFETCH_LABEL}.plan.json"
  build_log="${run_dir}/build/build_${PREFETCH_LABEL}.log"
  summary="${run_dir}/detailed_profile/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}/summary.csv"
  if [[ ! -x "${bin}" ]]; then
    log "skip ${variant}: no executable binary"
    python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
      --autotune-dir "${OUT_DIR}" \
      --variant "${variant}" \
      --run-dir "${run_dir}" \
      --baseline-summary "${BASELINE_SUMMARY}" \
      --max-cycles "${MAX_CYCLES}" \
      --status fail \
      --prefetch-label "${PREFETCH_LABEL}" \
      --rank-by runtime \
      --note "missing_binary" || true
    printf '%s\t%s\t%s\t%s\n' "${variant}" "skip_missing_binary" "missing_binary" "${run_dir}" >> "${OUT_DIR}/profile_status.tsv"
    continue
  fi
  if [[ ! -f "${run_dir}/assembly_validation/prefetch_asm_validation.md" && -f "${plan}" && -f "${build_log}" ]]; then
    log "validate relaxed ${variant}"
    PREFETCHIT_VALIDATION_SRCLINE_LIMIT=0 python3 "${LLVM_PREFETCH_DIR}/tools/validate_prefetch_asm.py" \
      --binary "${bin}" \
      --plan "${plan}" \
      --build-log "${build_log}" \
      --out-dir "${run_dir}/assembly_validation" \
      --mnemonic "${PREFETCH_MNEMONIC}" \
      --objdump llvm-objdump-19 \
      --addr2line llvm-addr2line-19 || true
  fi
  if [[ ! -f "${summary}" ]]; then
    log "profile ${variant}"
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
      > "${run_dir}/profile_${PREFETCH_LABEL}.salvage.log" 2>&1 </dev/null
    rc=$?
    set -e
    if [[ "${rc}" -ne 0 ]]; then
      log "profile fail ${variant}: rc=${rc}"
      python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
        --autotune-dir "${OUT_DIR}" \
        --variant "${variant}" \
        --run-dir "${run_dir}" \
        --baseline-summary "${BASELINE_SUMMARY}" \
        --max-cycles "${MAX_CYCLES}" \
        --status fail \
        --prefetch-label "${PREFETCH_LABEL}" \
        --rank-by runtime \
        --note "profile_rc=${rc}" || true
      printf '%s\t%s\t%s\t%s\n' "${variant}" "fail" "${rc}" "${run_dir}" >> "${OUT_DIR}/profile_status.tsv"
      continue
    fi
  else
    log "profile already present ${variant}"
  fi
  python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
    --autotune-dir "${OUT_DIR}" \
    --variant "${variant}" \
    --run-dir "${run_dir}" \
    --baseline-summary "${BASELINE_SUMMARY}" \
    --max-cycles "${MAX_CYCLES}" \
    --status ok \
    --prefetch-label "${PREFETCH_LABEL}" \
    --rank-by runtime
  printf '%s\t%s\t%s\t%s\n' "${variant}" "ok" "0" "${run_dir}" >> "${OUT_DIR}/profile_status.tsv"
  log "profile ok ${variant}"
done

PLOT_OUT="${OUT_DIR}/salvage_plot_$(date +%Y%m%d_%H%M%S)"
python3 "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_kind_injection_effects.py" \
  --results-root "${LLVM_PREFETCH_DIR}/results" \
  --baseline-summary "${BASELINE_SUMMARY}" \
  --out-dir "${PLOT_OUT}" || true
log "plot output: ${PLOT_OUT}"
log "salvage profile done"
