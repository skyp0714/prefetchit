#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"

SESSION="${SESSION:-prefetch_until_plateau}"
POLL_SEC="${POLL_SEC:-3600}"
RUN_ID="${RUN_ID:-}"
OUT_DIR="${OUT_DIR:-}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
MAX_BATCHES="${MAX_BATCHES:-5}"
MIN_IMPROVEMENT_ABS_PCT="${MIN_IMPROVEMENT_ABS_PCT:-1.0}"
PATIENCE_BATCHES="${PATIENCE_BATCHES:-2}"
RUN_FINAL_COMPARE="${RUN_FINAL_COMPARE:-1}"
RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE:-1}"
BUILD_JOBS="${BUILD_JOBS:-$(nproc)}"
TRACE_INPUTS="${TRACE_INPUTS:-}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/detailed_profile/baseline_qsort_${MAX_CYCLES}/summary.csv}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
WATCH_DIR="${WATCH_DIR:-${LLVM_PREFETCH_DIR}/results/prefetch_watchdog}"
LOG="${WATCH_DIR}/watchdog.log"

mkdir -p "${WATCH_DIR}"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

latest_plateau_dir() {
  if [[ -n "${OUT_DIR}" && -d "${OUT_DIR}" ]]; then
    printf '%s\n' "${OUT_DIR}"
    return
  fi
  find "${LLVM_PREFETCH_DIR}/results/prefetch_plateau" -maxdepth 1 -type d -name 'plateau*' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | head -1 | cut -d' ' -f2-
}

load_trace_inputs_from_dir() {
  local dir="$1"
  if [[ -z "${TRACE_INPUTS}" && -f "${dir}/manifest.txt" ]]; then
    TRACE_INPUTS="$(awk -F= '$1=="trace_inputs" {print substr($0, index($0,$2)); exit}' "${dir}/manifest.txt")"
  fi
  if [[ -z "${TRACE_INPUTS}" ]]; then
    local tbase="${LLVM_PREFETCH_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces"
    TRACE_INPUTS="${tbase}/baseline_qsort_${MAX_CYCLES}_trace01/l2_miss:${tbase}/baseline_qsort_${MAX_CYCLES}_trace02/l2_miss:${tbase}/baseline_qsort_${MAX_CYCLES}_trace03/l2_miss"
  fi
}

main_complete() {
  local dir="$1"
  [[ -f "${dir}/plateau_final_report.md" ]] && grep -q "prefetch plateau search complete" "${dir}/plateau_search.log" 2>/dev/null
}

exact_compare_complete() {
  local dir="$1"
  [[ -f "${dir}/exact_best_compare/compare.done" ]]
}

print_best_summary() {
  local dir="$1"
  python3 - "${dir}" <<'PY' 2>/dev/null || true
import csv
import math
import sys
from pathlib import Path

root = Path(sys.argv[1])
best = None
count = 0
for aggregate in sorted(root.glob("batch*/aggregate.csv")):
    with aggregate.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "ok":
                continue
            count += 1
            try:
                delta = float(row.get("elapsed_delta_pct", "nan"))
            except ValueError:
                continue
            if math.isfinite(delta) and (best is None or delta < best[0]):
                best = (delta, row.get("variant", ""), row.get("l2i_mpki_delta_pct", "nan"))
if best:
    print(f"successful_variants={count} best={best[1]} runtime_delta={best[0]} l2i_delta={best[2]}")
else:
    print(f"successful_variants={count} best=none")
PY
}

status_snapshot() {
  local dir="$1"
  log "status snapshot: dir=${dir}"
  df -h "${REPO_ROOT}" | tail -1 | tee -a "${LOG}"
  if tmux has-session -t "${SESSION}" 2>/dev/null; then
    log "main session active: ${SESSION}"
  else
    log "main session not active: ${SESSION}"
  fi
  print_best_summary "${dir}" | while IFS= read -r line; do log "${line}"; done
  ps -eo pid,etimes,stat,pcpu,pmem,cmd \
    | grep -E 'run_prefetch_until|run_prefetcht1|clang\+\+|make -f VTestDriver|run_detailed_profile|perf ' \
    | grep -v grep | head -20 | tee -a "${LOG}" || true
  if [[ -f "${dir}/plateau_search.log" ]]; then
    log "plateau tail:"
    tail -12 "${dir}/plateau_search.log" | tee -a "${LOG}"
  fi
  local latest_variant
  latest_variant="$(find "${dir}" -path '*/runs/*.driver.log' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
  if [[ -n "${latest_variant}" ]]; then
    log "latest variant log: ${latest_variant}"
    tail -18 "${latest_variant}" | tee -a "${LOG}"
  fi
}

start_main_session() {
  local new_run_id="$1"
  RUN_ID="${new_run_id}"
  OUT_DIR="${LLVM_PREFETCH_DIR}/results/prefetch_plateau/${RUN_ID}"
  load_trace_inputs_from_dir "${OUT_DIR}"
  log "starting main session ${SESSION}: RUN_ID=${RUN_ID}"
  local cmd
  cmd="cd ${REPO_ROOT} && TRACE_INPUTS='${TRACE_INPUTS}' RUN_ID='${RUN_ID}' MIN_IMPROVEMENT_ABS_PCT='${MIN_IMPROVEMENT_ABS_PCT}' PATIENCE_BATCHES='${PATIENCE_BATCHES}' SCREEN_ITERATIONS='${SCREEN_ITERATIONS}' FINAL_ITERATIONS='${FINAL_ITERATIONS}' RUN_RESIDUAL_TRACE='${RUN_RESIDUAL_TRACE}' RUN_FINAL_COMPARE='${RUN_FINAL_COMPARE}' MAX_BATCHES='${MAX_BATCHES}' BUILD_JOBS='${BUILD_JOBS}' /home/hnpark2/prefetchit/llvm_prefetchit/scripts/run_prefetch_until_plateau.sh"
  tmux new-session -d -s "${SESSION}" "${cmd}"
}

known_fatal_errors_present() {
  local dir="$1"
  local recent
  recent="$(find "${dir}" -path '*/runs/*.driver.log' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -4 | cut -d' ' -f2-)"
  [[ -n "${recent}" ]] || return 1
  grep -E 'rg: command not found|No rule to make target|line [0-9]+: e: command not found' ${recent} >/dev/null 2>&1
}

run_exact_compare_if_ready() {
  local dir="$1"
  if exact_compare_complete "${dir}"; then
    log "exact compare already complete: ${dir}/exact_best_compare"
    return 0
  fi
  if ! main_complete "${dir}"; then
    return 1
  fi
  run_known_variant_repairs_if_ready "${dir}" || {
    log "known variant repair failed or is incomplete; will retry before exact compare"
    return 1
  }
  load_trace_inputs_from_dir "${dir}"
  log "running exact-target final scheme compare"
  PLATEAU_DIR="${dir}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  FINAL_ITERATIONS="${FINAL_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE}" \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetch_scheme_compare_from_best.sh" \
    > "${dir}/exact_best_compare.driver.log" 2>&1
}

run_known_variant_repairs_if_ready() {
  local dir="$1"
  local malformed_v02_log="${dir}/batch1/runs/v02_999999.driver.log"
  local malformed_v04_log="${dir}/batch1/runs/v04_99999.driver.log"
  local repair_done="${dir}/batch1_repair/repair.done"
  if [[ -f "${repair_done}" ]]; then
    return 0
  fi

  load_trace_inputs_from_dir "${dir}"
  local repair_dir="${dir}/batch1_repair"
  local variants="${dir}/batches/batch1_repair_variants.txt"
  mkdir -p "${repair_dir}" "${dir}/batches"
  : > "${variants}"
  if [[ -f "${malformed_v02_log}" ]] && grep -q "invalid float value: '0,64'" "${malformed_v02_log}" 2>/dev/null; then
    cat >> "${variants}" <<'EOF_REPAIR'
cov50_tops_d4_16_b16_o2|999999|4|16|16|top-sites|1|0|50|0,64|
EOF_REPAIR
  fi
  if [[ -f "${malformed_v04_log}" ]] && grep -q "invalid float value: '0,64'" "${malformed_v04_log}" 2>/dev/null; then
    cat >> "${variants}" <<'EOF_REPAIR'
cov50_tops_d4_24_b8_o2|999999|4|24|8|top-sites|1|0|50|0,64|
EOF_REPAIR
  fi
  if [[ -f "${dir}/batch2/autotune.log" ]] && grep -q "skip malformed variant line: .*|75|0,64|CALL:2-8" "${dir}/batch2/autotune.log" 2>/dev/null; then
    cat >> "${variants}" <<'EOF_REPAIR'
cov75_bp_tops_d1_32_b8_o2|999999|1|32|8|top-sites|1|0|75|0,64|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
EOF_REPAIR
  fi
  if [[ -f "${dir}/batch3/autotune.log" ]] && grep -q "skip malformed variant line: .*|50|0,64,128,192|CALL:2-8" "${dir}/batch3/autotune.log" 2>/dev/null; then
    cat >> "${variants}" <<'EOF_REPAIR'
cov50_bp_tops_d1_32_b8_o4|999999|1|32|8|top-sites|1|0|50|0,64,128,192|CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
EOF_REPAIR
  fi
  if [[ ! -s "${variants}" ]]; then
    return 0
  fi

  log "repairing malformed skipped variants via ${repair_dir}"
  RUN_ID="batch1_repair" \
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
    > "${repair_dir}.driver.log" 2>&1 || {
      log "repair variant failed; see ${repair_dir}.driver.log"
      return 1
    }
  touch "${repair_done}"
  log "repair variant complete: ${repair_dir}"
}

recover_if_needed() {
  local dir="$1"
  if tmux has-session -t "${SESSION}" 2>/dev/null; then
    if known_fatal_errors_present "${dir}"; then
      log "known fatal error detected in active run; restarting with patched scripts"
      tmux kill-session -t "${SESSION}" 2>/dev/null || true
      start_main_session "plateau_watchdog_restart_$(date +%Y%m%d_%H%M%S)"
    fi
    return
  fi

  if main_complete "${dir}"; then
    run_exact_compare_if_ready "${dir}" || log "exact compare not ready or failed; will retry next poll"
    return
  fi

  log "main session is down before completion; restarting from a clean run id"
  start_main_session "plateau_watchdog_restart_$(date +%Y%m%d_%H%M%S)"
}

main() {
  local dir
  dir="$(latest_plateau_dir)"
  if [[ -z "${dir}" ]]; then
    start_main_session "plateau_watchdog_$(date +%Y%m%d_%H%M%S)"
    dir="$(latest_plateau_dir)"
  fi
  load_trace_inputs_from_dir "${dir}"
  log "watchdog start: session=${SESSION} poll_sec=${POLL_SEC} dir=${dir}"
  while true; do
    dir="$(latest_plateau_dir)"
    status_snapshot "${dir}"
    recover_if_needed "${dir}"
    sleep "${POLL_SEC}"
  done
}

main "$@"
