#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"

CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
BUILD_JOBS="${BUILD_JOBS:-$(nproc)}"
RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE:-1}"

PLATEAU_DIR="${PLATEAU_DIR:-}"
if [[ -z "${PLATEAU_DIR}" ]]; then
  PLATEAU_DIR="$(find "${LLVM_PREFETCH_DIR}/results/prefetch_plateau" -maxdepth 1 -type d -name 'plateau*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
fi
if [[ -z "${PLATEAU_DIR}" || ! -d "${PLATEAU_DIR}" ]]; then
  echo "[err] PLATEAU_DIR is required or no plateau dir was found" >&2
  exit 1
fi

LOG="${PLATEAU_DIR}/finalize_exact_compare.log"
TRACE_INPUTS="${TRACE_INPUTS:-}"
if [[ -z "${TRACE_INPUTS}" && -f "${PLATEAU_DIR}/manifest.txt" ]]; then
  TRACE_INPUTS="$(awk -F= '$1=="trace_inputs" {print substr($0, index($0,$2)); exit}' "${PLATEAU_DIR}/manifest.txt")"
fi
if [[ -z "${TRACE_INPUTS}" ]]; then
  echo "[err] TRACE_INPUTS is required or must be present in plateau manifest" | tee -a "${LOG}" >&2
  exit 1
fi

BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/detailed_profile/baseline_qsort_${MAX_CYCLES}/summary.csv}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"

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

require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_autotune.sh"
require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetch_scheme_compare_from_best.sh"
require_file "${BASELINE_BINARY}"
require_file "${BASELINE_SUMMARY}"

write_repair_variants() {
  local variants="$1"
  mkdir -p "$(dirname "${variants}")"
  cat > "${variants}" <<'EOF_VARIANTS'
cov50_tops_d4_16_b16_o2|999999|4|16|16|top-sites|1|0|50|0,64|
cov50_tops_d4_24_b8_o2|999999|4|24|8|top-sites|1|0|50|0,64|
cov75_bp_tops_d1_32_b8_o2|999999|1|32|8|top-sites|1|0|75|0,64|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
cov50_bp_tops_d1_32_b8_o4|999999|1|32|8|top-sites|1|0|50|0,64,128,192|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
EOF_VARIANTS
}

run_repair_variants() {
  local repair_dir="${PLATEAU_DIR}/batch_repair"
  local variants="${PLATEAU_DIR}/batches/batch_repair_variants.txt"
  if [[ -f "${repair_dir}/repair.done" ]]; then
    log "repair variants already complete: ${repair_dir}"
    return
  fi

  write_repair_variants "${variants}"
  log "running repair variants: ${variants}"
  RUN_ID="batch_repair" \
  OUT_DIR="${repair_dir}" \
  VARIANTS_FILE="${variants}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  TRACE_INPUT="${TRACE_INPUTS%%:*}" \
  BASELINE_BINARY="${BASELINE_BINARY}" \
  BASELINE_SUMMARY="${BASELINE_SUMMARY}" \
  SOURCE_WORK="${SOURCE_WORK}" \
  AUTOTUNE_HOURS=12 \
  SCREEN_ITERATIONS="${SCREEN_ITERATIONS}" \
  SCREEN_RUN_TRACE=0 \
  RUN_CONFIRMATION=0 \
  PREFETCH_MNEMONIC=prefetcht1 \
  PREFETCH_LABEL=prefetcht1 \
  BUILD_JOBS="${BUILD_JOBS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  ALLOW_UNRESOLVED_TARGETS=1 \
  STOP_RUNTIME_DELTA_PCT= \
  OBJDUMP_BIN=llvm-objdump-19 \
  ADDR2LINE_BIN=llvm-addr2line-19 \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_autotune.sh" \
    > "${repair_dir}.driver.log" 2>&1
  touch "${repair_dir}/repair.done"
  log "repair variants complete: ${repair_dir}"
}

run_exact_compare() {
  log "running exact same-plan prefetcht1 vs prefetchit1 compare"
  PLATEAU_DIR="${PLATEAU_DIR}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  FINAL_ITERATIONS="${FINAL_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetch_scheme_compare_from_best.sh" \
    > "${PLATEAU_DIR}/exact_best_compare.driver.log" 2>&1
  log "exact compare complete"
}

main() {
  log "finalize start: ${PLATEAU_DIR}"
  run_repair_variants
  run_exact_compare
  touch "${PLATEAU_DIR}/finalize.done"
  log "finalize done"
}

main "$@"
