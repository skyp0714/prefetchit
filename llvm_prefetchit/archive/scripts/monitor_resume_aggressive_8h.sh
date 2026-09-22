#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"

SOCKET="${SOCKET:-${LLVM_PREFETCH_DIR}/results/prefetch_watchdog/tmux/prefetch.sock}"
SESSION="${SESSION:-prefetch_resume8h}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
OUT_DIR="${OUT_DIR:?OUT_DIR is required}"
DURATION_HOURS="${DURATION_HOURS:-8}"
POLL_SEC="${POLL_SEC:-3600}"
BUILD_JOBS="${BUILD_JOBS:-32}"
PROFILE_CORE="${PROFILE_CORE:-0}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE:-1}"
LOG="${OUT_DIR}/monitor.log"

START_EPOCH="$(date +%s)"
END_EPOCH="$((START_EPOCH + DURATION_HOURS * 3600))"

mkdir -p "${OUT_DIR}"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

session_active() {
  tmux -S "${SOCKET}" has-session -t "${SESSION}" 2>/dev/null
}

final_done() {
  [[ -f "${OUT_DIR}/resume_aggressive_final_status.md" ]]
}

restart_main() {
  log "main session is down before final status; restarting ${SESSION}"
  tmux -S "${SOCKET}" new-session -d -s "${SESSION}" \
    "cd ${REPO_ROOT} && RUN_ID='${RUN_ID}' OUT_DIR='${OUT_DIR}' DURATION_HOURS='${DURATION_HOURS}' BUILD_JOBS='${BUILD_JOBS}' PROFILE_CORE='${PROFILE_CORE}' FINAL_ITERATIONS='${FINAL_ITERATIONS}' SCREEN_ITERATIONS='${SCREEN_ITERATIONS}' RUN_RESIDUAL_TRACE='${RUN_RESIDUAL_TRACE}' bash ${LLVM_PREFETCH_DIR}/scripts/run_resume_aggressive_8h.sh"
}

snapshot() {
  log "snapshot: seconds_left=$((END_EPOCH - $(date +%s)))"
  df -h "${REPO_ROOT}" | tee -a "${LOG}" || true
  if session_active; then
    log "main session active: ${SESSION}"
  else
    log "main session inactive: ${SESSION}"
  fi
  ps -eo pid,ppid,stat,etime,pcpu,pmem,args \
    | egrep 'run_resume_aggressive|run_prefetch_scheme|run_prefetcht1|VTestDriver|clang\+\+|make -f VTestDriver|perf|qsort' \
    | grep -v egrep | head -30 | tee -a "${LOG}" || true
  for path in \
    "${OUT_DIR}/resume_aggressive_8h.log" \
    "${OUT_DIR}/batch_aggressive/autotune.log" \
    "${OUT_DIR}/exact_best_compare/compare.log" \
    "${OUT_DIR}/resume_aggressive_final_status.md"; do
    if [[ -f "${path}" ]]; then
      log "tail ${path}"
      tail -30 "${path}" | tee -a "${LOG}" || true
    fi
  done
}

main() {
  log "monitor start: run_id=${RUN_ID} out=${OUT_DIR} session=${SESSION}"
  while (( $(date +%s) < END_EPOCH )); do
    snapshot
    if final_done; then
      log "final status present; monitor exiting"
      return 0
    fi
    if ! session_active; then
      restart_main || log "restart failed"
    fi
    sleep "${POLL_SEC}"
  done
  snapshot
  log "monitor done: duration reached"
}

main "$@"
